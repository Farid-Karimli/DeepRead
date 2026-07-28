"""
Weights & Biases (Weave) tracing setup for DeepRead.

Provides a single, resilient entry point so tracing can be enabled across the
agent pipeline and the evaluation harness without hard-failing when W&B is
unavailable, offline, or intentionally disabled (``WEAVE_DISABLED=1``).

Also provides ``ToolTraceCollector`` for recording Claude Agent SDK tool calls
(Search / ReadFile / …) so process metrics can be analyzed offline and attached
to Weave calls.

Usage:
    from src.observability import init_weave, op, log_summary, ToolTraceCollector

    init_weave()                 # idempotent; safe to call multiple times

    @op                          # traces the call when weave is active, else no-op
    async def do_work(...): ...
"""
from __future__ import annotations

import functools
import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from src.config import WANDB_API_KEY, WEAVE_DISABLED, WEAVE_PROJECT

logger = logging.getLogger(__name__)

_client: Any = None
_initialized: bool = False
_active: bool = False

# Cap stored tool-result previews so prediction JSONs stay manageable.
_RESULT_PREVIEW_CHARS = 500


def init_weave(project: str | None = None) -> Any:
    """Initialize Weave once. Returns the weave client, or None if unavailable.

    Never raises: a tracing backend being down must not break the pipeline."""
    global _client, _initialized, _active
    if _initialized:
        return _client
    _initialized = True

    if WEAVE_DISABLED:
        logger.info("Weave tracing disabled via WEAVE_DISABLED")
        return None

    try:
        import weave

        if WANDB_API_KEY:
            os.environ.setdefault("WANDB_API_KEY", WANDB_API_KEY)
        _client = weave.init(project or WEAVE_PROJECT)
        _active = True
        logger.info("Weave initialized project=%s", project or WEAVE_PROJECT)
    except Exception as exc:  # network down, not logged in, package missing, etc.
        logger.warning("Weave init failed (%s); continuing without tracing", exc)
        _client = None
        _active = False
    return _client


def is_active() -> bool:
    return _active


def op(*op_args: Any, **op_kwargs: Any) -> Callable:
    """Decorator applying ``weave.op`` when available, else an identity wrapper.

    Supports both ``@op`` and ``@op(name=...)`` forms. Decoration happens at
    import time; actual trace emission only occurs after ``init_weave``."""

    def decorate(fn: Callable) -> Callable:
        if WEAVE_DISABLED:
            return fn
        try:
            import weave

            return weave.op(*op_args, **op_kwargs)(fn)
        except Exception as exc:
            logger.debug(
                "weave.op unavailable for %s (%s); using no-op",
                getattr(fn, "__name__", fn),
                exc,
            )

            @functools.wraps(fn)
            def passthrough(*args: Any, **kwargs: Any):
                return fn(*args, **kwargs)

            return passthrough

    # Bare @op usage: op_args == (fn,)
    if len(op_args) == 1 and callable(op_args[0]) and not op_kwargs:
        fn = op_args[0]
        op_args = ()
        return decorate(fn)

    return decorate


def log_summary(name: str, data: dict) -> None:
    """Attach a summary dict to the current weave call/run if tracing is active.

    Best-effort: silently does nothing when tracing is inactive."""
    if not _active:
        return
    try:
        import weave

        call = getattr(weave, "get_current_call", lambda: None)()
        if call is not None and hasattr(call, "summary"):
            call.summary[name] = data
    except Exception as exc:
        logger.debug("log_summary failed for %s (%s)", name, exc)


@contextmanager
def attributes(attrs: dict[str, Any]) -> Iterator[None]:
    """Attach metadata to the current Weave call. No-op when tracing is inactive."""
    if not _active or not attrs:
        yield
        return
    try:
        import weave

        with weave.attributes(attrs):
            yield
    except Exception as exc:
        logger.debug("weave.attributes failed (%s); continuing without attrs", exc)
        yield


