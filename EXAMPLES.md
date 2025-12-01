# RepliCode Examples

This document provides examples of running the **replicode** tool on different types of repositories.

## Installation

First, install the package:

```bash
pip install -r requirements.txt
pip install -e .
```

Or run directly:

```bash
pip install rich
```

## Example 1: Well-Structured ML Repository

We've created a sample well-structured ML repository at `example_repos/good_ml_repo/`.

### Running the Analysis

```bash
python -m replicode.cli example_repos/good_ml_repo
```

### Console Output

```
Analyzing repository: example_repos/good_ml_repo


╭────────────────────────────────────────────────────╮
│ RepliCode - ML Repository Reproducibility Analysis │
╰────────────────────────────────────────────────────╯

Repository: /home/user/RepliCode/example_repos/good_ml_repo

╭──────────────────────────────────────────────────────────────────────────────╮
│ ✅ 88% Overall Reproducibility Readiness                                     │
╰──────────────────────────────────────────────────────────────────────────────╯

                   Detailed Scores
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ Category                  ┃      Score ┃  Status  ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━┩
│ Training Code             │       100% │    ✅    │
│ Inference/Demo Code       │       100% │    ✅    │
│ Configuration & Arguments │       100% │    ✅    │
│ Environment Specification │        40% │    ❌    │
│ Documentation             │       100% │    ✅    │
└───────────────────────────┴────────────┴──────────┘

Analysis Details:

Training Code:
  • Found 1 training script(s): train.py
  • Training code contains key constructs: dataloader, epoch, torch.optim, loss

Inference/Demo Code:
  • Found 1 inference/demo script(s): inference.py
  • Inference code contains model loading/prediction logic

Configuration & Arguments:
  • Found 1 configuration file(s)
  • Scripts use argument parsing (argparse/click/fire)

Environment Specification:
  • Environment specification found: requirements.txt

Documentation:
  • README found: README.md
  • README contains installation instructions
  • README contains usage instructions
  • README mentions training
  • README includes example commands
```

### What This Repository Contains

```
good_ml_repo/
├── README.md                    # Comprehensive documentation
├── requirements.txt             # Python dependencies
├── train.py                     # Training script with argparse
├── inference.py                 # Inference/demo script
└── configs/
    └── train_config.yaml        # Configuration file
```

## Example 2: Poorly Structured Repository

We've created a sample poorly-structured repository at `example_repos/poor_ml_repo/`.

### Running the Analysis

```bash
python -m replicode.cli example_repos/poor_ml_repo
```

### Console Output

```
Analyzing repository: example_repos/poor_ml_repo


╭────────────────────────────────────────────────────╮
│ RepliCode - ML Repository Reproducibility Analysis │
╰────────────────────────────────────────────────────╯

Repository: /home/user/RepliCode/example_repos/poor_ml_repo

╭──────────────────────────────────────────────────────────────────────────────╮
│ ❌ 0% Overall Reproducibility Readiness                                      │
╰──────────────────────────────────────────────────────────────────────────────╯

                   Detailed Scores
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ Category                  ┃      Score ┃  Status  ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━┩
│ Training Code             │         0% │    ❌    │
│ Inference/Demo Code       │         0% │    ❌    │
│ Configuration & Arguments │         0% │    ❌    │
│ Environment Specification │         0% │    ❌    │
│ Documentation             │         0% │    ❌    │
└───────────────────────────┴────────────┴──────────┘

Analysis Details:

Training Code:
  • No training script found (e.g., train.py, trainer.py)

Inference/Demo Code:
  • No inference/demo script found

Configuration & Arguments:
  • No argument parsing detected in main scripts
  • No configuration files or argument parsing found

Environment Specification:
  • No environment specification file found (requirements.txt, environment.yml, etc.)

Documentation:
  • No README file found

⚠️  Issues Detected:
  •  No training script found (e.g., train.py, trainer.py)
  •  No inference/demo script found
  •  No argument parsing detected in main scripts
  •  No configuration files or argument parsing found
  •  No environment specification file found (requirements.txt, environment.yml, etc.)
  •  No README file found
```

## Example 3: Generating JSON Output

You can save the analysis results as JSON for programmatic processing:

```bash
python -m replicode.cli example_repos/good_ml_repo --json-out results.json
```

### JSON Output Format

```json
{
  "repo_path": "/home/user/RepliCode/example_repos/good_ml_repo",
  "scores": {
    "training_code": 1.0,
    "inference_code": 1.0,
    "config_and_args": 1.0,
    "environment_spec": 0.4,
    "documentation": 1.0,
    "overall_repro_readiness": 0.88
  },
  "flags": []
}
```

For the poor repository:

```json
{
  "repo_path": "/home/user/RepliCode/example_repos/poor_ml_repo",
  "scores": {
    "training_code": 0.0,
    "inference_code": 0.0,
    "config_and_args": 0.0,
    "environment_spec": 0.0,
    "documentation": 0.0,
    "overall_repro_readiness": 0.0
  },
  "flags": [
    "[training_code] No training script found (e.g., train.py, trainer.py)",
    "[inference_code] No inference/demo script found",
    "[config_and_args] No argument parsing detected in main scripts",
    "[config_and_args] No configuration files or argument parsing found",
    "[environment_spec] No environment specification file found (requirements.txt, environment.yml, etc.)",
    "[documentation] No README file found"
  ]
}
```

## Example 4: Plain Text Output (No Colors)

If you're running in an environment without color support or want plain text:

```bash
python -m replicode.cli example_repos/good_ml_repo --no-color
```

This will produce a simpler, non-colored output suitable for logging or CI/CD pipelines.

## Example 5: Using in CI/CD

The tool returns different exit codes based on the overall score:

- **Exit 0**: Good score (≥ 0.6)
- **Exit 1**: Low score (0.3 - 0.6)
- **Exit 2**: Very low score (< 0.3)

Example CI/CD usage:

```yaml
# .github/workflows/reproducibility-check.yml
name: Reproducibility Check

on: [push, pull_request]

jobs:
  check-repro:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'

      - name: Install replicode
        run: |
          pip install rich
          pip install -e git+https://github.com/yourusername/replicode.git#egg=replicode

      - name: Run reproducibility check
        run: |
          replicode . --json-out repro-score.json

      - name: Upload results
        uses: actions/upload-artifact@v2
        if: always()
        with:
          name: reproducibility-report
          path: repro-score.json
```

## Example 6: Analyzing a Real Repository

To analyze any local repository:

```bash
# Clone a repository
git clone https://github.com/some-user/ml-project
cd ml-project

# Run replicode
replicode .

# Or specify the path
replicode /path/to/ml-project
```

## Tips for Improving Your Score

Based on the analysis, here's how to improve your reproducibility readiness:

1. **Training Code (100% = 1.0)**:
   - Add `train.py` or `trainer.py`
   - Include key ML constructs: optimizer, loss, dataloader, epochs, backprop

2. **Inference Code (100% = 1.0)**:
   - Add `inference.py`, `demo.py`, or `predict.py`
   - Include model loading and prediction logic

3. **Configuration & Arguments (100% = 1.0)**:
   - Add config files in YAML/JSON format
   - Use argument parsing (argparse, click, fire) in main scripts

4. **Environment Specification (100% = 1.0)**:
   - Add `requirements.txt` (most important)
   - Consider `environment.yml` for conda users
   - Add `setup.py` or `pyproject.toml` for installable packages

5. **Documentation (100% = 1.0)**:
   - Create a comprehensive `README.md`
   - Include installation instructions
   - Include usage instructions with example commands
   - Show how to run training and inference

## Advanced Usage

### Batch Analysis

Analyze multiple repositories:

```bash
for repo in repos/*/; do
    echo "Analyzing $repo"
    replicode "$repo" --json-out "results/$(basename $repo).json"
done
```

### Comparison Script

Compare scores across repositories:

```python
import json
import glob

results = []
for json_file in glob.glob('results/*.json'):
    with open(json_file) as f:
        data = json.load(f)
        results.append({
            'repo': json_file,
            'score': data['scores']['overall_repro_readiness']
        })

results.sort(key=lambda x: x['score'], reverse=True)

print("Top repositories by reproducibility:")
for r in results[:10]:
    print(f"{r['score']:.0%} - {r['repo']}")
```
