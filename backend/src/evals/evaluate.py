"""
Scores predictions produced by `run.py` against the ground-truth
locations in `annotations/manual_v1.json`.

For each annotation, the agent's top-ranked predicted code snippet (the first
entry in `code_snippets`, i.e. the best-reranked candidate) is compared
against the annotation's ground-truth locations, at increasingly fine
granularity:

- Filepath accuracy: does the predicted filepath match any ground-truth
  location's filepath for that annotation?
- Filepath hit@5: does *any* of the (up to 5) predicted snippets' filepaths
  match a ground-truth location's filepath? This is looser than filepath
  accuracy above (which only looks at the top-ranked snippet) and captures
  cases where the correct file was found but not ranked first.
- Class / method accuracy (only when the filepath is correct): does the
  predicted line range sit inside the same class / method as the
  ground-truth range that best overlaps it? This catches cases where the
  agent points at, say, a class or function *definition* (e.g. a loss
  function's name) rather than the specific lines that do the actual work
  described in the paper. Marked "not_applicable" when the ground-truth
  range itself isn't inside a class/method (e.g. module-level code), or
  when the file can't be parsed (only Python files are currently
  supported).
- Line-range IoU (only when the filepath is correct): the max IoU between
  the top-ranked predicted line range and every ground-truth location that
  shares the predicted filepath (an annotation can have multiple locations
  in the same file).
- Mean IoU across matching filepaths: unlike the top-1-only IoU above, this
  considers every one of the (up to 5) predicted snippets whose filepath
  matches a ground-truth location. For each such snippet, the max IoU
  against the ground-truth locations sharing its filepath is computed, then
  those per-snippet IoUs are averaged. `None` when none of the predicted
  snippets share a filepath with any ground-truth location.

Reading source files for the class/method check requires the paper's
GitHub repo to be cloned locally (same as `run.py`); repos are
cloned on demand and cleaned up when the script finishes.

Usage:
    python -m src.evals.evaluate [--predictions PATH] [--annotations PATH] [--output PATH]
"""

import argparse
import ast
import json
import os

from src.utils import clone_repo_to_temp_dir, delete_temp_dir, normalize_github_repo_url

DEFAULT_PREDICTIONS_PATH = os.path.join(
    os.path.dirname(__file__), "results", "manual_v1_predictions.json"
)
DEFAULT_ANNOTATIONS_PATH = os.path.join(
    os.path.dirname(__file__), "annotations", "manual_v1.json"
)
DEFAULT_OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "results", "manual_v1_metrics.json"
)

NOT_APPLICABLE = "not_applicable"


def get_predicted_snippets(prediction: dict | None) -> list[dict]:
    """Normalizes both the current `code_snippets` (list) schema and the
    older single `code_snippet` schema into a list of
    {filepath, start_line, end_line}, ordered best-first."""
    if not isinstance(prediction, dict):
        return []

    snippets = prediction.get("code_snippets")
    if isinstance(snippets, list) and len(snippets) > 0:
        return [s for s in snippets if isinstance(s, dict)]

    legacy_snippet = prediction.get("code_snippet")
    if isinstance(legacy_snippet, dict):
        return [legacy_snippet]

    return []


def line_range_iou(range_a: tuple[int, int], range_b: tuple[int, int]) -> float:
    """Intersection-over-union of two inclusive 1D line ranges."""
    start_a, end_a = range_a
    start_b, end_b = range_b

    len_a = max(0, end_a - start_a + 1)
    len_b = max(0, end_b - start_b + 1)
    if len_a == 0 or len_b == 0:
        return 0.0

    intersection = max(0, min(end_a, end_b) - max(start_a, start_b) + 1)
    union = len_a + len_b - intersection
    if union == 0:
        return 0.0
    return intersection / union


