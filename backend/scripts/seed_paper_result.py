"""
Seed an already-computed paper analysis result into Redis + Supabase.

Mirrors what /analyze + analyze_paper_task do, without re-running the agent:
    1. Read raw PDF bytes -> derive paper_id = sha256(bytes)
    2. Upload PDF to Supabase storage bucket "papers" (path = paper_id)
    3. Write the analysis JSON into Redis under the standard cache key
    4. Update the Supabase `papers` row metadata (title + github link)

Usage (from repo root):
    cd backend
    uv run python scripts/seed_paper_result.py \
        --pdf papers/vjepa.pdf \
        --result scripts/out/2506_09985v1.9cfcfde5fb0d.analyze_paper.json

Defaults match the request: pretraining-rl.pdf + pretraining-rl.analyze_paper.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_BACKEND = Path(__file__).resolve().parents[1]
if str(REPO_BACKEND) not in sys.path:
    sys.path.insert(0, str(REPO_BACKEND))

from src.db import (  # noqa: E402
    _bytea_hex_payload,
    get_paper_row,
    get_supabase_client,
    is_configured as supabase_configured,
    upload_paper_to_storage,
)
from src.paper_analysis_cache import (  # noqa: E402
    cache_key_for_paper_id,
    get_cached_result,
    set_cached_result,
)


def _upsert_paper_row(
    paper_id: str,
    paper_title: str | None,
    github_link: str | None,
    paper_content: bytes,
) -> None:
    """
    Insert-or-update a row in the `papers` table.

    Live `/analyze` never inserts a row (only storage + Redis), so a bare UPDATE
    is a silent no-op. For seeding we want the row to exist, so use upsert.
    `paper_content` is included as bytea hex to satisfy any NOT NULL constraint
    (matches the legacy save_paper_upload_bytes shape).
    """
    supabase = get_supabase_client()
    payload = {
        "id": paper_id,
        "paper_title": (paper_title or "").strip(),
        "github_link": (github_link or "").strip(),
        "paper_content": _bytea_hex_payload(paper_content),
    }
    supabase.from_("papers").upsert(payload, on_conflict="id").execute()


def _extract_metadata(result: dict) -> tuple[str | None, str | None]:
    title = result.get("paper_title")
    link = result.get("github_repo_url")
    code_result = result.get("code_result") if isinstance(result, dict) else None
    if not link and isinstance(code_result, dict):
        link = code_result.get("github_repo_url")
    if not title and isinstance(code_result, dict):
        ct = code_result.get("paper_title")
        if isinstance(ct, str):
            title = ct
    return (
        title if isinstance(title, str) else None,
        link if isinstance(link, str) else None,
    )


def seed(pdf_path: Path, result_path: Path, papermage_result_path: Path) -> None:
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")
    if not result_path.exists():
        raise SystemExit(f"Analysis JSON not found: {result_path}")

    raw = pdf_path.read_bytes()
    paper_id = hashlib.sha256(raw).hexdigest()
    print(f"[info] pdf={pdf_path}")
    print(f"[info] result={result_path}")
    print(f"[info] paper_id={paper_id}")

    analysis_result = json.loads(result_path.read_text(encoding="utf-8"))
    papermage_result = json.loads(papermage_result_path.read_text(encoding="utf-8"))
    if not isinstance(analysis_result, dict) or not isinstance(papermage_result, dict):
        raise SystemExit("Analysis JSON and Papermage JSON must decode to an object/dict")

    title, link = _extract_metadata(analysis_result)
    print(f"[info] paper_title={title!r}")
    print(f"[info] github_repo_url={link!r}")

    if not supabase_configured():
        print("[warn] Supabase not configured (SUPABASE_URL/SUPABASE_KEY missing); "
              "Supabase steps will be skipped.")
    else:
        print("[step] uploading PDF to Supabase storage bucket 'papers'...")
        upload_paper_to_storage(
            paper_name=pdf_path.name,
            paper_id=paper_id,
            paper_content=raw,
        )

    print("[step] writing analysis result to Redis cache...")
    set_cached_result(paper_id, analysis_result, papermage_result)
    cached = get_cached_result(paper_id)
    if cached is None:
        print(f"[error] Redis cache write did not stick at key {cache_key_for_paper_id(paper_id)!r}")
    else:
        print(f"[ok] Redis cache key={cache_key_for_paper_id(paper_id)} (size={len(json.dumps(cached))} chars)")

    if supabase_configured():
        existing = get_paper_row(paper_id)
        verb = "updating" if existing is not None else "inserting"
        print(f"[step] {verb} Supabase `papers` row (title + github link)...")
        try:
            _upsert_paper_row(
                paper_id=paper_id,
                paper_title=title,
                github_link=link,
                paper_content=raw,
            )
            row = get_paper_row(paper_id)
            if row is None:
                print("[error] upsert reported success but row is not visible")
            else:
                print(f"[ok] papers row id={row.get('id')} title={row.get('paper_title')!r} github_link={row.get('github_link')!r}")
        except Exception as e:
            print(f"[error] papers upsert failed: {e}")
            print("        If the failure is about NOT NULL columns, add them to _upsert_paper_row in this script.")

    print(f"[done] paper_id={paper_id}")
    print("[done] frontend can fetch via GET /papers/{paper_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdf",
        type=Path,
        default=REPO_BACKEND / "papers" / "pretraining-rl.pdf",
        help="Path to the source PDF (used to derive paper_id and upload to storage).",
    )
    parser.add_argument(
        "--result",
        type=Path,
        default=REPO_BACKEND / "pretraining-rl.analyze_paper.json",
        help="Path to the precomputed analyze_paper JSON.",
    )
    parser.add_argument(
        "--papermage",
        type=Path, 
        default=REPO_BACKEND / "pretraining-papermage.json",
        help="Path to the papermage processing result JSON."
    )
    args = parser.parse_args()
    seed(args.pdf.resolve(), args.result.resolve(), args.papermage.resolve())


if __name__ == "__main__":
    main()
