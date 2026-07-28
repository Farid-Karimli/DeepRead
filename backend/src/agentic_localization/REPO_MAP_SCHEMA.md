Repo Map Schema (POC)

Schema for the two-agent localization pipeline: a planner picks a file and anchor
symbol, a resolver pins the exact line span. Built on `treesitter-chunker` 4.0.0
output (`TreeSitterCodeChunk`).

Scope of this POC: Python only, single repo checkout, no cross-file resolution.
See `REPO_MAP_DEFERRED.md` for what is intentionally left out.

## Two views, one index

One canonical index is built per repo. It is exposed two ways:

| View | Consumer | Delivery | Contains |
| --- | --- | --- | --- |
| Minimal | Planner (Agent 1) | Serialized blob in prompt | File tree, roles, symbol names + line ranges, one-line summaries |
| Full | Resolver (Agent 2) | Query by file/symbol | Everything below, scoped to one file or symbol |

The full view is never serialized whole. A large repo will not fit in context,
and the resolver only ever needs one file.

## Verified source constraints

These were checked against `src/temp/Atari-PB` with `.venv/bin/python`:

- `chunk.metadata['call_spans']` offsets are **absolute file byte offsets**, not
  chunk-relative. Confirmed: `byte_to_line(chunk.byte_start) == chunk.start_line`.
- `BaseMetadataExtractor` is abstract. The concrete class comes from
  `MetadataExtractorFactory.create_extractor("python")`, and its methods take
  `(node: tree_sitter.Node, source: bytes)` — not a chunk. Not required for this POC.
- `chunk_file` / `chunk_directory` emit `class_definition`, `function_definition`
  and `lambda` nodes only. No statement-level nodes, so module-level code has no
  chunk of its own — see `module_scopes` below.
- `chunk.file_path` is absolute unless `identity_path` is passed. All paths in this
  schema are repo-relative.
- The chunker is installed in `backend/.venv`, not the anaconda Python on PATH.
- `chunk_directory` takes no `identity_path` and shells out to a
  `ProcessPoolExecutor`. The builder walks the tree itself and calls `chunk_file`
  per file instead: repo-relative paths, deterministic order, ~0.3s for 72 files.

## Repo-level index

| Field | Type | Source | Notes |
| --- | --- | --- | --- |
| `repo_url` | str | caller | Normalized clone URL |
| `commit_sha` | str | git | Pins the map to a checkout; line numbers are only valid for this SHA |
| `language` | str | caller | `"python"` for POC |
| `files` | list[FileRecord] | derived | Ordered by path |
| `symbols` | dict[str, SymbolTableEntry] | derived | Keyed by qualified name |
| `built_at` | datetime | derived | |

## SymbolTableEntry

Inversion of `qualified_route`. Turns the planner's anchor symbol into a lookup
instead of a search.

| Field | Type | Source | Notes |
| --- | --- | --- | --- |
| `qualified_name` | str | derived from `chunk.qualified_route` | e.g. `CURLTrainer.compute_loss` |
| `filepath` | str | `chunk.file_path` | Repo-relative |
| `node_type` | str | `chunk.node_type` | `class_definition` \| `function_definition` |
| `start_line` | int | `chunk.start_line` | 1-based, inclusive |
| `end_line` | int | `chunk.end_line` | 1-based, inclusive |

Collisions (same qualified name in different files) are stored as a list.

## FileRecord

Fields marked **M** appear in the minimal view; the rest are full view only.

| Field | M | Type | Source | Notes |
| --- | --- | --- | --- | --- |
| `filepath` | ✓ | str | `chunk.file_path` via `identity_path` | Repo-relative |
| `language` | ✓ | str | `chunk.language` | |
| `role` | ✓ | enum | derived | See role tags below |
| `loc` | ✓ | int | derived | Total lines |
| `summary` | ✓ | str | module docstring or header comment | Truncated to ~120 chars |
| `key_imports` | ✓ | list[str] | derived | Non-stdlib only, deduped |
| `is_test` | ✓ | bool | derived | Path/name heuristic |
| `is_vendored` | ✓ | bool | derived | Path heuristic (`third_party/`, `external/`, `vendor/`) plus any non-root directory with its own `setup.py` / `pyproject.toml` |
| `is_entrypoint` | ✓ | bool | derived | Has `__main__` guard |
| `classes` | ✓ | list[ClassRecord] | chunks | |
| `functions` | ✓ | list[SymbolRecord] | chunks | Module-level only |
| `module_scopes` | | list[SymbolRecord] | derived | One per gap between top-level definitions; `node_type` is `module_scope` |

