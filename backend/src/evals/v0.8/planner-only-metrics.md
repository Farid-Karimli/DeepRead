Results for `planner-only-metrics.json`.

## Overall

| Metric | Value |
| --- | --- |
| Total annotations | 54 |
| Errored | 0 |
| With prediction | 52 |
| Filepath accuracy (top-1) | 75.93% (41/54) |
| Filepath hit@5 | 83.33% (45/54) |
| Mean IoU (given correct filepath, top-1) | 0.278 (n=41) |
| Mean IoU (across all matching-filepath snippets) | 0.209 (n=45) |
| Class accuracy (given applicable) | 95.45% (21/22) |
| Method accuracy (given applicable) | 61.76% (21/34) |
| Mean duration (s) | 38.45 |
| Mean tool calls | 0.00 |
| Total cost (USD) | N/A |
| Mean input tokens | 7022 |
| Mean output tokens | 474 |

## By paper

| Paper | Annotations | Filepath accuracy | Filepath hit@5 | Mean IoU (correct filepath, top-1) | Mean IoU (matching filepaths) | Class accuracy (n applicable) | Method accuracy (n applicable) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| investigating_pre_training_objectives_for_generalization_in_vision_based_reinforcement_learning | 12 | 100.00% | 100.00% | 0.122 | 0.124 (n=12) | 100.00% (n=9) | 70.00% (n=10) |
| inference_time_intervention_eliciting_truthful_answers_from_a_language_mode | 12 | 66.67% | 75.00% | 0.623 | 0.354 (n=9) | 100.00% (n=1) | 75.00% (n=8) |
| lora_low_rank_adaptation_of_large_lan_guage_models | 5 | 80.00% | 100.00% | 0.260 | 0.265 (n=5) | 75.00% (n=4) | 50.00% (n=4) |
| mistake_attribution_fine_grained_mistake_understanding_in_egocentric_videos | 12 | 50.00% | 66.67% | 0.325 | 0.256 (n=8) | 100.00% (n=3) | 100.00% (n=3) |
| v_jepa_2_self_supervised_video_models_enable_understanding_prediction_and_planning | 13 | 84.62% | 84.62% | 0.179 | 0.123 (n=11) | 100.00% (n=5) | 33.33% (n=9) |
