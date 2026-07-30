from types import SimpleNamespace
from typing import Any

from src import db
from src.types import ContentToCodeResult, PaperMappingRecord


class FakeMappingsQuery:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.filters: list[tuple[str, Any]] = []
        self.orders: list[tuple[str, bool]] = []
        self.limits: list[int] = []

    def select(self, _columns: str) -> "FakeMappingsQuery":
        return self

    def eq(self, column: str, value: Any) -> "FakeMappingsQuery":
        self.filters.append((column, value))
        return self

    def order(self, column: str, desc: bool = False) -> "FakeMappingsQuery":
        self.orders.append((column, desc))
        return self

    def limit(self, value: int) -> "FakeMappingsQuery":
        self.limits.append(value)
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=self.rows)


class FakeSupabase:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.query = FakeMappingsQuery(rows)

    def table(self, name: str) -> FakeMappingsQuery:
        assert name == "mappings"
        return self.query


def mapping_row(
    cache_key: str,
    *,
    verdict: str = "implemented",
    snippets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "paper_id": "paper-1",
        "mapping_type": "content_to_code",
        "cache_key": cache_key,
        "inputs": {
            "content": "The model uses a contrastive objective.",
            "repo_url": "https://github.com/example/repo",
            "context": "Training objective",
            "box": {"l": 0.1, "t": 0.2, "w": 0.3, "h": 0.1},
            "page_number": 2,
        },
        "outputs": {
            "reasoning": "The loss is computed here.",
            "verdict": verdict,
            "code_snippets": snippets
            if snippets is not None
            else [
                {
                    "content": "loss = contrastive_loss(x, y)",
                    "filepath": "src/loss.py",
                    "start_line": 10,
                    "end_line": 10,
                }
            ],
        },
        "created_by": 7,
    }


def test_get_recent_matches_scopes_query_and_returns_chronological_rows(monkeypatch) -> None:
    client = FakeSupabase(
        [
            mapping_row("newest"),
            mapping_row("not-implemented", verdict="not_implemented"),
            mapping_row("oldest"),
        ]
    )
    monkeypatch.setattr(db, "is_configured", lambda: True)
    monkeypatch.setattr(db, "get_supabase_client", lambda: client)

    records = db.get_recent_content_to_code_matches_by_paper_and_user(
        "paper-1",
        7,
    )

    assert [record.cache_key for record in records] == [
        "oldest",
        "not-implemented",
        "newest",
    ]
    assert client.query.filters == [
        ("paper_id", "paper-1"),
        ("mapping_type", "content_to_code"),
        ("created_by", 7),
    ]
    assert client.query.orders == [("created_at", True)]
    assert client.query.limits == [3]


def test_memory_snapshot_round_trips_inside_existing_outputs_json() -> None:
    row = mapping_row("source-1")
    row["outputs"]["memory_snapshot"] = {
        "strategy": "recent",
        "version": "v1",
        "hints": [
            {
                "source_cache_key": "earlier-match",
                "source_content": "A related contrastive loss.",
                "verdict": "implemented",
                "reasoning": "The prior interaction found this loss.",
                "paths": ["src/loss.py:10-12"],
                "folders": ["src"],
            }
        ],
    }

    record = PaperMappingRecord.model_validate(row)

    assert isinstance(record.outputs, ContentToCodeResult)
    assert record.outputs.memory_snapshot is not None
    assert record.outputs.memory_snapshot.hints[0].source_cache_key == "earlier-match"
    assert (
        record.model_dump(mode="json")["outputs"]["memory_snapshot"]["version"]
        == "v1"
    )