def _preview_text(value: Any, limit: int = _RESULT_PREVIEW_CHARS) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        # Tool results sometimes arrive as [{type, text}, ...]
        parts = []
        for item in value:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        text = "\n".join(parts)
    else:
        text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + f"… (+{len(text) - limit} chars)"


def _normalize_tool_input(name: str, tool_input: dict[str, Any] | None) -> dict[str, Any]:
    """Pull the useful fields from Claude Code tool inputs under stable keys."""
    raw = tool_input if isinstance(tool_input, dict) else {}
    normalized: dict[str, Any] = {}

    # Common across Search / Grep / Glob / Read
    for key in (
        "pattern",
        "query",
        "path",
        "file_path",
        "glob",
        "include",
        "offset",
        "limit",
        "output_mode",
        "case_insensitive",
        "head_limit",
    ):
        if key in raw and raw[key] is not None:
            normalized[key] = raw[key]

    # Prefer a single "path" for reads
    if "file_path" in normalized and "path" not in normalized:
        normalized["path"] = normalized["file_path"]

    # Keep a small leftover bag so we don't lose unexpected fields silently.
    leftovers = {
        k: v
        for k, v in raw.items()
        if k not in normalized and k not in ("file_path",) and v is not None
    }
    if leftovers:
        # Bound size of leftover values
        trimmed = {}
        for k, v in list(leftovers.items())[:8]:
            if isinstance(v, str) and len(v) > 200:
                trimmed[k] = v[:200] + "…"
            else:
                trimmed[k] = v
        # Hoist common Bash fields out of "extra" for easier process metrics.
        if isinstance(trimmed.get("command"), str):
            normalized["command"] = trimmed.pop("command")
        if isinstance(trimmed.get("description"), str):
            normalized["description"] = trimmed.pop("description")
        if trimmed:
            normalized["extra"] = trimmed

    normalized["tool"] = name
    return normalized


