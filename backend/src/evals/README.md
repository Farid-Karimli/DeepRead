# Running Evaluations on Annotation Dataset

1. Activate the Python environment:

    ```{bash}
    cd backend
    source .venv/bin/activate
    ```

2. Run agent predictions:

    ```{bash}
    cd backend
    python -m src.evals.run                    # run all 54 annotations
    python -m src.evals.run --limit 5          # smoke test on first 5
    python -m src.evals.run --output out.json  # custom output path
    python -m src.evals.run --paper 2          # only run annotations for the 2nd paper (1-indexed)
    ```

3. Evaluate agent performance:

    ```{bash}
    cd backend
    python -m src.evals.evaluate              # uses default predictions/output paths
    python -m src.evals.evaluate --predictions X.json --output Y.json
    ```

Computes, per annotation (using the agent's top-ranked predicted snippet):

- `filepath_correct`: does the predicted filepath match a ground-truth location?
- `filepath_hit_at_5`: does *any* of the (up to 5) predicted snippets' filepaths match
  a ground-truth location, regardless of rank? Looser than `filepath_correct`, which
  only looks at the top-ranked snippet; catches cases where the right file was found
  but not ranked first (`filepath_hit_rank` records at what rank it was found).
- `correct_class` / `correct_method` (only when the filepath is correct): does the
  predicted line range sit in the same class / method as the best-matching
  ground-truth range? Marked `"not_applicable"` when the ground-truth range
  isn't inside a class/method, or the file can't be parsed (Python files only).
  This surfaces cases where the agent points at, e.g., a class/function
  definition rather than the specific lines doing the described work.
- `best_iou` (only when the filepath is correct): max IoU between the top-ranked
  predicted line range and the ground-truth locations in that file.
- `mean_iou_matching_filepaths`: average IoU across *all* (up to 5) predicted
  snippets whose filepath matches a ground-truth location, not just the top-ranked
  one. For each matching snippet, the max IoU against ground-truth locations
  sharing its filepath is taken, then those per-snippet values are averaged.
  `null` when no predicted snippet shares a filepath with a ground-truth location.

Since the class/method check reads real source files, it re-clones each
paper's repo on demand (cleaned up automatically when the script finishes).

