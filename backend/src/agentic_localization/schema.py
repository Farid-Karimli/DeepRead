"""
Repo map data model (v0), as specified in REPO_MAP_SCHEMA.md.

One canonical index per repo checkout, exposed two ways:

- minimal view: serialized into the planner's prompt (file tree, roles, symbol
  names + line ranges, one-line summaries)
- full view: queried by file or symbol, never serialized whole

Line numbers are 1-based and inclusive, and are only valid for `commit_sha`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterator

from pydantic import BaseModel, Field, PrivateAttr


class Role(str, Enum):
    TRAINER = "trainer"
    MODEL = "model"
    DATASET = "dataset"
    LOSS = "loss"
    CONFIG = "config"
    SCRIPT = "script"
    TEST = "test"
    UTIL = "util"
    VENDORED = "vendored"
    UNKNOWN = "unknown"


class Parameter(BaseModel):
    name: str
    type: str | None = None
    default: str | None = None


class SignatureInfo(BaseModel):
    name: str = ""
    parameters: list[Parameter] = Field(default_factory=list)
    return_type: str | None = None
    decorators: list[str] = Field(default_factory=list)
    modifiers: list[str] = Field(default_factory=list)

    def render(self) -> str:
        params = ", ".join(
            p.name + (f": {p.type}" if p.type else "") + (f"={p.default}" if p.default else "")
            for p in self.parameters
        )
        arrow = f" -> {self.return_type}" if self.return_type else ""
        return f"{self.name}({params}){arrow}"


class CallSite(BaseModel):
    """A call from `metadata['call_spans']`, byte offsets converted to lines.

    Byte offsets are absolute file offsets and are kept as a tiebreaker when
    several calls land on the same line.
    """

    name: str
    start_line: int
    end_line: int
    byte_start: int
    byte_end: int


class BlockRecord(BaseModel):
    """A comment-delimited stanza inside a function: starts at a comment line,
    runs to the line before the next comment or the end of the function."""

    label: str
    start_line: int
    end_line: int
    call_names: list[str] = Field(default_factory=list)


class CandidateSpan(BaseModel):
    """A span offered to the resolver. `kind` is `block`, `merged` or `function`."""

    kind: str
    label: str
    start_line: int
    end_line: int
    call_names: list[str] = Field(default_factory=list)


class SymbolRecord(BaseModel):
    """A function or method. Fields below `end_line` are full view only."""

    name: str
    qualified_name: str
    node_type: str
    start_line: int
    end_line: int
    docstring: str | None = None
    signature: SignatureInfo | None = None
    calls: list[str] = Field(default_factory=list)
    call_sites: list[CallSite] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    blocks: list[BlockRecord] = Field(default_factory=list)
    complexity: dict[str, Any] = Field(default_factory=dict)

    def candidate_spans(self, max_merge: int = 3) -> list[CandidateSpan]:
        """Each block, plus merged runs of up to `max_merge` adjacent blocks,
        plus the enclosing function as fallback."""
        spans: list[CandidateSpan] = []
        for block in self.blocks:
            spans.append(
                CandidateSpan(
                    kind="block",
                    label=block.label,
                    start_line=block.start_line,
                    end_line=block.end_line,
                    call_names=list(block.call_names),
                )
            )
        for width in range(2, max_merge + 1):
            for i in range(len(self.blocks) - width + 1):
                run = self.blocks[i : i + width]
                spans.append(
                    CandidateSpan(
                        kind="merged",
                        label=" / ".join(b.label for b in run),
                        start_line=run[0].start_line,
                        end_line=run[-1].end_line,
                        call_names=[n for b in run for n in b.call_names],
                    )
                )
        spans.append(
            CandidateSpan(
                kind="function",
                label=self.qualified_name,
                start_line=self.start_line,
                end_line=self.end_line,
                call_names=list(dict.fromkeys(self.calls)),
            )
        )
        return spans


class ClassRecord(BaseModel):
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    # End of the declaration region: bases, class attributes and docstring, up to
    # the first method. Annotators point here when a claim names a component
    # rather than an operation ("CURL is implemented in ...").
    header_end_line: int = 0
    docstring: str | None = None
    decorators: list[str] = Field(default_factory=list)
    bases: list[str] = Field(default_factory=list)
    methods: list[SymbolRecord] = Field(default_factory=list)

    def header(self) -> SymbolRecord:
        """The declaration region, as a resolver candidate."""
        return SymbolRecord(
            name=self.name,
            qualified_name=self.qualified_name,
            node_type="class_header",
            start_line=self.start_line,
            end_line=self.header_end_line or self.end_line,
            docstring=self.docstring,
        )

    def as_symbol(self) -> SymbolRecord:
        """The whole class, which is what a class anchor resolves to. The header
        alone can be one line, too narrow to hand back as a span on its own."""
        return SymbolRecord(
            name=self.name,
            qualified_name=self.qualified_name,
            node_type="class_definition",
            start_line=self.start_line,
            end_line=self.end_line,
            docstring=self.docstring,
        )


class FileRecord(BaseModel):
    filepath: str
    language: str
    role: Role = Role.UNKNOWN
    loc: int = 0
    summary: str = ""
    key_imports: list[str] = Field(default_factory=list)
    is_test: bool = False
    is_vendored: bool = False
    is_entrypoint: bool = False
    classes: list[ClassRecord] = Field(default_factory=list)
    functions: list[SymbolRecord] = Field(default_factory=list)
    module_scopes: list[SymbolRecord] = Field(default_factory=list)

    def symbols(self) -> Iterator[SymbolRecord]:
        """Named symbols only: what the symbol table and the planner see."""
        for cls in self.classes:
            yield from cls.methods
        yield from self.functions

    def candidates(self) -> Iterator[SymbolRecord]:
        """Everything the resolver can be pointed at: named symbols, class
        declaration regions, and the run-at-import stanzas that carry no symbol
        name (14% of the annotated ground truth)."""
        yield from self.symbols()
        for cls in self.classes:
            yield cls.header()
        yield from self.module_scopes


class SymbolTableEntry(BaseModel):
    """Inversion of `qualified_route`: turns the planner's anchor symbol into a
    lookup instead of a search."""

    qualified_name: str
    filepath: str
    node_type: str
    start_line: int
    end_line: int


class RepoMap(BaseModel):
    repo_url: str
    commit_sha: str
    language: str
    files: list[FileRecord] = Field(default_factory=list)
    symbols: dict[str, list[SymbolTableEntry]] = Field(default_factory=dict)
    built_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    _file_index: dict[str, FileRecord] = PrivateAttr(default_factory=dict)

    def file(self, filepath: str) -> FileRecord | None:
        """Full view for one file."""
        if not self._file_index:
            self._file_index = {f.filepath: f for f in self.files}
        return self._file_index.get(filepath.lstrip("./"))

    def lookup(self, qualified_name: str) -> list[SymbolTableEntry]:
        """Symbol table lookup. Returns every location the name resolves to."""
        entries = self.symbols.get(qualified_name)
        if entries:
            return entries
        # Planner anchors are often bare method names; fall back to a suffix match.
        return [
            entry
            for name, hits in self.symbols.items()
            if name.split(".")[-1] == qualified_name
            for entry in hits
        ]

    def symbol(self, qualified_name: str, filepath: str | None = None) -> SymbolRecord | None:
        """Full view for one symbol. Methods and functions come back as
        themselves; a class name comes back as the whole class."""
        for entry in self.lookup(qualified_name):
            if filepath and entry.filepath != filepath.lstrip("./"):
                continue
            record = self.file(entry.filepath)
            if record is None:
                continue
            for candidate in record.symbols():
                if candidate.qualified_name == entry.qualified_name:
                    return candidate
            for cls in record.classes:
                if cls.qualified_name == entry.qualified_name:
                    return cls.as_symbol()
        return None

    def stats(self) -> dict[str, int]:
        classes = sum(len(f.classes) for f in self.files)
        symbols = sum(1 for f in self.files for _ in f.symbols())
        blocks = sum(len(s.blocks) for f in self.files for s in f.candidates())
        return {
            "files": len(self.files),
            "classes": classes,
            "symbols": symbols,
            "module_scopes": sum(len(f.module_scopes) for f in self.files),
            "symbol_table_names": len(self.symbols),
            "blocks": blocks,
        }
