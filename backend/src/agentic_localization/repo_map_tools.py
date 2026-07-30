"""
Repo-map-backed tools for the guided-crawl resolver (Anthropic tool specs + handlers).

Handlers read the checkout at `repo_root` and query `RepoMap` for structure; they do not
expose the whole map to the model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import RepoMap, SymbolRecord

MAX_READ_LINES = 200
MAX_SEARCH_HITS = 25

REPO_MAP_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "lookup_symbol",
        "description": (
            "Resolve a planner anchor on the repo map. Returns the symbol's line range "
            "and numbered candidate_spans to cite in the final JSON (spans field)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "qualified_name": {
                    "type": "string",
                    "description": "Anchor symbol, e.g. CURLTrainer.compute_loss",
                },
                "filepath": {
                    "type": "string",
                    "description": "File from the planner; use to disambiguate.",
                },
            },
            "required": ["qualified_name"],
        },
    },
    {
        "name": "read_lines",
        "description": "Read a 1-based inclusive line range from a file in the repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
            "required": ["filepath", "start_line", "end_line"],
        },
    },
    {
        "name": "search_code",
        "description": (
            "Search for a literal substring in repository files. "
            "Pass filepath to scope to one file; otherwise planner files are searched first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "filepath": {"type": "string"},
            },
            "required": ["query"],
        },
    },
]


def _symbol_payload(record: SymbolRecord) -> dict[str, Any]:
    return {
        "qualified_name": record.qualified_name,
        "node_type": record.node_type,
        "start_line": record.start_line,
        "end_line": record.end_line,
        "docstring_preview": (record.docstring or "")[:300],
        "candidate_spans": [
            {"index": i, **s.model_dump()} for i, s in enumerate(record.candidate_spans())
        ],
    }


class RepoMapToolRunner:
    def __init__(
        self,
        repo_map: RepoMap,
        repo_root: Path,
        *,
        prefer_filepaths: list[str] | None = None,
    ) -> None:
        self.repo_map = repo_map
        self.repo_root = repo_root.resolve()
        self.prefer_filepaths = [p.lstrip("./") for p in (prefer_filepaths or []) if p]

    def dispatch(self, name: str, inputs: dict[str, Any]) -> str:
        try:
            if name == "lookup_symbol":
                return self._lookup_symbol(inputs)
            if name == "read_lines":
                return self._read_lines(inputs)
            if name == "search_code":
                return self._search_code(inputs)
            return json.dumps({"error": f"unknown tool: {name}"})
        except Exception as exc:  # noqa: BLE001 — tool errors go back to the model
            return json.dumps({"error": str(exc)})

    def _lookup_symbol(self, inputs: dict[str, Any]) -> str:
        qn = (inputs.get("qualified_name") or "").strip()
        fp = (inputs.get("filepath") or "").strip().lstrip("./") or None
        if not qn:
            return json.dumps({"found": False, "error": "qualified_name required"})
        entries = self.repo_map.lookup(qn)
        if fp:
            entries = [e for e in entries if e.filepath == fp]
        if not entries:
            return json.dumps({"found": False, "qualified_name": qn, "filepath": fp})
        entry = entries[0]
        record = self.repo_map.symbol(qn, filepath=entry.filepath)
        if record is None:
            return json.dumps({"found": False, "qualified_name": qn, "filepath": entry.filepath})
        return json.dumps(
            {
                "found": True,
                "filepath": entry.filepath,
                "symbol": _symbol_payload(record),
            }
        )

    def _safe_path(self, filepath: str) -> Path | None:
        rel = filepath.lstrip("./")
        full = (self.repo_root / rel).resolve()
        try:
            full.relative_to(self.repo_root)
        except ValueError:
            return None
        return full if full.is_file() else None

    def _read_lines(self, inputs: dict[str, Any]) -> str:
        fp = (inputs.get("filepath") or "").strip()
        start = max(1, int(inputs.get("start_line", 1)))
        end = int(inputs.get("end_line", start))
        if end < start:
            end = start
        if end - start + 1 > MAX_READ_LINES:
            end = start + MAX_READ_LINES - 1
        path = self._safe_path(fp)
        if path is None:
            return json.dumps({"error": "file not found", "filepath": fp})
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        chunk = lines[start - 1 : end]
        end_line = start + len(chunk) - 1 if chunk else start
        return json.dumps(
            {
                "filepath": fp.lstrip("./"),
                "start_line": start,
                "end_line": end_line,
                "content": "\n".join(chunk),
            }
        )

    def _search_code(self, inputs: dict[str, Any]) -> str:
        query = inputs.get("query") or ""
        scope = (inputs.get("filepath") or "").strip().lstrip("./")
        if not query:
            return json.dumps({"hits": []})
        file_list: list[str] = []
        if scope:
            file_list = [scope]
        else:
            seen: set[str] = set()
            for rel in self.prefer_filepaths:
                if rel not in seen:
                    file_list.append(rel)
                    seen.add(rel)
            for f in self.repo_map.files:
                if f.filepath in seen or f.language != "python":
                    continue
                file_list.append(f.filepath)
                seen.add(f.filepath)
        hits: list[dict[str, Any]] = []
        for rel in file_list:
            path = self._safe_path(rel)
            if path is None:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if query in line:
                    hits.append({"filepath": rel, "line": i, "text": line.strip()[:200]})
                    if len(hits) >= MAX_SEARCH_HITS:
                        break
            if len(hits) >= MAX_SEARCH_HITS:
                break
        return json.dumps({"query": query, "hits": hits})
