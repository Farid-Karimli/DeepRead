Agentic Localization

Two-agent localization: a planner picks a file and an anchor symbol from a
serialized repo map, and a resolver pins the exact line span using the full
record for that one symbol. Targets `src/evals` method accuracy and code IoU
while cutting the tool-call wandering the single-agent baseline does.

`REPO_MAP_SCHEMA.md` is the spec, `REPO_MAP_DEFERRED.md` is what is out of scope.

## What is here

| File | Role |
| --- | --- |
| `schema.py` | The data model: `RepoMap`, `FileRecord`, `ClassRecord`, `SymbolRecord`, `BlockRecord`, `CandidateSpan` |
| `repo_map.py` | v0 builder, minimal-view serialization, candidate spans, per-sha cache |
| `planner.py` | Agent 1: picks file + anchor symbol from the minimal view, no tools |
| `main.py` | CLI: `build`, `show`, `oracle` |
| `utils.py` | Repo cloning and file helpers |

Agent 2 (resolver) is not built yet, so a planner prediction's span is the whole
anchor symbol.

## Pipeline

Built on [treesitter-chunker](https://github.com/Consiliency/treesitter-chunker)
4.0.0, one `chunk_file` call per `.py` file with `identity_path` set so every
path in the map is repo-relative.

1. Walk the checkout, chunk each file, and collect the repo-wide symbol name set
   that the noise filter needs (`metadata['calls']` and `['dependencies']` are
   ~100 mostly-builtin names per class; only names defined in this repo plus an
   allowlist of loaded library calls survive).
2. Per file, derive what the chunker does not expose: docstrings, decorators and
   base classes from `ast`; `key_imports` (non-stdlib, relative imports resolved);
   a role tag from path tokens with class- and method-name fallbacks; comment
   stanzas (`BlockRecord`) from `tokenize`, so a `#` inside a string is not
   mistaken for a comment; `call_spans` byte offsets converted to lines.
3. Invert `qualified_route` into a symbol table so an anchor name is a lookup
   rather than a search. Collisions are kept as a list.

Two views over the one index:

- Minimal (planner): `render_minimal_view()` — a directory-grouped text blob of
  paths, roles, LOC, summaries, imports and symbol line ranges. Tests, vendored
  code and empty files are excluded.
- Full (resolver): `repo_map.file(path)` and `repo_map.symbol(name)`, plus
  `symbol.candidate_spans()` — every block, merged runs of up to 3 adjacent
  blocks, and the enclosing span as fallback.

## Usage

Needs `backend/.venv` (the chunker is not in the anaconda Python on PATH).

```bash
cd backend
python -m src.agentic_localization.main build \
    --path src/temp/Atari-PB --repo-url https://github.com/dojeon-ai/Atari-PB

python -m src.agentic_localization.main show --path src/temp/Atari-PB --minimal
python -m src.agentic_localization.main show --path src/temp/Atari-PB \
    --symbol CURLTrainer.compute_loss --spans

python -m src.agentic_localization.main oracle          # all papers
python -m src.agentic_localization.main oracle --paper 1

python -m src.agentic_localization.planner              # planner smoke test
python -m src.evals.run --planner --paper 1 --output src/evals/v0.7/planner-sonnet-predictions.json
python -m src.evals.evaluate --predictions src/evals/v0.7/planner-sonnet-predictions.json \
    --output src/evals/v0.7/planner-sonnet-metrics.json
```

```python
from src.agentic_localization.repo_map import load_or_build, render_minimal_view

repo_map = load_or_build("src/temp/Atari-PB")          # cached per commit sha
blob = render_minimal_view(repo_map)                   # planner prompt
symbol = repo_map.symbol("CURLTrainer.compute_loss")   # resolver
spans = symbol.candidate_spans()
```

The directory is named `agentic_localization`, not `agentic-localization`, so it
can be imported as a package (`src.evals.run` imports the planner from it).

Maps are cached in `cache/<repo>@<sha>.json`, since line numbers are only valid
for one checkout. Both `cache/` and `src/temp/` are gitignored.

## Planner (agent 1)

`planner.py` mirrors `Agent.map_content_to_code`, with one deliberate difference:
it gets **no tools**. The minimal view goes into the prompt, so picking a file and
an anchor symbol is one call instead of a Search / ReadFile crawl. Line numbers
come from the symbol table, not from the model, so the span cannot be
hallucinated — an anchor that does not resolve is counted, not silently accepted.
It exposes the same `map_content_to_code` signature as `Agent`, so
`src.evals.run --planner` and `src.evals.evaluate` work unchanged.

Paper 1 (Atari-PB, 12 annotations), sonnet, against the single-agent baselines on
the same 12 annotations:

| run | filepath top-1 | hit@5 | method acc | class acc | IoU (correct filepath) | tool calls | s/annotation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v0.1 baseline | 66.7% | 100% | 33.3% (n=6) | 100% (n=6) | 0.241 | — | — |
| v0.5 baseline | 58.3% | 100% | 50.0% (n=6) | 100% (n=6) | 0.201 | — | 97.6 |
| v0.6 baseline (haiku) | 66.7% | 91.7% | 57.1% (n=7) | 100% (n=6) | 0.194 | — | — |
| **v0.7 planner** | **91.7%** | **100%** | **70.0% (n=10)** | 100% (n=9) | 0.186 | **0** | **12.5** |

Filepath accuracy and method accuracy both move up, and because more filepaths are
correct, more annotations become *eligible* for the method check (n=10 vs n=6) —
the rate improves on a harder denominator. IoU is flat by construction: without a
resolver, the returned span is the entire anchor symbol. That is the 0.396 oracle
column below, and closing the gap to 0.573 is agent 2's job.

Zero unresolved filepaths and zero unresolved anchors across the 12 annotations:
the planner did not invent a path or a symbol name once.

All three remaining method-accuracy misses have the same shape: the planner
anchored on the class (`SiamMAETrainer`, `DTTrainer`, a dataset util class) when the
content described an operation inside one of its methods, so the span is the whole
class and lands in the right file but the wrong method. Both a prompt nudge and the
resolver attack this directly, which makes it the obvious next lever.

Token load per annotation is 18.8k input / 494 output. Two findings behind that
number, both measured:

- `allowed_tools=[]` withholds tool *permission* but the SDK still ships every
  Claude Code tool schema, worth ~15k input tokens per call. `tools=[]` drops
  them and takes the call from 33.7k to 18.5k.
- Even with `tools=[]`, an explicit `system_prompt` and `setting_sources=[]`, the
  Claude Code CLI injects ~11.3k tokens of its own scaffolding per call (measured
  with a stub prompt). So of 18.8k input tokens, only ~7.5k is the repo map and
  the instructions. Calling the `anthropic` SDK directly would remove that floor;
  it is left in place for now so the planner and the baseline run through the same
  harness.

The baseline's token usage was never recorded, so there is no like-for-like token
comparison yet. `Agent.map_content_to_code` now records `usage` and
`total_cost_usd` in its process metrics, so the next baseline run will produce one.

## Measured on the annotation ground truth

`main.py oracle` scores the candidate spans against `evals/annotations/manual_v1.json`
with no model in the loop: for each `.py` ground-truth range it takes the best
overlapping anchor and reports the best IoU reachable from each candidate tier.
This is the ceiling the resolver is selecting against, not a prediction.

| paper | n | in_min | in_fn | anchor | span | block | merged | best |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Atari-PB | 29 | 29 | 29 | 29 | 0.382 | 0.360 | 0.325 | 0.662 |
| honest_llama | 15 | 15 | 15 | 15 | 0.473 | 0.216 | 0.169 | 0.494 |
| LoRA | 18 | 18 | 18 | 18 | 0.344 | 0.345 | 0.180 | 0.532 |
| MATT | 27 | 27 | 19 | 27 | 0.436 | 0.134 | 0.144 | 0.532 |
| vjepa2 | 27 | 27 | 26 | 27 | 0.365 | 0.290 | 0.182 | 0.588 |
| all | 116 | 116 | 107 | 116 | 0.396 | 0.270 | 0.207 | **0.573** |

`in_min` is ground-truth ranges whose file survives into the minimal view (a
file the planner never sees is an accuracy ceiling too), `in_fn` is ranges with a
named anchor, `anchor` is ranges with any anchor. IoU columns average over all
`n`, so an unanchored range counts as 0.

Two additions beyond the spec were needed to reach 116/116 anchored, both worth
their cost:

- Class declaration regions (`ClassRecord.header()`): class start to the line
  before the first method. Claims that name a component rather than an operation
  point here, and the whole-class span scores badly against them.
- Module scopes (`FileRecord.module_scopes`): the chunker emits class and
  function nodes only, so script bodies under a `__main__` guard and module
  constants had no anchor at all. That was 16 of 116 ranges, 9 of them in MATT.
  One pseudo-symbol per gap between top-level definitions, so merged block runs
  never jump over a class body.

Minimal-view token budget (rough, chars/4), which settles that open decision —
one blob fits, and the text encoding is ~3.5x cheaper than JSON:

| repo | `.py` in checkout | in minimal view | text | json |
| --- | --- | --- | --- | --- |
| honest_llama | 9 | 9 | ~0.7k | ~2.2k |
| MATT | 43 | 41 | ~3.6k | ~12k |
| Atari-PB | 72 | 69 | ~4.0k | ~14k |
| vjepa2 | 87 | 76 | ~5.8k | ~20k |
| LoRA | 815 | 18 | ~1.3k | ~4.8k |

LoRA was the stress case, not vjepa 2: it ships all of `transformers` under
`examples/NLU`, and unfiltered its blob is ~107k tokens. Any non-root directory
with its own `setup.py` / `pyproject.toml` is treated as a nested project and
marked `is_vendored`, which drops 797 of LoRA's files without losing a single
ground-truth range in any of the 5 repos. Vendored files are skipped at build
time by default (`--include-vendored` to keep them), which takes LoRA's map from
34 MB to 358 KB. All five maps build from scratch in 2.6s.

License headers are also stripped from `summary`: identical in every file of a
repo, and worth ~2k tokens of vjepa 2's blob on their own.

## Known gaps

- No resolver yet, so planner spans are whole symbols and IoU stays at the 0.396
  enclosing-span level.
- Coarse tail blocks. A stanza runs to the next comment, so the last block of a
  sparsely commented function can be ~90 lines. This is the loop-and-conditional
  span item in `REPO_MAP_DEFERRED.md`.
- `merged` scores below single `block` everywhere, unlike the estimate in the
  schema doc. Merging is only worth keeping as an option for the resolver, not as
  a default.
- Python only, and `.ipynb` ground truth (honest_llama's `finetune_gpt.ipynb`) is
  still invisible.