class _ScopeIndex(ast.NodeVisitor):
    """Indexes a Python module's class/method spans so a line number can be
    mapped to its innermost enclosing class and qualified method name."""

    def __init__(self) -> None:
        self._class_stack: list[str] = []
        # (start_line, end_line, class_name)
        self.class_spans: list[tuple[int, int, str]] = []
        # (start_line, end_line, qualified_name, class_name_or_none)
        self.func_spans: list[tuple[int, int, str, str | None]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        end = getattr(node, "end_lineno", node.lineno)
        self.class_spans.append((node.lineno, end, node.name))
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        end = getattr(node, "end_lineno", node.lineno)
        class_name = self._class_stack[-1] if self._class_stack else None
        qualified = f"{class_name}.{node.name}" if class_name else node.name
        self.func_spans.append((node.lineno, end, qualified, class_name))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    @classmethod
    def from_source(cls, source: str) -> "_ScopeIndex | None":
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None
        index = cls()
        index.visit(tree)
        return index

    def enclosing_class(self, line: int) -> str | None:
        containing = [s for s in self.class_spans if s[0] <= line <= s[1]]
        if not containing:
            return None
        return min(containing, key=lambda s: s[1] - s[0])[2]

    def enclosing_method(self, line: int) -> str | None:
        containing = [s for s in self.func_spans if s[0] <= line <= s[1]]
        if not containing:
            return None
        return min(containing, key=lambda s: s[1] - s[0])[2]


class RepoSourceCache:
    """Clones repos on demand and caches parsed scope indexes per file, so
    the same repo/file isn't re-cloned/re-parsed for every annotation."""

    def __init__(self, paper_repo_urls: dict[str, str]) -> None:
        self._paper_repo_urls = paper_repo_urls
        self._repo_dirs: dict[str, str] = {}  # repo_url -> local dir
        self._scope_cache: dict[tuple[str, str], _ScopeIndex | None] = {}

    def _repo_dir_for_paper(self, paper_id: str) -> str | None:
        repo_url = self._paper_repo_urls.get(paper_id)
        if not repo_url:
            return None
        if repo_url not in self._repo_dirs:
            try:
                self._repo_dirs[repo_url] = clone_repo_to_temp_dir(repo_url)
            except Exception as exc:
                print(f"Warning: failed to clone {repo_url} for {paper_id}: {exc}")
                self._repo_dirs[repo_url] = None
        return self._repo_dirs[repo_url]

    def scope_index_for(self, paper_id: str, filepath: str) -> "_ScopeIndex | None":
        repo_dir = self._repo_dir_for_paper(paper_id)
        if repo_dir is None:
            return None

        cache_key = (repo_dir, filepath)
        if cache_key in self._scope_cache:
            return self._scope_cache[cache_key]

        index = None
        if filepath.endswith(".py"):
            try:
                with open(os.path.join(repo_dir, filepath), "r", encoding="utf-8") as f:
                    source = f.read()
                index = _ScopeIndex.from_source(source)
            except OSError:
                index = None

        self._scope_cache[cache_key] = index
        return index

    def cleanup(self) -> None:
        for repo_dir in self._repo_dirs.values():
            if repo_dir:
                delete_temp_dir(repo_dir)


def build_paper_repo_urls(annotations_path: str) -> dict[str, str]:
    with open(annotations_path, "r") as f:
        data = json.load(f)

    paper_repo_urls: dict[str, str] = {}
    for paper in data.get("papers", []):
        repo_url = normalize_github_repo_url((paper.get("repo_path") or "").rstrip(". "))
        if repo_url:
            paper_repo_urls[paper.get("paper_id")] = repo_url
    return paper_repo_urls


def compare_scopes(
    source_cache: RepoSourceCache,
    paper_id: str,
    filepath: str,
    predicted_start_line: int,
    ground_truth_start_line: int,
) -> tuple[bool | str, bool | str, str | None, str | None, str | None, str | None]:
    """Returns (correct_class, correct_method, predicted_class,
    predicted_method, ground_truth_class, ground_truth_method).
    `correct_class`/`correct_method` are booleans, or `NOT_APPLICABLE` when
    the ground-truth position isn't inside a class/method, or the file
    couldn't be parsed (non-Python file, syntax error, missing file)."""
    scope_index = source_cache.scope_index_for(paper_id, filepath)
    if scope_index is None:
        return NOT_APPLICABLE, NOT_APPLICABLE, None, None, None, None

    ground_truth_class = scope_index.enclosing_class(ground_truth_start_line)
    ground_truth_method = scope_index.enclosing_method(ground_truth_start_line)
    predicted_class = scope_index.enclosing_class(predicted_start_line)
    predicted_method = scope_index.enclosing_method(predicted_start_line)

    correct_class: bool | str = (
        NOT_APPLICABLE if ground_truth_class is None else predicted_class == ground_truth_class
    )
    correct_method: bool | str = (
        NOT_APPLICABLE if ground_truth_method is None else predicted_method == ground_truth_method
    )

    return correct_class, correct_method, predicted_class, predicted_method, ground_truth_class, ground_truth_method


def evaluate_annotation(record: dict, source_cache: RepoSourceCache) -> dict:
    ground_truth_locations = record.get("ground_truth_locations") or []
    predicted_snippets = get_predicted_snippets(record.get("prediction"))
    top_prediction = predicted_snippets[0] if predicted_snippets else None

    result = {
        "paper_id": record.get("paper_id"),
        "annotation_id": record.get("annotation_id"),
        "duration_seconds": record.get("duration_seconds"),
        "had_error": bool(record.get("error")),
        "predicted_filepath": top_prediction.get("filepath") if top_prediction else None,
        "predicted_line_range": (
            [top_prediction.get("start_line"), top_prediction.get("end_line")]
            if top_prediction
            else None
        ),
        "ground_truth_filepaths": sorted({loc.get("filepath") for loc in ground_truth_locations if loc.get("filepath")}),
        "num_predicted_snippets": len(predicted_snippets),
        "filepath_correct": False,
        "filepath_hit_at_5": False,
        "filepath_hit_rank": None,
        "best_iou": None,
        "matched_ground_truth_range": None,
        "mean_iou_matching_filepaths": None,
        "num_matching_filepath_snippets": 0,
        "correct_class": None,
        "correct_method": None,
        "predicted_class": None,
        "predicted_method": None,
        "ground_truth_class": None,
        "ground_truth_method": None,
    }

    ground_truth_filepaths = set(result["ground_truth_filepaths"])
    for rank, snippet in enumerate(predicted_snippets, start=1):
        if snippet.get("filepath") in ground_truth_filepaths:
            result["filepath_hit_at_5"] = True
            result["filepath_hit_rank"] = rank
            break

    matching_filepath_ious: list[float] = []
    for snippet in predicted_snippets:
        snippet_filepath = snippet.get("filepath")
        snippet_matching_locations = [
            loc for loc in ground_truth_locations if loc.get("filepath") == snippet_filepath
        ]
        if not snippet_matching_locations:
            continue

        snippet_range = (snippet.get("start_line"), snippet.get("end_line"))
        if snippet_range[0] is None or snippet_range[1] is None:
            continue

        best_snippet_iou = 0.0
        for loc in snippet_matching_locations:
            gt_range = loc.get("line_range") or [None, None]
            if gt_range[0] is None or gt_range[1] is None:
                continue
            best_snippet_iou = max(best_snippet_iou, line_range_iou(snippet_range, tuple(gt_range)))
        matching_filepath_ious.append(best_snippet_iou)

    result["num_matching_filepath_snippets"] = len(matching_filepath_ious)
    result["mean_iou_matching_filepaths"] = (
        sum(matching_filepath_ious) / len(matching_filepath_ious) if matching_filepath_ious else None
    )

    if top_prediction is None or not ground_truth_locations:
        return result

    predicted_filepath = top_prediction.get("filepath")
    matching_locations = [loc for loc in ground_truth_locations if loc.get("filepath") == predicted_filepath]
    result["filepath_correct"] = len(matching_locations) > 0

    if not result["filepath_correct"]:
        return result

    predicted_range = (top_prediction.get("start_line"), top_prediction.get("end_line"))
    best_iou = 0.0
    best_gt_range = None
    for loc in matching_locations:
        gt_range = loc.get("line_range") or [None, None]
        if gt_range[0] is None or gt_range[1] is None or predicted_range[0] is None or predicted_range[1] is None:
            continue
        iou = line_range_iou(tuple(predicted_range), tuple(gt_range))
        if iou >= best_iou:
            best_iou = iou
            best_gt_range = gt_range
    result["best_iou"] = best_iou
    result["matched_ground_truth_range"] = best_gt_range

    if best_gt_range is not None and predicted_range[0] is not None:
        (
            correct_class,
            correct_method,
            predicted_class,
            predicted_method,
            ground_truth_class,
            ground_truth_method,
        ) = compare_scopes(
            source_cache,
            record.get("paper_id"),
            predicted_filepath,
            predicted_range[0],
            best_gt_range[0],
        )
        result["correct_class"] = correct_class
        result["correct_method"] = correct_method
        result["predicted_class"] = predicted_class
        result["predicted_method"] = predicted_method
        result["ground_truth_class"] = ground_truth_class
        result["ground_truth_method"] = ground_truth_method

    return result


def _accuracy_over_applicable(values: list[bool | str]) -> tuple[float | None, int, int]:
    """Accuracy over the subset of values that are booleans (excluding
    `NOT_APPLICABLE` and `None`). Returns (accuracy, num_correct, num_applicable)."""
    applicable = [v for v in values if isinstance(v, bool)]
    num_correct = sum(1 for v in applicable if v)
    accuracy = num_correct / len(applicable) if applicable else None
    return accuracy, num_correct, len(applicable)


def summarize(per_annotation: list[dict]) -> dict:
    total = len(per_annotation)
    num_errored = sum(1 for r in per_annotation if r["had_error"])
    num_with_prediction = sum(1 for r in per_annotation if r["predicted_filepath"] is not None)
    num_filepath_correct = sum(1 for r in per_annotation if r["filepath_correct"])
    num_filepath_hit_at_5 = sum(1 for r in per_annotation if r["filepath_hit_at_5"])

    ious = [r["best_iou"] for r in per_annotation if r["filepath_correct"] and r["best_iou"] is not None]
    matching_filepath_ious = [
        r["mean_iou_matching_filepaths"] for r in per_annotation if r["mean_iou_matching_filepaths"] is not None
    ]
    durations = [r["duration_seconds"] for r in per_annotation if isinstance(r["duration_seconds"], (int, float))]

    class_accuracy, num_class_correct, num_class_applicable = _accuracy_over_applicable(
        [r["correct_class"] for r in per_annotation]
    )
    method_accuracy, num_method_correct, num_method_applicable = _accuracy_over_applicable(
        [r["correct_method"] for r in per_annotation]
    )

    by_paper: dict[str, dict] = {}
    for r in per_annotation:
        paper_id = r["paper_id"] or "unknown"
        bucket = by_paper.setdefault(
            paper_id,
            {
                "total": 0,
                "filepath_correct": 0,
                "filepath_hit_at_5": 0,
                "ious": [],
                "matching_filepath_ious": [],
                "correct_class": [],
                "correct_method": [],
            },
        )
        bucket["total"] += 1
        if r["filepath_correct"]:
            bucket["filepath_correct"] += 1
            if r["best_iou"] is not None:
                bucket["ious"].append(r["best_iou"])
        if r["filepath_hit_at_5"]:
            bucket["filepath_hit_at_5"] += 1
        if r["mean_iou_matching_filepaths"] is not None:
            bucket["matching_filepath_ious"].append(r["mean_iou_matching_filepaths"])
        bucket["correct_class"].append(r["correct_class"])
        bucket["correct_method"].append(r["correct_method"])

    by_paper_summary = {}
    for paper_id, bucket in by_paper.items():
        paper_class_accuracy, _, paper_class_applicable = _accuracy_over_applicable(bucket["correct_class"])
        paper_method_accuracy, _, paper_method_applicable = _accuracy_over_applicable(bucket["correct_method"])
        by_paper_summary[paper_id] = {
            "total_annotations": bucket["total"],
            "filepath_accuracy": bucket["filepath_correct"] / bucket["total"] if bucket["total"] else None,
            "filepath_hit_at_5_rate": bucket["filepath_hit_at_5"] / bucket["total"] if bucket["total"] else None,
            "mean_iou_given_correct_filepath": (
                sum(bucket["ious"]) / len(bucket["ious"]) if bucket["ious"] else None
            ),
            "mean_iou_matching_filepaths": (
                sum(bucket["matching_filepath_ious"]) / len(bucket["matching_filepath_ious"])
                if bucket["matching_filepath_ious"]
                else None
            ),
            "num_annotations_with_matching_filepath_iou": len(bucket["matching_filepath_ious"]),
            "class_accuracy_given_applicable": paper_class_accuracy,
            "num_class_applicable": paper_class_applicable,
            "method_accuracy_given_applicable": paper_method_accuracy,
            "num_method_applicable": paper_method_applicable,
        }

    return {
        "total_annotations": total,
        "num_errored": num_errored,
        "num_with_prediction": num_with_prediction,
        "num_filepath_correct": num_filepath_correct,
        "filepath_accuracy": num_filepath_correct / total if total else None,
        "num_filepath_hit_at_5": num_filepath_hit_at_5,
        "filepath_hit_at_5_rate": num_filepath_hit_at_5 / total if total else None,
        "mean_iou_given_correct_filepath": sum(ious) / len(ious) if ious else None,
        "num_annotations_with_iou": len(ious),
        "mean_iou_matching_filepaths": (
            sum(matching_filepath_ious) / len(matching_filepath_ious) if matching_filepath_ious else None
        ),
        "num_annotations_with_matching_filepath_iou": len(matching_filepath_ious),
        "class_accuracy_given_applicable": class_accuracy,
        "num_class_correct": num_class_correct,
        "num_class_applicable": num_class_applicable,
        "method_accuracy_given_applicable": method_accuracy,
        "num_method_correct": num_method_correct,
        "num_method_applicable": num_method_applicable,
        "mean_duration_seconds": sum(durations) / len(durations) if durations else None,
        "by_paper": by_paper_summary,
    }


def evaluate(predictions_path: str, annotations_path: str, output_path: str) -> dict:
    with open(predictions_path, "r") as f:
        predictions = json.load(f)

    paper_repo_urls = build_paper_repo_urls(annotations_path)
    source_cache = RepoSourceCache(paper_repo_urls)

    try:
        per_annotation = [evaluate_annotation(record, source_cache) for record in predictions]
    finally:
        source_cache.cleanup()

    summary = summarize(per_annotation)

    output = {"summary": summary, "annotations": per_annotation}

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote evaluation results to {output_path}")
    print(json.dumps(summary, indent=2))

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", default=DEFAULT_PREDICTIONS_PATH, help="Path to predictions JSON produced by run.py")
    parser.add_argument("--annotations", default=DEFAULT_ANNOTATIONS_PATH, help="Path to the annotations JSON file (used to resolve each paper's repo for the class/method check)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help="Path to write evaluation metrics JSON to")
    args = parser.parse_args()

    evaluate(args.predictions, args.annotations, args.output)


if __name__ == "__main__":
    main()
