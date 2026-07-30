from src.evals.memory import EvaluationMemory


def prediction(filepath: str, verdict: str = "implemented") -> dict:
    return {
        "reasoning": "Prediction only.",
        "verdict": verdict,
        "code_snippets": (
            [
                {
                    "content": "pass",
                    "filepath": filepath,
                    "start_line": 4,
                    "end_line": 8,
                }
            ]
            if verdict == "implemented"
            else []
        ),
    }


def remember(
    memory: EvaluationMemory,
    annotation_id: str,
    content: str,
    predicted_filepath: str,
    verdict: str = "implemented",
) -> None:
    memory.remember(
        paper_id="paper-1",
        annotation_id=annotation_id,
        content=content,
        context="Paper context",
        repo_url="https://github.com/example/repo",
        prediction=prediction(predicted_filepath, verdict),
    )


def test_eval_memory_is_cold_before_any_prediction() -> None:
    snapshot = EvaluationMemory().retrieve("paper-1")

    assert snapshot.strategy == "recent"
    assert snapshot.hints == []


def test_eval_memory_uses_last_three_predictions_not_ground_truth() -> None:
    memory = EvaluationMemory()
    remember(memory, "first", "first claim", "predicted/first.py")
    remember(memory, "second", "second claim", "predicted/second.py")
    remember(
        memory,
        "failed",
        "unmatched claim",
        "ground_truth/must_not_appear.py",
        verdict="not_implemented",
    )
    remember(memory, "fourth", "fourth claim", "predicted/fourth.py")

    snapshot = memory.retrieve("paper-1")

    assert [hint.source_cache_key for hint in snapshot.hints] == [
        "eval:second",
        "eval:failed",
        "eval:fourth",
    ]
    assert snapshot.hints[0].paths == ["predicted/second.py:4-8"]
    assert snapshot.hints[1].paths == []
    assert all("ground_truth" not in path for hint in snapshot.hints for path in hint.paths)


def test_eval_memory_is_isolated_per_paper() -> None:
    memory = EvaluationMemory()
    remember(memory, "first", "contrastive loss", "src/loss.py")

    assert memory.retrieve("paper-2").hints == []
