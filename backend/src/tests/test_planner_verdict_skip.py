from src.agentic_localization.utils import (
    finalize_resolver_verdict,
    planner_verdict_skips_resolve,
)


def test_planner_verdict_skips_resolve_terminal():
    assert planner_verdict_skips_resolve("not_implemented")
    assert planner_verdict_skips_resolve("not_applicable")
    assert planner_verdict_skips_resolve("  not_implemented  ")


def test_planner_verdict_skips_resolve_implemented():
    assert not planner_verdict_skips_resolve("implemented")
    assert not planner_verdict_skips_resolve("")
    assert not planner_verdict_skips_resolve(None)


def test_finalize_resolver_verdict_empty_snippets():
    v, r = finalize_resolver_verdict(
        snippets=[], model_verdict="implemented", model_reasoning="planner said yes"
    )
    assert v == "not_implemented"
    assert "planner said yes" in r


def test_finalize_resolver_verdict_empty_not_applicable():
    v, _ = finalize_resolver_verdict(
        snippets=[],
        model_verdict="not_applicable",
        model_reasoning="no code concept",
    )
    assert v == "not_applicable"


def test_finalize_resolver_verdict_with_snippets():
    v, _ = finalize_resolver_verdict(
        snippets=[{"file": "a.py"}],
        model_verdict="not_implemented",
        model_reasoning="found it",
    )
    assert v == "implemented"
