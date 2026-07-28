Repo Map — Deferred Items

Fields and capabilities intentionally left out of the POC (`REPO_MAP_SCHEMA.md`).
Each entry states what it is, why it is deferred, what it unlocks, and what would
trigger building it.

## Loop and conditional spans

What: line ranges for `for_statement` / `while_statement` / `if_statement` nodes
inside a function.

Why deferred: `chunk_file` emits `class_definition` and `function_definition` nodes
only, so this needs custom tree-sitter queries — new code paths rather than a field
mapping. `metadata['complexity']['nesting_depth']` confirms the chunker sees loops
but does not expose their spans.

Unlocks: targeting algorithm descriptions ("we iterate over ...") at the loop rather
than the whole function.

Trigger: comment blocks plateau and remaining IoU errors are concentrated in
functions whose stanzas are loop bodies.

## Assignment / binding line index

What: name → line mapping for variable bindings, so `loss` resolves to line 96.

Why deferred: `metadata['exports']` gives the names (`loss`, `similarity`,
`gt_label`) but carries no positions, so it would require walking assignment nodes
directly. Comment blocks already capture most of these bindings as a side effect.

Unlocks: span selection keyed on a variable name rather than a call name.

Trigger: paper content that names a variable with no accompanying call site.

## Inheritance graph

What: base-class edges, e.g. `CURLTrainer(BaseTrainer)`, plus an `is_override` flag
per method.

Why deferred: not present in the class chunk metadata; requires reading the
`argument_list` of the class definition.

Unlocks: following `super().__init__()`, and finding method implementations that
live in a base class rather than the subclass the planner picked. Relevant here —
much of what these papers describe sits in shared base trainers.

Trigger: filepath accuracy failures where the correct location is a base class.

## Import resolution and cross-file calls

What: resolving bare call names (`rearrange`, `aug_func`) to a defining file and
line; a call graph over resolved edges.

Why deferred: needs a repo-wide two-pass build (collect definitions, then resolve
references). The chunker's `references`, `symbol_id`, and `definition_id` fields may
already support part of this, but they were empty or unverified in the output
inspected.

Unlocks: telling "external library" apart from "defined two files over", and
following a chain from the planner's file to the real implementation.

Trigger: verify what the chunker populates in `references` / `definition_id` first;
build only if those are unusable.

## Config → class registry

What: mapping framework config keys to the classes they instantiate, e.g.
`CURLTrainer.name = 'curl'` ↔ `configs/.../curl.yaml: name: curl`.

Why deferred: framework-specific (Hydra here), and orthogonal to the IoU work.

Unlocks: removes a known failure mode. In the traced Haiku and Sonnet runs the agent
burned multiple steps wandering `configs/model/head/atc_head.yaml`,
`configs/pretrain.yaml`, and `configs/model/base.yaml` to answer what is effectively
a lookup.

Trigger: tool traces continue to show config wandering as a large share of steps.

## Notebook support

What: `.ipynb` parsing with per-cell extraction and line-offset mapping back to
notebook numbering; a `cell_index` provenance field.

Why deferred: tree-sitter does not parse `.ipynb`. Only some papers need it.

Unlocks: coverage of ground truth that lives in notebooks, e.g. the ITI paper's
`finetune_gpt.ipynb`.

Trigger: required before reporting numbers on any paper whose ground truth includes
notebooks. Retrofitting the provenance field later is painful, so decide the field
early even if parsing lands later.

## Non-Python languages

What: role tagging, block segmentation, and comment conventions for other languages
the chunker supports (C, Go, JavaScript, Rust, TypeScript).

Why deferred: the annotated corpus is Python. Block segmentation assumes `#`
comments.

Unlocks: repos that are not Python-first.

Trigger: adding a paper whose implementation is not Python.

## Ranking priors

What: using `complexity` and LOC to prefer the substantive implementation over a
thin wrapper, plus `decorators` for registry-based component discovery.

Why deferred: the fields are already in `metadata` and cost nothing to carry, but
using them for ranking is a resolver policy change, not a schema change.

Unlocks: disambiguation between same-named symbols across files.

Trigger: failures where the predicted symbol is a wrapper or stub.

## Memory / past-interaction fields

What: linking map entries to prior accepted mappings so a symbol carries its history
of matched paper content.

Why deferred: separate subsystem (the `mappings` table), and the offline memory
simulation is a distinct experiment from the localization work.

Unlocks: the warm-vs-cold experiment; storing matches keyed on `qualified_name`
rather than line ranges makes them durable across commits.

Trigger: after the localization POC is measured, so the two effects stay separable.