Minimal view drops `content` entirely and lists only symbol names + line ranges,
and drops test, vendored and empty files.

`module_scopes` exists because the chunker emits no statement-level nodes: script
bodies under a `__main__` guard and module-level constants would otherwise have no
anchor at all. That was 16 of the 116 annotated ground-truth ranges. One record
per gap between top-level definitions, so merged block runs never jump over a
class body. Full view only — the planner picks the file, not the gap.

## ClassRecord

| Field | M | Type | Source | Notes |
| --- | --- | --- | --- | --- |
| `name` | ✓ | str | `chunk.metadata['signature']['name']` | |
| `qualified_name` | ✓ | str | `chunk.qualified_route` | |
| `start_line` / `end_line` | ✓ | int | chunk | |
| `header_end_line` | | int | derived | Line before the first method, blanks trimmed |
| `docstring` | | str \| None | derived via `ast` | Class chunks carry no `signature` |
| `decorators` | | list[str] | derived via `ast` | |
| `bases` | ✓ | list[str] | derived via `ast` | |
| `methods` | ✓ | list[SymbolRecord] | chunks | Minimal view: names + line ranges only |

`start_line .. header_end_line` is the declaration region: bases, class attributes
and docstring. It is offered to the resolver as its own candidate, because claims
that name a component rather than an operation ("CURL is implemented in ...") point
there, and the whole-class span scores badly against them.

## SymbolRecord (function or method)

| Field | M | Type | Source | Notes |
| --- | --- | --- | --- | --- |
| `name` | ✓ | str | `metadata['signature']['name']` | |
| `qualified_name` | ✓ | str | `chunk.qualified_route` | |
| `node_type` | ✓ | str | `chunk.node_type` | |
| `start_line` / `end_line` | ✓ | int | chunk | |
| `docstring` | | str \| None | derived | Often absent in research repos |
| `signature` | | SignatureInfo | `metadata['signature']` | Params, return type, decorators |
| `calls` | | list[str] | `metadata['calls']` | Filtered (see noise filter) |
| `call_sites` | | list[CallSite] | derived from `metadata['call_spans']` | Byte → line converted |
| `dependencies` | | list[str] | `metadata['dependencies']` | Filtered |
| `blocks` | | list[BlockRecord] | derived | The IoU lever |
| `complexity` | | dict | `metadata['complexity']` | Ranking prior |

## CallSite

`metadata['call_spans']` with offsets converted to lines via a newline-offset
table. Used to select which block, not to define the returned span.

| Field | Type | Source | Notes |
| --- | --- | --- | --- |
| `name` | str | `call_spans[].name` | |
| `start_line` | int | derived from `call_spans[].start` | |
| `end_line` | int | derived from `call_spans[].end` | |
| `byte_start` / `byte_end` | int | `call_spans[]` | Kept as tiebreaker for multiple calls on one line |

## BlockRecord

Comment-delimited stanzas inside a function. A block starts at a comment line and
runs to the line before the next comment (or the end of the function).

| Field | Type | Source | Notes |
| --- | --- | --- | --- |
| `label` | str | comment text | Stripped of `#`; the lexical match hook |
| `start_line` | int | derived | Inclusive, starts at the comment line |
| `end_line` | int | derived | Inclusive |
| `call_names` | list[str] | join with `call_sites` | Calls occurring inside this block |

Candidate spans offered to the resolver are: each block, plus merged runs of up to
3 adjacent blocks, plus the enclosing span (function, class header or module scope)
as fallback.

