from src.agentic_localization.utils import planner_verdict_skips_resolve


def test_planner_verdict_skips_resolve_terminal():
    assert planner_verdict_skips_resolve("not_implemented")
    assert planner_verdict_skips_resolve("not_applicable")
    assert planner_verdict_skips_resolve("  not_implemented  ")


def test_planner_verdict_skips_resolve_implemented():
    assert not planner_verdict_skips_resolve("implemented")
    assert not planner_verdict_skips_resolve("")
    assert not planner_verdict_skips_resolve(None)
