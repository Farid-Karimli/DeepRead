# Eval synthesis (`manual_v1`)

54 annotations, 5 papers. Metrics from `evaluate.py` on each run’s predictions JSON unless noted.

**Oracle ceiling** (repo-map span menu, no model): best IoU **0.573** on `.py` GT ranges (`agentic_localization` oracle).

---

## Full dataset (n=54)

| Run | Filepath top-1 | Hit@5 | Method acc. | IoU (correct fp) | s / ann. | Tool calls / ann. |
| --- | --- | --- | --- | --- | --- | --- |
| v0.0 baseline (Claude Code) | 51.9% | 79.6% | 59.1% (13/22) | 0.234 | 62.8 | — |
| v0.5 baseline sonnet | 51.9% | 74.1% | 65.2% (15/23) | 0.394 | 97.6 | — |
| **v0.8 planner only** | **75.9%** | 83.3% | 61.8% (21/34) | 0.278 | **38.5** | **0** |
| v0.8 planner + menu | 68.5% | 75.9% | 59.4% (19/32) | 0.303 | 71.8 | 0 |
| **v0.8 planner + crawl** | 74.1% | 83.3% | **84.4% (27/32)** | **0.402** | 110.4 | **14.8** |

## Paper 1 only — Atari-PB (n=12, apples-to-apples with early baselines)

| Run | Filepath top-1 | Hit@5 | Method acc. | IoU (correct fp) | s / ann. |
| --- | --- | --- | --- | --- | --- |
| v0.1 baseline sonnet | 66.7% | 100% | 33.3% (2/6) | 0.241 | 67.4 |
| v0.6 baseline haiku | 66.7% | 91.7% | 57.1% (4/7) | 0.194 | 33.7 |
| v0.7 planner only | 91.7% | 100% | 70.0% (7/10) | 0.186 | 12.5 |
| v0.8 planner only | 100% | 100% | 70.0% (7/10) | 0.122 | — |
| v0.8 planner + crawl | 100% | 100% | 90.0% (9/10) | 0.397 | — |

*(v0.8 per-paper timings omitted; full-run means above.)*

---

## Cost / effort (what we actually logged)

| Run | Mean input tokens* | Mean output tokens* | USD logged |
| --- | --- | --- | --- |
| v0.7 planner (n=12) | ~7.6k† | ~494 | **$0.81** total |
| v0.8 planner only | 7,022 | 474 | N/A |
| v0.8 planner + menu | 7,022‡ | 454‡ | N/A |
| v0.8 planner + crawl | 7,022‡ | 469‡ | N/A |
| v0.6 haiku baseline | — | — | N/A (~10 tool calls / ann.) |

\*Anthropic planner step only in v0.8; resolver (menu/crawl) tokens not yet rolled into `process_metrics`.  
†From v0.7 `process_metrics.usage` (harness-era run).  
‡Planner `get_candidates` only; menu adds one LLM call, crawl adds ~15 tool steps + final JSON.

**Time vs tokens:** Planner-only is **~3× faster** than full-dataset baseline sonnet (38s vs 98s) with **much higher filepath accuracy**. Crawl adds **~3× latency** over planner-only (110s) for the largest quality jump on **method** (+23 pts) and **IoU** (+0.12).

---

## Biggest signals

1. **Repo-map planner beats blind Search/ReadFile on files.** Full-set filepath top-1 jumps from ~52% (baselines) to ~76% (planner only) at lower latency and zero tool calls.

2. **Whole-symbol spans cap IoU without a resolver.** Planner-only IoU stays ~0.18–0.28 even when filepath is right; method accuracy suffers when the anchor is a class but GT is a method body.

3. **Menu resolver underperformed on the full 54.** One extra LLM call over planner candidates did not beat map-only anchors: filepath and method **dropped** vs planner-only. Likely brittle span-index picking without repo reads.

4. **Guided crawl is the quality knob.** Planner + crawl matches planner filepath (~74%), lifts **method to 84%** and **IoU to 0.40** (vs 0.28 planner-only), at ~15 repo-map tool calls and ~110s/annotation — comparable wall time to baseline sonnet crawl but far better filepath and method.

5. **Tradeoff summary**
   - **Min cost / latency:** planner only → good files, coarse spans.
   - **Best localization quality:** planner + crawl → ~2.9× planner-only time, ~15 tool calls, best method/IoU in this sweep.
   - **Skip:** menu path on current prompt/schema (cost without gain on n=54).

6. **Hard papers:** MATT and honest_llama remain weak on filepath across strategies (~42–67% top-1 in v0.8); gains concentrate on Atari-PB, LoRA, vjepa2.

---

## Source artifacts

| Run | Predictions | Metrics |
| --- | --- | --- |
| v0.0 | `v0.0/manual_v1_predictions.json` | `v0.0/manual_v1_metrics.md` |
| v0.1 | `v0.1/sonnet5-predictions.json` | `v0.1/sonnet5-metrics.md` |
| v0.5 | `v0.5/sonnet5-predictions.json` | `v0.5/sonnet5-metrics.md` |
| v0.6 haiku | `v0.6/haiku-predictions.json` | `v0.6/haiku-metrics.md` |
| v0.7 planner | `v0.7/planner-sonnet-predictions.json` | `v0.7/planner-sonnet-metrics.md` |
| v0.8 planner | `v0.8/planner-only-*` | |
| v0.8 menu | `v0.8/planner-menu-*` | |
| v0.8 crawl | `v0.8/planner-crawl-*` | |