Rationale, from `main.py oracle` over all 116 `.py` ground-truth ranges in
`evals/annotations/manual_v1.json`: best achievable IoU is 0.396 for the enclosing
span, 0.270 for a single block, 0.207 for merged blocks, and 0.573 taking the best
of all tiers. Every range has an anchor (116/116) and every range's file survives
into the minimal view. These are oracle ceilings, so realized gains will be lower.

Merged runs score below single blocks on every paper, so merging is worth keeping
as an option for the resolver rather than a default. Per-paper numbers are in
`README.md`.

## Role tags

Derived from path plus `key_imports`. Drives content-type routing (paper says
"loss" → prefer `trainer` / `loss`).

`trainer` | `model` | `dataset` | `loss` | `config` | `script` | `test` | `util` | `vendored` | `unknown`

## Noise filter

`metadata['dependencies']` and `metadata['exports']` are position-less name lists
that run to ~100 entries per class, mostly builtins and locals (`len`, `range`,
`zip`, `sum`, `float`, `self`, `_`, `t`, `to`, `shape`). Keep only:

- names resolving to something else in this repo, and
- an allowlist of semantically loaded library calls (`CrossEntropyLoss`,
  `all_gather`, `no_grad`, and similar).

`exports` is excluded from the POC schema entirely — it carries no line numbers,
so it cannot support span selection. See `REPO_MAP_DEFERRED.md`.

## Illustrative shape

Minimal view, one file:

```json
{
  "filepath": "src/trainers/curl.py",
  "role": "trainer",
  "loc": 130,
  "key_imports": ["torch", "einops", "src.common.schedulers"],
  "classes": [
    {
      "name": "CURLTrainer",
      "qualified_name": "CURLTrainer",
      "start_line": 13,
      "end_line": 130,
      "methods": [
        { "name": "__init__", "qualified_name": "CURLTrainer.__init__", "start_line": 15, "end_line": 51 },
        { "name": "compute_loss", "qualified_name": "CURLTrainer.compute_loss", "start_line": 53, "end_line": 103 },
        { "name": "update", "qualified_name": "CURLTrainer.update", "start_line": 105, "end_line": 130 }
      ]
    }
  ],
  "functions": []
}
```

Full view, one symbol:

```json
{
  "qualified_name": "CURLTrainer.compute_loss",
  "start_line": 53,
  "end_line": 103,
  "calls": ["aug_func", "rearrange", "CrossEntropyLoss", "all_gather"],
  "call_sites": [
    { "name": "aug_func", "start_line": 62, "end_line": 62 },
    { "name": "CrossEntropyLoss", "start_line": 95, "end_line": 95 },
    { "name": "criterion", "start_line": 96, "end_line": 96 }
  ],
  "blocks": [
    { "label": "augmentation", "start_line": 59, "end_line": 65, "call_names": ["aug_func", "rearrange"] },
    { "label": "similarity", "start_line": 89, "end_line": 91, "call_names": ["t"] },
    { "label": "loss & acc", "start_line": 93, "end_line": 97, "call_names": ["CrossEntropyLoss", "criterion"] }
  ],
  "complexity": { "cyclomatic": 6, "lines_of_code": 62, "nesting_depth": 2 }
}
```

## Decisions settled in v0

- Minimal-view token budget: a single blob, text-encoded rather than JSON (~3.5x
  cheaper). The five annotated repos land at 0.7k–7.8k estimated tokens. The stress
  case was LoRA, not V-JEPA 2 — it vendors all of `transformers` under
  `examples/NLU`, which the nested-project rule for `is_vendored` removes. No lazy
  per-directory expansion needed at this corpus size.
- Blocks are precomputed for every function at build time. Segmentation is cheap
  (one `tokenize` pass per file) and the whole map builds in ~2s for 72 files.
- The map is cached per `commit_sha` (`cache/<repo>@<sha>.json`), since line
  numbers are only valid for one checkout.

## Still open

- Whether the planner should see block labels for the file it picked, or only
  reach them through the resolver's per-symbol query.
- How to score a candidate span against paper content: lexical overlap on block
  labels, embedding similarity, or a model call per candidate.
