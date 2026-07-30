"""
Repo map builder (v0) for the two-agent localization pipeline.

Wraps `treesitter-chunker` output into the index described in
REPO_MAP_SCHEMA.md: one canonical index per checkout, a minimal view that is
serialized into the planner's prompt, and a full view queried per file/symbol
by the resolver.

Python only, single checkout, no cross-file resolution (see REPO_MAP_DEFERRED.md).

    from src.agentic_localization.repo_map import build_repo_map, render_minimal_view

    repo_map = build_repo_map("src/temp/Atari-PB", repo_url="https://github.com/dojeon-ai/Atari-PB")
    planner_prompt_blob = render_minimal_view(repo_map)
    symbol = repo_map.symbol("CURLTrainer.compute_loss")   # full view
    spans = symbol.candidate_spans()
"""

from __future__ import annotations

import ast
import bisect
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Any, Iterable

from chunker import chunk_file

from .schema import (
    BlockRecord,
    CallSite,
    ClassRecord,
    FileRecord,
    Parameter,
    RepoMap,
    Role,
    SignatureInfo,
    SymbolRecord,
    SymbolTableEntry,
)

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "build",
    "dist",
    ".eggs",
    ".mypy_cache",
    ".pytest_cache",
    ".ipynb_checkpoints",
    "site-packages",
}

VENDOR_DIRS = {
    "third_party",
    "thirdparty",
    "external",
    "extern",
    "vendor",
    "vendors",
    "submodules",
}

# (role, exact path tokens, substring stems). First match wins.
ROLE_RULES: list[tuple[Role, set[str], tuple[str, ...]]] = [
    (Role.LOSS, {"loss", "losses", "criterion", "criteria", "objective", "objectives"}, ("loss",)),
    (Role.TRAINER, {"trainer", "trainers", "train", "training", "learner", "engine", "solver"}, ("train",)),
    (Role.DATASET, {"data", "dataset", "datasets", "dataloader", "dataloaders", "loader", "loaders", "datamodule"}, ("dataset", "dataload")),
    (
        Role.MODEL,
        {
            "model", "models", "net", "nets", "network", "networks", "modules",
            "backbone", "backbones", "head", "heads", "neck", "necks", "arch",
            "archs", "architecture", "architectures", "encoder", "decoder",
            "layers", "attention", "transformer", "vit", "predictor",
        },
        ("model",),
    ),
    (Role.CONFIG, {"config", "configs", "cfg", "conf", "hparams", "hyperparams", "defaults", "settings"}, ("config",)),
    (Role.UTIL, {"util", "utils", "utilities", "helper", "helpers", "common", "misc", "ops"}, ("util",)),
]

SCRIPT_DIRS = {"scripts", "script", "tools", "bin", "apps", "examples", "experiments"}

# Library calls that carry enough meaning to survive the noise filter even
# though they resolve outside the repo.
LIB_ALLOWLIST = {
    "CrossEntropyLoss", "MSELoss", "L1Loss", "SmoothL1Loss", "BCELoss",
    "BCEWithLogitsLoss", "KLDivLoss", "NLLLoss", "CosineEmbeddingLoss",
    "cross_entropy", "mse_loss", "binary_cross_entropy",
    "binary_cross_entropy_with_logits", "kl_div", "smooth_l1_loss",
    "log_softmax", "softmax", "normalize", "cosine_similarity", "einsum",
    "rearrange", "repeat", "reduce", "interpolate", "scaled_dot_product_attention",
    "all_gather", "all_reduce", "broadcast", "barrier", "reduce_scatter",
    "no_grad", "autocast", "backward", "zero_grad", "clip_grad_norm_",
    "DataLoader", "DistributedSampler", "DistributedDataParallel",
    "Adam", "AdamW", "SGD", "LambdaLR", "CosineAnnealingLR", "OneCycleLR",
    "Linear", "Conv1d", "Conv2d", "Conv3d", "LayerNorm", "BatchNorm1d",
    "BatchNorm2d", "GroupNorm", "Dropout", "Embedding", "MultiheadAttention",
    "Sequential", "Parameter", "GradScaler", "checkpoint", "instantiate",
    "load_state_dict", "state_dict",
}

