"""
CLI for the v0 repo map (see REPO_MAP_SCHEMA.md). Run from `backend/`.

    # build + cache a map, and report minimal-view token cost
    python -m src.agentic_localization.main build --path src/temp/Atari-PB \
        --repo-url https://github.com/dojeon-ai/Atari-PB

    # inspect the two views
    python -m src.agentic_localization.main show --path src/temp/Atari-PB --minimal
    python -m src.agentic_localization.main show --path src/temp/Atari-PB \
        --symbol CURLTrainer.compute_loss --spans

    # oracle ceiling of the candidate spans against the annotation ground truth
    python -m src.agentic_localization.main oracle --paper 1
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .repo_map import (
    DEFAULT_CACHE_DIR,
    build_repo_map,
    cache_path,
    estimate_tokens,
    load_or_build,
    minimal_dict,
    render_minimal_view,
    save_repo_map,
)
from .schema import RepoMap, SymbolRecord

ANNOTATIONS_PATH = Path(__file__).parents[1] / "evals" / "annotations" / "manual_v1.json"
REPOS_DIR = Path(__file__).parents[1] / "temp"


def _iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    overlap = max(0, min(a[1], b[1]) - max(a[0], b[0]) + 1)
    if overlap == 0:
        return 0.0
    union = (a[1] - a[0] + 1) + (b[1] - b[0] + 1) - overlap
    return overlap / union


def cmd_build(args: argparse.Namespace) -> None:
    repo_map = build_repo_map(
        args.path, repo_url=args.repo_url, skip_vendored=not args.include_vendored
    )
    out = Path(args.out) if args.out else cache_path(args.path, args.cache_dir)
    save_repo_map(repo_map, out)

    text = render_minimal_view(repo_map)
    as_json = json.dumps(minimal_dict(repo_map))
    print(f"{repo_map.repo_url} @ {repo_map.commit_sha[:7]}")
    for key, value in repo_map.stats().items():
        print(f"  {key}: {value}")
    print(f"  minimal view (text): {len(text)} chars, ~{estimate_tokens(text)} tokens")
    print(f"  minimal view (json): {len(as_json)} chars, ~{estimate_tokens(as_json)} tokens")
    print(f"  full map written to {out} ({out.stat().st_size // 1024} KB)")


def _print_symbol(symbol: SymbolRecord, show_spans: bool) -> None:
    print(f"{symbol.qualified_name}  {symbol.start_line}-{symbol.end_line}  ({symbol.node_type})")
    if symbol.signature:
        print(f"  signature: {symbol.signature.render()}")
    if symbol.docstring:
        print(f"  docstring: {symbol.docstring.splitlines()[0]}")
    if symbol.calls:
        print(f"  calls: {', '.join(symbol.calls)}")
    if symbol.dependencies:
        print(f"  dependencies: {', '.join(symbol.dependencies)}")
    if symbol.complexity:
        print(f"  complexity: {symbol.complexity}")
    for block in symbol.blocks:
        calls = f"  [{', '.join(block.call_names)}]" if block.call_names else ""
        print(f"  block {block.start_line}-{block.end_line}: {block.label}{calls}")
    if show_spans:
        print("  candidate spans:")
        for span in symbol.candidate_spans():
            print(f"    {span.kind:8s} {span.start_line}-{span.end_line}  {span.label}")


def cmd_show(args: argparse.Namespace) -> None:
    repo_map = load_or_build(args.path, repo_url=args.repo_url, cache_dir=args.cache_dir, rebuild=args.rebuild)

    if args.minimal:
        print(render_minimal_view(repo_map, include_tests=args.include_tests))
        return
    if args.file:
        record = repo_map.file(args.file)
        if record is None:
            sys.exit(f"{args.file} not in map")
        print(record.model_dump_json(indent=1))
        return
    if args.symbol:
        entries = repo_map.lookup(args.symbol)
        if not entries:
            sys.exit(f"{args.symbol} not in symbol table")
        for entry in entries:
            print(f"== {entry.filepath}")
            symbol = repo_map.symbol(entry.qualified_name, filepath=entry.filepath)
            if symbol is None:
                print(f"   {entry.qualified_name} {entry.start_line}-{entry.end_line} ({entry.node_type})")
            else:
                _print_symbol(symbol, args.spans)
        return
    for key, value in repo_map.stats().items():
        print(f"{key}: {value}")


def _oracle_for_location(repo_map: RepoMap, filepath: str, gt: tuple[int, int]) -> dict | None:
    """Best achievable IoU per candidate tier for one ground-truth range."""
    record = repo_map.file(filepath)
    if record is None:
        return None
    # A file the minimal view drops is a file the planner cannot pick.
    in_minimal = bool(record.loc) and not record.is_test and not record.is_vendored

    overlapping = [c for c in record.candidates() if _iou((c.start_line, c.end_line), gt) > 0]
    named = [c for c in overlapping if c.node_type != "module_scope"]
    scopes = [c for c in overlapping if c.node_type == "module_scope"]
    if not named and not scopes:
        return {"in_map": True, "in_minimal": in_minimal, "in_symbol": False}
    enclosing = max(
        named + scopes,
        key=lambda s: (_iou((s.start_line, s.end_line), gt), -(s.end_line - s.start_line)),
    )

    best: dict[str, float] = {"function": 0.0, "block": 0.0, "merged": 0.0}
    for span in enclosing.candidate_spans():
        best[span.kind] = max(best[span.kind], _iou((span.start_line, span.end_line), gt))
    return {
        "in_map": True,
        "in_minimal": in_minimal,
        "in_symbol": True,
        "in_named_symbol": bool(named),
        "symbol": enclosing.qualified_name,
        "n_blocks": len(enclosing.blocks),
        **best,
        "best": max(best.values()),
    }


def _ensure_repo(repo_url: str, repos_dir: str | Path) -> Path:
    name = repo_url.split("/")[-1].replace(".git", "")
    path = Path(repos_dir) / name
    if not path.exists():
        print(f"cloning {repo_url} -> {path}")
        subprocess.run(["git", "clone", "--depth", "1", repo_url, str(path)], check=True)
    return path


def cmd_oracle(args: argparse.Namespace) -> None:
    data = json.loads(Path(args.annotations).read_text())
    papers = data.get("papers", [])
    if args.paper is not None:
        papers = [papers[args.paper - 1]]

    rows: list[tuple[str, list[dict]]] = []
    for paper in papers:
        repo_url = (paper.get("repo_path") or "").rstrip(". ")
        repo_path = _ensure_repo(repo_url, args.repos_dir)
        repo_map = load_or_build(repo_path, repo_url=repo_url, cache_dir=args.cache_dir, rebuild=args.rebuild)

        results: list[dict] = []
        for annotation in paper.get("annotations", []):
            for location in annotation.get("locations", []):
                filepath = location.get("filepath") or ""
                line_range = location.get("line_range") or []
                if len(line_range) != 2 or not filepath.endswith(".py"):
                    continue
                result = _oracle_for_location(repo_map, filepath, (line_range[0], line_range[1]))
                results.append(result or {"in_map": False, "in_symbol": False})
        rows.append(((paper.get("paper_id") or repo_path.name)[:44], results))

    header = (
        f"{'paper':46s} {'n':>4s} {'in_map':>7s} {'in_min':>7s} {'in_fn':>6s} {'anchor':>7s} "
        f"{'span':>6s} {'block':>6s} {'merged':>6s} {'best':>6s}"
    )
    print(header)
    print("-" * len(header))
    all_results: list[dict] = []
    for label, results in rows:
        print(_oracle_row(label, results))
        all_results.extend(results)
    print("-" * len(header))
    print(_oracle_row("ALL", all_results))


def _oracle_row(label: str, results: list[dict]) -> str:
    n = len(results)
    if n == 0:
        return f"{label:46s} {0:>4d}"
    in_map = sum(1 for r in results if r.get("in_map"))
    in_minimal = sum(1 for r in results if r.get("in_minimal"))
    in_named = sum(1 for r in results if r.get("in_named_symbol"))
    anchored = [r for r in results if r.get("in_symbol")]

    def mean(key: str) -> float:
        # Averaged over every .py ground-truth range, so unparsed or
        # unanchored ranges count as 0 IoU.
        return sum(r.get(key, 0.0) for r in anchored) / n if n else 0.0

    return (
        f"{label:46s} {n:>4d} {in_map:>7d} {in_minimal:>7d} {in_named:>6d} {len(anchored):>7d} "
        f"{mean('function'):>6.3f} {mean('block'):>6.3f} {mean('merged'):>6.3f} {mean('best'):>6.3f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build and cache a repo map")
    build.add_argument("--path", required=True, help="Path to a repo checkout")
    build.add_argument("--repo-url", default=None)
    build.add_argument("--out", default=None, help="Write the full map here instead of the cache")
    build.add_argument(
        "--include-vendored", action="store_true", help="Keep nested/vendored packages in the map"
    )
    build.set_defaults(func=cmd_build)

    show = subparsers.add_parser("show", help="Inspect the minimal or full view")
    show.add_argument("--path", required=True)
    show.add_argument("--repo-url", default=None)
    show.add_argument("--rebuild", action="store_true")
    show.add_argument("--minimal", action="store_true", help="Print the planner blob")
    show.add_argument("--include-tests", action="store_true")
    show.add_argument("--file", default=None, help="Full view for one file")
    show.add_argument("--symbol", default=None, help="Full view for one symbol")
    show.add_argument("--spans", action="store_true", help="List candidate spans for --symbol")
    show.set_defaults(func=cmd_show)

    oracle = subparsers.add_parser(
        "oracle", help="Best achievable IoU of the candidate spans against ground truth"
    )
    oracle.add_argument("--annotations", default=str(ANNOTATIONS_PATH))
    oracle.add_argument("--repos-dir", default=str(REPOS_DIR))
    oracle.add_argument("--paper", type=int, default=None, help="1-indexed paper to restrict to")
    oracle.add_argument("--rebuild", action="store_true")
    oracle.set_defaults(func=cmd_oracle)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
