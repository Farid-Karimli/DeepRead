"""
Programmatically upload and analyze one or more papers.

This mirrors the live /analyze flow without going through FastAPI/Celery:
    1. Read a local filepath or download a URL into raw bytes.
    2. Derive paper_id = sha256(raw bytes).
    3. Upload the original paper bytes to Supabase storage.
    4. Check Supabase for an existing paper row unless --force is passed.
    5. Extract/normalize paper text and run Agent.analyze_paper().
    6. Upsert the result to Supabase metadata.

Usage (from repo root):
    cd backend
    uv run python scripts/analyze_papers.py papers/flow.pdf https://example.com/paper.pdf
    uv run python scripts/analyze_papers.py --input-list papers.txt --force

Each input is processed sequentially so progress logs and streamed agent events stay readable.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import mimetypes
import sys
import time
from datetime import UTC, datetime
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests


REPO_BACKEND = Path(__file__).resolve().parents[1]
if str(REPO_BACKEND) not in sys.path:
    sys.path.insert(0, str(REPO_BACKEND))

from src.types import PaperRecord


@dataclass(frozen=True)
class PaperUpload:
    source: str
    filename: str
    raw: bytes


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def _filename_from_url(url: str, response: requests.Response) -> str:
    content_disposition = response.headers.get("content-disposition", "")
    marker = "filename="
    if marker in content_disposition:
        filename = content_disposition.split(marker, 1)[1].strip().strip('"')
        if filename:
            return filename

    parsed = urlparse(url)
    basename = Path(unquote(parsed.path)).name
    if basename:
        return basename

    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
    extension = mimetypes.guess_extension(content_type) or ".pdf"
    return f"downloaded-paper{extension}"


def _read_input(source: str, timeout: int) -> PaperUpload:
    if _is_url(source):
        print(f"[step] downloading {source}")
        response = requests.get(source, timeout=timeout)
        response.raise_for_status()
        filename = _filename_from_url(source, response)
        return PaperUpload(source=source, filename=filename, raw=response.content)

    if source.startswith("file://"):
        local_path = Path(unquote(urlparse(source).path)).expanduser()
    else:
        local_path = Path(source).expanduser()
    local_path = local_path.resolve()
    if not local_path.exists():
        raise FileNotFoundError(f"Paper not found: {local_path}")
    if not local_path.is_file():
        raise IsADirectoryError(f"Paper input is not a file: {local_path}")
    return PaperUpload(source=str(local_path), filename=local_path.name, raw=local_path.read_bytes())


def _extract_metadata(result: dict) -> tuple[str, str]:
    title = result.get("paper_title")
    link = result.get("github_repo_url")
    code_result = result.get("code_result")
    if not link and isinstance(code_result, dict):
        link = code_result.get("github_repo_url")
    if not title and isinstance(code_result, dict):
        code_title = code_result.get("paper_title")
        if isinstance(code_title, str):
            title = code_title
    return (
        title if isinstance(title, str) else "",
        link if isinstance(link, str) else "",
    )


def _output_path(out_dir: Path, filename: str, paper_id: str) -> Path:
    stem = Path(filename).stem or "paper"
    safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in stem)
    return out_dir / f"{safe_stem}.{paper_id[:12]}.analyze_paper.json"


def _read_input_list(path: Path) -> list[str]:
    if str(path) == "-":
        raw = sys.stdin.read()
    else:
        raw = path.read_text(encoding="utf-8")
    return [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _unified_from_paper_record(paper_record: PaperRecord) -> dict:
    dumped = paper_record.model_dump(mode="json")
    return {
        "analysis": dumped.get("analysis_result"),
        "processed": dumped.get("papermage_result"),
    }


async def _analyze_one(
    source: str,
    *,
    model: str,
    out_dir: Path,
    force: bool,
    stream_events: bool,
    timeout: int,
) -> bool:
    started = time.perf_counter()
    print("")
    print(f"[paper] source={source}")

    upload = _read_input(source, timeout=timeout)
    paper_id = hashlib.sha256(upload.raw).hexdigest()
    print(f"[info] filename={upload.filename}")
    print(f"[info] bytes={len(upload.raw)}")
    print(f"[info] paper_id={paper_id}")

    from src.db import get_paper_record_by_id, upsert_paper, upload_paper_to_storage

    print("[step] uploading paper bytes to Supabase storage...")
    upload_paper_to_storage(
        paper_name=upload.filename,
        paper_id=paper_id,
        paper_content=upload.raw,
    )

    if not force:
        paper_record = get_paper_record_by_id(paper_id)
        if paper_record is not None and paper_record.analysis_result is not None:
            unified_result = _unified_from_paper_record(paper_record)
            out_path = _output_path(out_dir, upload.filename, paper_id)
            out_path.write_text(
                json.dumps(unified_result, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"[cache] hit supabase paper_id={paper_id}")
            print(f"[done] wrote cached result to {out_path}")
            return True

    print("[step] processing PDF with Papermage...")
    from src.process_pdf import papermage_process

    papermage_result = papermage_process(file_input=upload.raw)

    print("[step] running agent.analyze_paper with streamed events...")
    from src.agent import Agent
    from src.utils import print_event

    agent = Agent(model=model, stream_events=stream_events)
    result = await agent.analyze_paper(
        file_input=upload.raw,
        papermage_process_result=papermage_result,
        on_event=print_event,
    )

    title, link = _extract_metadata(result)
    print(f"[info] paper_title={title!r}")
    print(f"[info] github_repo_url={link!r}")
    print("[step] upserting Supabase paper row...")
    upsert_paper(
        paper_record=PaperRecord(
            id=paper_id,
            paper_title=title,
            github_link=link,
            created_at=datetime.now(UTC),
            analysis_result=result,
            papermage_result=papermage_result,
        ),
    )

    unified_result = {
        "analysis": result,
        "processed": papermage_result,
    }
    out_path = _output_path(out_dir, upload.filename, paper_id)
    out_path.write_text(json.dumps(unified_result, indent=2, ensure_ascii=False), encoding="utf-8")
    elapsed = time.perf_counter() - started
    print(f"[done] wrote result to {out_path}")
    print(f"[done] paper_id={paper_id} elapsed={elapsed:.1f}s")
    return True


async def _run(args: argparse.Namespace) -> int:
    inputs: list[str] = list(args.inputs)
    for input_list in args.input_list:
        inputs.extend(_read_input_list(input_list))

    if not inputs:
        raise SystemExit("Provide at least one paper URL/path or --input-list.")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[info] total_inputs={len(inputs)}")
    print(f"[info] out_dir={args.out_dir}")
    print(f"[info] model={args.model}")
    print(f"[info] stream_events={not args.no_events}")
    print(f"[info] force={args.force}")

    successes = 0
    failures = 0
    for index, source in enumerate(inputs, start=1):
        print("")
        print(f"[progress] {index}/{len(inputs)}")
        try:
            ok = await _analyze_one(
                source,
                model=args.model,
                out_dir=args.out_dir,
                force=args.force,
                stream_events=not args.no_events,
                timeout=args.timeout,
            )
            successes += int(ok)
        except Exception as exc:
            failures += 1
            print(f"[error] failed source={source}")
            print(f"[error] {type(exc).__name__}: {exc}")
            if not args.continue_on_error:
                raise

    print("")
    print(f"[summary] success={successes} failed={failures}")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Paper URLs, file:// URLs, or local file paths to analyze.",
    )
    parser.add_argument(
        "--input-list",
        action="append",
        type=Path,
        default=[],
        help="Newline-delimited file of URLs/paths. Use '-' to read from stdin.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_BACKEND / "scripts" / "out",
        help="Directory for per-paper analysis JSON outputs.",
    )
    parser.add_argument(
        "--model",
        default="sonnet",
        help="Claude Agent SDK model alias to pass into Agent.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run Papermage + agent and upsert even when a Supabase paper row already exists.",
    )
    parser.add_argument(
        "--no-events",
        action="store_true",
        help="Disable printing streamed Claude Agent SDK events.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Keep processing later inputs if one paper fails.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="HTTP download timeout in seconds.",
    )
    args = parser.parse_args()
    args.out_dir = args.out_dir.resolve()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