_COMMENT_PRAGMAS = ("type:", "noqa", "pylint", "flake8", "ruff", "mypy", "fmt:", "pragma", "isort", "-*-", "!/")
_CODE_LIKE = (
    re.compile(r"^(from|import|return|pass|break|continue|raise|assert|del|yield|global|nonlocal)\b"),
    re.compile(r"^(if|for|while|def|class|with|try|except|elif|else|async)\b.*:\s*$"),
    re.compile(r"^[A-Za-z_][\w\.\[\]\"']*\s*(=|\+=|-=|\*=|/=)[^=]"),
    re.compile(r"^(print|breakpoint|pprint)\s*\("),
)

_BOILERPLATE = re.compile(
    r"copyright|all rights reserved|licen[sc]ed? (under|in)|SPDX|"
    r"LICENSE file in the root|-\*- coding",
    re.IGNORECASE,
)

MAX_LABEL_CHARS = 120
MAX_SUMMARY_CHARS = 120


# --------------------------------------------------------------------------- #
# per-file source analysis
# --------------------------------------------------------------------------- #


class _LineIndex:
    """Absolute file byte offset -> 1-based line number.

    `metadata['call_spans']` offsets are absolute file offsets, so this maps
    them without any chunk-relative adjustment.
    """

    def __init__(self, source: str) -> None:
        data = source.encode("utf-8")
        self._starts = [0]
        for i, byte in enumerate(data):
            if byte == 0x0A:
                self._starts.append(i + 1)

    def line_of(self, byte_offset: int) -> int:
        return bisect.bisect_right(self._starts, byte_offset)