class ToolTraceCollector:
    """Accumulates ordered tool-use / tool-result events from the Claude Agent SDK.

    Feed every streamed message via :meth:`ingest`. After the agent finishes,
    call :meth:`to_list` / :meth:`summarize` for persistence and Weave logging.
    """

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._started_at = time.perf_counter()
        self._pending: dict[str, int] = {}  # tool_use_id -> event index

    def ingest(self, message: Any) -> None:
        """Extract ToolUseBlock / ToolResultBlock from an SDK message."""
        try:
            from claude_agent_sdk.types import (
                AssistantMessage,
                ToolResultBlock,
                ToolUseBlock,
                UserMessage,
            )
        except ImportError:
            return

        content = getattr(message, "content", None)
        if content is None:
            return

        blocks = content if isinstance(content, list) else []
        for block in blocks:
            if isinstance(block, ToolUseBlock):
                self._record_tool_use(block)
            elif isinstance(block, ToolResultBlock):
                self._record_tool_result(block)

        # Some SDK versions also attach a consolidated tool_use_result on UserMessage
        if isinstance(message, UserMessage) and getattr(message, "tool_use_result", None):
            result = message.tool_use_result
            if isinstance(result, dict):
                self.events.append(
                    {
                        "step": len(self.events) + 1,
                        "kind": "tool_result_summary",
                        "t_offset_s": round(time.perf_counter() - self._started_at, 3),
                        "result_keys": sorted(result.keys()),
                        "preview": _preview_text(result),
                    }
                )

        # Silence unused-import warning if AssistantMessage unused in isinstance
        _ = AssistantMessage

    def _record_tool_use(self, block: Any) -> None:
        name = getattr(block, "name", "") or "unknown"
        tool_input = getattr(block, "input", None) or {}
        tool_use_id = getattr(block, "id", None)
        event = {
            "step": len(self.events) + 1,
            "kind": "tool_use",
            "t_offset_s": round(time.perf_counter() - self._started_at, 3),
            "tool_use_id": tool_use_id,
            "tool": name,
            "input": _normalize_tool_input(name, tool_input if isinstance(tool_input, dict) else {}),
        }
        self.events.append(event)
        if isinstance(tool_use_id, str):
            self._pending[tool_use_id] = len(self.events) - 1

    def _record_tool_result(self, block: Any) -> None:
        tool_use_id = getattr(block, "tool_use_id", None)
        content = getattr(block, "content", None)
        is_error = getattr(block, "is_error", None)
        preview = _preview_text(content)
        content_len = len(str(content)) if content is not None else 0

        # Prefer attaching the result onto the matching tool_use event
        if isinstance(tool_use_id, str) and tool_use_id in self._pending:
            idx = self._pending.pop(tool_use_id)
            self.events[idx]["result_preview"] = preview
            self.events[idx]["result_chars"] = content_len
            self.events[idx]["is_error"] = bool(is_error) if is_error is not None else False
            self.events[idx]["result_t_offset_s"] = round(
                time.perf_counter() - self._started_at, 3
            )
            return

        self.events.append(
            {
                "step": len(self.events) + 1,
                "kind": "tool_result",
                "t_offset_s": round(time.perf_counter() - self._started_at, 3),
                "tool_use_id": tool_use_id,
                "result_preview": preview,
                "result_chars": content_len,
                "is_error": bool(is_error) if is_error is not None else False,
            }
        )

    def to_list(self) -> list[dict[str, Any]]:
        return list(self.events)

    def summarize(self) -> dict[str, Any]:
        """Derive process metrics that answer: did the agent search before reading?"""
        uses = [e for e in self.events if e.get("kind") == "tool_use"]
        tool_names = [e.get("tool") for e in uses]

        def _is_search(name: str | None) -> bool:
            n = (name or "").lower()
            return n in {"search", "grep", "glob", "find"} or "grep" in n or "search" in n

        def _is_read(name: str | None) -> bool:
            n = (name or "").lower()
            return n in {"read", "readfile", "read_file"} or n.startswith("read")

        def _is_explore_bash(event: dict) -> bool:
            """Bash that lists dirs / finds files — treat as search-like exploration."""
            if (event.get("tool") or "").lower() != "bash":
                return False
            inp = event.get("input") or {}
            cmd = str(
                inp.get("command")
                or inp.get("cmd")
                or (inp.get("extra") or {}).get("command")
                or ""
            )
            cmd_l = cmd.lower()
            return any(
                token in cmd_l
                for token in ("ls ", "ls\n", "find ", "rg ", "grep ", "tree ", "fd ", "glob")
            )

        search_steps = [e for e in uses if _is_search(e.get("tool")) or _is_explore_bash(e)]
        read_steps = [e for e in uses if _is_read(e.get("tool"))]

        files_read: list[str] = []
        for e in read_steps:
            path = (e.get("input") or {}).get("path") or (e.get("input") or {}).get("file_path")
            if isinstance(path, str) and path and path not in files_read:
                files_read.append(path)

        search_patterns = []
        for e in search_steps:
            inp = e.get("input") or {}
            pat = inp.get("pattern") or inp.get("query")
            if isinstance(pat, str) and pat:
                search_patterns.append(pat)

        first_search_step = search_steps[0]["step"] if search_steps else None
        first_read_step = read_steps[0]["step"] if read_steps else None
        search_before_read = None
        if first_search_step is not None and first_read_step is not None:
            search_before_read = first_search_step < first_read_step
        elif first_search_step is not None and first_read_step is None:
            search_before_read = True
        elif first_search_step is None and first_read_step is not None:
            search_before_read = False

        return {
            "num_tool_calls": len(uses),
            "tool_sequence": tool_names,
            "num_searches": len(search_steps),
            "num_reads": len(read_steps),
            "num_unique_files_read": len(files_read),
            "files_read": files_read,
            "search_patterns": search_patterns[:20],
            "first_search_step": first_search_step,
            "first_read_step": first_read_step,
            "search_before_read": search_before_read,
            "duration_s": round(time.perf_counter() - self._started_at, 3),
            "num_errors": sum(1 for e in self.events if e.get("is_error")),
        }
