# Running Evaluations on Annotation Dataset

1. Activate the Python environment:

    ```{bash}
    cd backend
    source .venv/bin/activate
    ```

2. Run agent predictions:

    ```{bash}
    cd backend
    python -m src.evals.run_manual_v1                    # run all 54 annotations
    python -m src.evals.run_manual_v1 --limit 5          # smoke test on first 5
    python -m src.evals.run_manual_v1 --output out.json  # custom output path
    ```

3. Evaluate agent performance:

    ```{bash}
    cd backend
    python -m src.evals.evaluate_manual_v1              # uses default predictions/output paths
    python -m src.evals.evaluate_manual_v1 --predictions X.json --output Y.json
    ```

Computes, per annotation (using the agent's top-ranked predicted snippet):

- `filepath_correct`: does the predicted filepath match a ground-truth location?
- `correct_class` / `correct_method` (only when the filepath is correct): does the
  predicted line range sit in the same class / method as the best-matching
  ground-truth range? Marked `"not_applicable"` when the ground-truth range
  isn't inside a class/method, or the file can't be parsed (Python files only).
  This surfaces cases where the agent points at, e.g., a class/function
  definition rather than the specific lines doing the described work.
- `best_iou` (only when the filepath is correct): max IoU between the predicted
  line range and the ground-truth locations in that file.

Since the class/method check reads real source files, it re-clones each
paper's repo on demand (cleaned up automatically when the script finishes).