class _AstIndex:
    """Docstrings, decorators and base classes keyed by qualified name, plus
    the file's import list. These are `derived` fields in the schema; the
    chunker does not expose them (class chunks carry no `signature`)."""

    def __init__(self, source: str, filepath: str) -> None:
        self.docstrings: dict[str, str] = {}
        self.decorators: dict[str, list[str]] = {}
        self.bases: dict[str, list[str]] = {}
        self.imports: list[str] = []
        self.module_docstring: str | None = None
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return
        self.module_docstring = ast.get_docstring(tree)
        package = Path(filepath).parent.parts
        self._walk(tree, prefix=(), package=package)

    def _walk(self, node: ast.AST, prefix: tuple[str, ...], package: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                self.imports.extend(_import_names(child, package))
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualified = ".".join(prefix + (child.name,))
                docstring = ast.get_docstring(child)
                if docstring and qualified not in self.docstrings:
                    self.docstrings[qualified] = docstring
                self.decorators.setdefault(qualified, [_unparse(d) for d in child.decorator_list])
                if isinstance(child, ast.ClassDef):
                    self.bases.setdefault(qualified, [_unparse(b) for b in child.bases])
                self._walk(child, prefix + (child.name,), package)
            else:
                self._walk(child, prefix, package)


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _import_names(node: ast.Import | ast.ImportFrom, package: tuple[str, ...]) -> list[str]:
    """Non-stdlib module names. `from a.b import c` keeps `a.b`, `import a.b`
    keeps `a`, and relative imports are resolved against the file's package."""
    names: list[str] = []
    if isinstance(node, ast.Import):
        names = [alias.name.split(".")[0] for alias in node.names]
    else:
        module = node.module or ""
        if node.level:
            base = list(package[: len(package) - node.level + 1]) if node.level > 1 else list(package)
            module = ".".join([*base, module]) if module else ".".join(base)
        names = [module] if module else []
    return [n for n in names if n and n.split(".")[0] not in sys.stdlib_module_names]


def _own_line_comments(source: str) -> list[tuple[int, str]]:
    """Comments that occupy a whole line, as (line number, raw text). Uses
    `tokenize` so `#` inside strings is not mistaken for a comment."""
    comments: list[tuple[int, str]] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT and token.line.lstrip().startswith("#"):
                comments.append((token.start[0], token.string))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        for lineno, line in enumerate(source.splitlines(), start=1):
            if line.lstrip().startswith("#"):
                comments.append((lineno, line.strip()))
    return comments


def _clean_comment(text: str) -> str | None:
    """Comment text stripped of `#`. Returns None for pragmas, separator lines
    and commented-out code, which are not useful block labels."""
    label = text.lstrip("#").strip()
    if len(label) < 3:
        return None
    lowered = label.lower()
    if any(lowered.startswith(p) for p in _COMMENT_PRAGMAS):
        return None
    if not any(ch.isalnum() for ch in label):
        return None
    if any(pattern.match(label) for pattern in _CODE_LIKE):
        return None
    return label[:MAX_LABEL_CHARS]


def _blocks_in_span(
    comments: list[tuple[int, str]],
    lines: list[str],
    start_line: int,
    end_line: int,
    call_sites: list[CallSite],
) -> list[BlockRecord]:
    """Comment-delimited stanzas inside one function. A block starts at a
    comment line and runs to the line before the next comment (or the end of
    the function). This is the IoU lever."""
    runs: list[tuple[int, list[str]]] = []
    previous_lineno: int | None = None
    for lineno, text in comments:
        if not start_line < lineno <= end_line:
            continue
        label = _clean_comment(text)
        if label is None:
            previous_lineno = lineno
            continue
        if runs and previous_lineno == lineno - 1:
            runs[-1][1].append(label)
        else:
            runs.append((lineno, [label]))
        previous_lineno = lineno

    blocks: list[BlockRecord] = []
    for i, (lineno, parts) in enumerate(runs):
        block_end = runs[i + 1][0] - 1 if i + 1 < len(runs) else end_line
        while block_end > lineno and not lines[block_end - 1].strip():
            block_end -= 1
        if block_end <= lineno:
            continue  # a trailing comment with no body under it
        blocks.append(
            BlockRecord(
                label=" ".join(parts)[:MAX_LABEL_CHARS],
                start_line=lineno,
                end_line=block_end,
                call_names=list(
                    dict.fromkeys(
                        site.name for site in call_sites if lineno <= site.start_line <= block_end
                    )
                ),
            )
        )
    return blocks


def _module_scopes(
    comments: list[tuple[int, str]],
    lines: list[str],
    top_level: list[tuple[int, int]],
) -> list[SymbolRecord]:
    """Pseudo-symbols for the module-level code between top-level definitions.

    `chunk_file` only emits class and function nodes, so script bodies (argparse
    setup, dataframe pipelines under a `__main__` guard, module constants) have
    no symbol to anchor on. Each gap becomes its own record so merged block runs
    never jump over a class body.
    """
    occupied: list[tuple[int, int]] = sorted(top_level)
    scopes: list[SymbolRecord] = []
    cursor = 1
    boundaries = [*occupied, (len(lines) + 1, len(lines) + 1)]
    for start, end in boundaries:
        gap_end = start - 1
        if gap_end >= cursor and any(lines[i - 1].strip() for i in range(cursor, gap_end + 1)):
            blocks = _blocks_in_span(comments, lines, cursor - 1, gap_end, [])
            scopes.append(
                SymbolRecord(
                    name="<module>",
                    qualified_name=f"<module>:{cursor}-{gap_end}",
                    node_type="module_scope",
                    start_line=cursor,
                    end_line=gap_end,
                    blocks=blocks,
                )
            )
        cursor = max(cursor, end + 1)
    return scopes


def _summary(ast_index: _AstIndex, lines: list[str]) -> str:
    """Module docstring first line, else the leading comment header. License
    boilerplate is skipped — it is identical across every file in a repo and
    would cost the planner a line per file to say nothing."""
    if ast_index.module_docstring:
        for text in ast_index.module_docstring.strip().split("\n"):
            text = text.strip()
            if text and not _BOILERPLATE.search(text):
                return text[:MAX_SUMMARY_CHARS]
    header: list[str] = []
    for line in lines[:15]:
        stripped = line.strip()
        if not stripped:
            if header:
                break
            continue
        if not stripped.startswith("#"):
            break
        label = _clean_comment(stripped)
        if label and not _BOILERPLATE.search(label):
            header.append(label)
    return " ".join(header)[:MAX_SUMMARY_CHARS]


# --------------------------------------------------------------------------- #
# file classification
# --------------------------------------------------------------------------- #


def _path_tokens(filepath: str) -> list[str]:
    tokens: list[str] = []
    parts = Path(filepath).parts
    for part in parts[:-1]:
        tokens.extend(re.split(r"[_\-.]", part.lower()))
    tokens.extend(re.split(r"[_\-.]", Path(filepath).stem.lower()))
    return [t for t in tokens if t]


def _is_test(filepath: str) -> bool:
    name = Path(filepath).name.lower()
    if name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py":
        return True
    return any(part.lower() in {"test", "tests", "testing"} for part in Path(filepath).parts[:-1])


def _is_vendored(filepath: str, nested_projects: frozenset[str] = frozenset()) -> bool:
    parts = Path(filepath).parts[:-1]
    if any(part.lower() in VENDOR_DIRS for part in parts):
        return True
    # A nested project (its own setup.py / pyproject.toml) is a copy of somebody
    # else's package, not the repo's own code. LoRA ships all of transformers
    # under examples/NLU this way, which is 600 of its 815 Python files.
    return any("/".join(parts[: i + 1]) in nested_projects for i in range(len(parts)))


def _nested_projects(repo_path: Path) -> frozenset[str]:
    markers = ("setup.py", "pyproject.toml", "setup.cfg")
    roots: set[str] = set()
    for marker in markers:
        for path in repo_path.rglob(marker):
            relative = path.parent.relative_to(repo_path).as_posix()
            if relative != "." and not any(part in SKIP_DIRS for part in path.parts):
                roots.add(relative)
    return frozenset(roots)


def _classify(
    filepath: str,
    is_test: bool,
    is_vendored: bool,
    is_entrypoint: bool,
    classes: Iterable[ClassRecord],
) -> Role:
    if is_vendored:
        return Role.VENDORED
    if is_test:
        return Role.TEST
    parts = [p.lower() for p in Path(filepath).parts[:-1]]
    if is_entrypoint and (not parts or parts[0] in SCRIPT_DIRS):
        return Role.SCRIPT
    tokens = set(_path_tokens(filepath))
    for role, exact, stems in ROLE_RULES:
        if tokens & exact:
            return role
        if any(stem in token for token in tokens for stem in stems):
            return role
    # Fall back to what the file defines. Class names first, then method names,
    # which catch the framework base classes that carry no keyword in the path.
    for record in classes:
        name = record.name
        bases = " ".join(record.bases)
        if name.endswith(("Trainer", "Learner")):
            return Role.TRAINER
        if name.endswith(("Dataset", "DataModule", "DataLoader")):
            return Role.DATASET
        if name.endswith(("Loss", "Criterion")):
            return Role.LOSS
        if "Module" in bases or "nn." in bases:
            return Role.MODEL
    methods = {m.name for record in classes for m in record.methods}
    if methods & {"train", "fit", "train_step", "training_step", "compute_loss", "update"}:
        return Role.TRAINER
    if "forward" in methods:
        return Role.MODEL
    if methods & {"__getitem__", "__iter__"}:
        return Role.DATASET
    if is_entrypoint:
        return Role.SCRIPT
    return Role.UNKNOWN


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #


def _qualified_name(route: list[str]) -> str:
    return ".".join(part.split(":", 1)[-1] for part in route)


def _signature(metadata: dict[str, Any]) -> SignatureInfo | None:
    raw = metadata.get("signature")
    if not isinstance(raw, dict):
        return None
    return SignatureInfo(
        name=raw.get("name") or "",
        parameters=[
            Parameter(
                name=p.get("name") or "",
                type=p.get("type"),
                default=p.get("default"),
            )
            for p in raw.get("parameters") or []
            if isinstance(p, dict)
        ],
        return_type=raw.get("return_type"),
        decorators=[d for d in raw.get("decorators") or [] if isinstance(d, str)],
        modifiers=[m for m in raw.get("modifiers") or [] if isinstance(m, str)],
    )


def _call_sites(metadata: dict[str, Any], line_index: _LineIndex) -> list[CallSite]:
    sites: list[CallSite] = []
    for span in metadata.get("call_spans") or []:
        if not isinstance(span, dict) or "start" not in span:
            continue
        sites.append(
            CallSite(
                name=span.get("name") or "",
                start_line=line_index.line_of(span["start"]),
                end_line=line_index.line_of(span.get("end", span["start"])),
                byte_start=span["start"],
                byte_end=span.get("end", span["start"]),
            )
        )
    return sites


def _filter_names(names: Iterable[str], repo_names: set[str]) -> list[str]:
    """Noise filter: `dependencies` and `calls` run to ~100 mostly-builtin
    entries per class. Keep names defined in this repo plus an allowlist of
    semantically loaded library calls."""
    kept: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen or not name:
            continue
        if name in repo_names or name in LIB_ALLOWLIST:
            kept.append(name)
            seen.add(name)
    return kept


def _discover_files(repo_path: Path, extensions: tuple[str, ...]) -> list[Path]:
    found: list[Path] = []
    for root, dirs, filenames in os.walk(repo_path):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for filename in sorted(filenames):
            if filename.endswith(extensions):
                found.append(Path(root) / filename)
    return found


def commit_sha(repo_path: str | Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def build_repo_map(
    repo_path: str | Path,
    repo_url: str | None = None,
    language: str = "python",
    skip_vendored: bool = True,
) -> RepoMap:
    """Build the canonical index for one checkout.

    Line numbers in the result are only valid for the returned `commit_sha`.

    Vendored code is dropped by default: it never reaches the minimal view, so
    the resolver can never be pointed at it, and keeping it makes LoRA's map 34 MB
    instead of 1 MB.
    """
    if language != "python":
        raise NotImplementedError("v0 of the repo map is Python only; see REPO_MAP_DEFERRED.md")

    root = Path(repo_path).resolve()
    paths = _discover_files(root, (".py",))
    nested = _nested_projects(root)

    # Pass 1: chunk every file and collect the repo-wide name set the noise
    # filter needs. Sources are kept for block segmentation and summaries.
    parsed: list[tuple[str, str, list[Any]]] = []
    repo_names: set[str] = set()
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if skip_vendored and _is_vendored(relative, nested):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        try:
            chunks = chunk_file(path, language, identity_path=relative)
        except Exception:
            chunks = []
        chunks = [c for c in chunks if c.node_type in {"class_definition", "function_definition"}]
        parsed.append((relative, source, chunks))
        repo_names.add(Path(relative).stem)
        for chunk in chunks:
            if chunk.qualified_route:
                repo_names.add(chunk.qualified_route[-1].split(":", 1)[-1])

    # Pass 2: build the records.
    files: list[FileRecord] = []
    for relative, source, chunks in parsed:
        files.append(_build_file_record(relative, source, chunks, language, repo_names, nested))

    symbols: dict[str, list[SymbolTableEntry]] = {}
    for record in files:
        for entry in _symbol_entries(record):
            symbols.setdefault(entry.qualified_name, []).append(entry)

    return RepoMap(
        repo_url=repo_url or root.name,
        commit_sha=commit_sha(root),
        language=language,
        files=files,
        symbols=symbols,
    )


def _build_file_record(
    relative: str,
    source: str,
    chunks: list[Any],
    language: str,
    repo_names: set[str],
    nested_projects: frozenset[str] = frozenset(),
) -> FileRecord:
    lines = source.splitlines()
    ast_index = _AstIndex(source, relative)
    line_index = _LineIndex(source)
    comments = _own_line_comments(source)

    classes: dict[tuple[str, ...], ClassRecord] = {}
    functions: list[SymbolRecord] = []

    for chunk in sorted(chunks, key=lambda c: (c.start_line, len(c.qualified_route))):
        route = tuple(chunk.qualified_route)
        if not route:
            continue
        qualified = _qualified_name(list(route))
        name = route[-1].split(":", 1)[-1]

        if chunk.node_type == "class_definition":
            classes[route] = ClassRecord(
                name=name,
                qualified_name=qualified,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                docstring=ast_index.docstrings.get(qualified),
                decorators=ast_index.decorators.get(qualified, []),
                bases=ast_index.bases.get(qualified, []),
            )
            continue

        call_sites = _call_sites(chunk.metadata, line_index)
        symbol = SymbolRecord(
            name=name,
            qualified_name=qualified,
            node_type=chunk.node_type,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            docstring=ast_index.docstrings.get(qualified),
            signature=_signature(chunk.metadata),
            calls=_filter_names(chunk.metadata.get("calls") or [], repo_names),
            call_sites=call_sites,
            dependencies=_filter_names(chunk.metadata.get("dependencies") or [], repo_names),
            blocks=_blocks_in_span(comments, lines, chunk.start_line, chunk.end_line, call_sites),
            complexity=chunk.metadata.get("complexity") or {},
        )
        parent = route[:-1]
        if parent in classes:
            classes[parent].methods.append(symbol)
        elif len(route) == 1:
            functions.append(symbol)
        else:
            # Nested function: reachable through the symbol table, but kept out
            # of the minimal view unless its parent is a class.
            functions.append(symbol)

    class_records = sorted(classes.values(), key=lambda c: c.start_line)
    for record in class_records:
        first_method = min((m.start_line for m in record.methods), default=None)
        header_end = (first_method - 1) if first_method else record.end_line
        while header_end > record.start_line and not lines[header_end - 1].strip():
            header_end -= 1
        record.header_end_line = header_end
    top_level = [
        (chunk.start_line, chunk.end_line) for chunk in chunks if len(chunk.qualified_route) == 1
    ]
    is_test = _is_test(relative)
    is_vendored = _is_vendored(relative, nested_projects)
    is_entrypoint = bool(re.search(r"^\s*if\s+__name__\s*==", source, re.MULTILINE))

    return FileRecord(
        filepath=relative,
        language=language,
        role=_classify(relative, is_test, is_vendored, is_entrypoint, class_records),
        loc=len(lines),
        summary=_summary(ast_index, lines),
        key_imports=list(dict.fromkeys(ast_index.imports)),
        is_test=is_test,
        is_vendored=is_vendored,
        is_entrypoint=is_entrypoint,
        classes=class_records,
        functions=functions,
        module_scopes=_module_scopes(comments, lines, top_level),
    )


def _symbol_entries(record: FileRecord) -> list[SymbolTableEntry]:
    entries: list[SymbolTableEntry] = []
    for cls in record.classes:
        entries.append(
            SymbolTableEntry(
                qualified_name=cls.qualified_name,
                filepath=record.filepath,
                node_type="class_definition",
                start_line=cls.start_line,
                end_line=cls.end_line,
            )
        )
    for symbol in record.symbols():
        entries.append(
            SymbolTableEntry(
                qualified_name=symbol.qualified_name,
                filepath=record.filepath,
                node_type=symbol.node_type,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
            )
        )
    return entries


# --------------------------------------------------------------------------- #
# minimal view (planner)
# --------------------------------------------------------------------------- #

MINIMAL_LEGEND = (
    "One line per file: path [role] <loc>L - summary. "
    "'C' lines are classes with their methods, 'F' lines module-level functions. "
    "Numbers after a name are its inclusive line range at this commit."
)


def render_minimal_view(
    repo_map: RepoMap,
    include_tests: bool = False,
    include_vendored: bool = False,
    max_imports: int = 6,
) -> str:
    """Compact text serialization of the minimal view, for the planner prompt.

    Files are grouped by directory so paths are not repeated per file.
    """
    out: list[str] = [
        f"repo: {repo_map.repo_url} @ {repo_map.commit_sha[:7]} ({repo_map.language})",
        MINIMAL_LEGEND,
        "",
    ]

    selected = [
        f
        for f in repo_map.files
        if f.loc and (include_tests or not f.is_test) and (include_vendored or not f.is_vendored)
    ]

    grouped: dict[str, list[FileRecord]] = {}
    for record in selected:
        grouped.setdefault(str(Path(record.filepath).parent), []).append(record)

    for directory in sorted(grouped):
        out.append(f"{'.' if directory == '.' else directory}/")
        for record in sorted(grouped[directory], key=lambda f: f.filepath):
            header = f"  {Path(record.filepath).name} [{record.role.value}] {record.loc}L"
            if record.summary:
                header += f" - {record.summary}"
            if record.is_entrypoint and record.role != Role.SCRIPT:
                header += " *main"
            out.append(header)
            if record.key_imports:
                out.append(f"    imports: {', '.join(record.key_imports[:max_imports])}")
            for cls in record.classes:
                line = f"    C {cls.name} {cls.start_line}-{cls.end_line}"
                if cls.bases:
                    line += f"({', '.join(cls.bases)})"
                if cls.methods:
                    line += ": " + ", ".join(
                        f"{m.name} {m.start_line}-{m.end_line}" for m in cls.methods
                    )
                out.append(line)
            top_level = [f for f in record.functions if "." not in f.qualified_name]
            if top_level:
                out.append(
                    "    F "
                    + ", ".join(f"{f.name} {f.start_line}-{f.end_line}" for f in top_level)
                )
    return "\n".join(out) + "\n"


def minimal_dict(
    repo_map: RepoMap,
    include_tests: bool = False,
    include_vendored: bool = False,
) -> list[dict[str, Any]]:
    """JSON form of the minimal view. Kept alongside `render_minimal_view` so
    the token cost of the two encodings can be compared directly."""
    out: list[dict[str, Any]] = []
    for record in repo_map.files:
        if not record.loc:
            continue
        if not include_tests and record.is_test:
            continue
        if not include_vendored and record.is_vendored:
            continue
        out.append(
            {
                "filepath": record.filepath,
                "role": record.role.value,
                "loc": record.loc,
                "summary": record.summary,
                "key_imports": record.key_imports,
                "classes": [
                    {
                        "name": cls.name,
                        "qualified_name": cls.qualified_name,
                        "start_line": cls.start_line,
                        "end_line": cls.end_line,
                        "methods": [
                            {
                                "name": m.name,
                                "qualified_name": m.qualified_name,
                                "start_line": m.start_line,
                                "end_line": m.end_line,
                            }
                            for m in cls.methods
                        ],
                    }
                    for cls in record.classes
                ],
                "functions": [
                    {
                        "name": f.name,
                        "qualified_name": f.qualified_name,
                        "start_line": f.start_line,
                        "end_line": f.end_line,
                    }
                    for f in record.functions
                    if "." not in f.qualified_name
                ],
            }
        )
    return out


def estimate_tokens(text: str) -> int:
    """Rough character-based estimate; good enough for budget comparisons."""
    return len(text) // 4


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #

DEFAULT_CACHE_DIR = Path(__file__).parent / "cache"


def save_repo_map(repo_map: RepoMap, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(repo_map.model_dump_json(indent=1))
    return path


def load_repo_map(path: str | Path) -> RepoMap:
    return RepoMap.model_validate(json.loads(Path(path).read_text()))


def cache_path(repo_path: str | Path, cache_dir: str | Path = DEFAULT_CACHE_DIR) -> Path:
    """Cached maps are keyed by commit sha, since line numbers are only valid
    for one checkout."""
    root = Path(repo_path).resolve()
    return Path(cache_dir) / f"{root.name}@{commit_sha(root)[:12]}.json"


def load_or_build(
    repo_path: str | Path,
    repo_url: str | None = None,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    rebuild: bool = False,
) -> RepoMap:
    path = cache_path(repo_path, cache_dir)
    if path.exists() and not rebuild:
        return load_repo_map(path)
    repo_map = build_repo_map(repo_path, repo_url=repo_url)
    save_repo_map(repo_map, path)
    return repo_map
