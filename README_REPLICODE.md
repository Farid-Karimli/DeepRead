# RepliCode

A command-line tool to score the **reproducibility readiness** of machine learning code repositories.

## Overview

RepliCode analyzes ML repositories and provides a reproducibility score based on:

- ✅ **Training Code**: Presence of training scripts with key ML constructs
- ✅ **Inference Code**: Demo/inference scripts for running the model
- ✅ **Configuration**: Config files and argument parsing
- ✅ **Environment**: Dependency specifications (requirements.txt, etc.)
- ✅ **Documentation**: README with installation and usage instructions

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Install the package
pip install -e .
```

## Usage

### Basic Usage

```bash
# Analyze a repository
replicode /path/to/repo

# Or use as a Python module
python -m replicode.cli /path/to/repo
```

### Save JSON Output

```bash
replicode /path/to/repo --json-out results.json
```

### Disable Colors

```bash
replicode /path/to/repo --no-color
```

## Example Output

### Console Output

```
======================================================================
RepliCode - ML Repository Reproducibility Analysis
======================================================================

Repository: /path/to/ml-repo

✅ Overall Reproducibility Readiness: 85%

Detailed Scores:
----------------------------------------------------------------------
✅ Training Code......................... 100%
✅ Inference/Demo Code................... 70%
✅ Configuration & Arguments............. 100%
✅ Environment Specification............. 100%
⚠️  Documentation........................ 60%

Analysis Details:
----------------------------------------------------------------------

Training Code:
  • Found 2 training script(s): train.py, src/trainer.py
  • Training code contains key constructs: optimizer, loss, epoch

Inference/Demo Code:
  • Found 1 inference/demo script(s): inference.py

...
```

### JSON Output

```json
{
  "repo_path": "/path/to/ml-repo",
  "scores": {
    "training_code": 1.0,
    "inference_code": 0.7,
    "config_and_args": 1.0,
    "environment_spec": 1.0,
    "documentation": 0.6,
    "overall_repro_readiness": 0.86
  },
  "flags": [
    "[documentation] README lacks concrete usage examples"
  ]
}
```

## Scoring Criteria

### Training Code (0.0 - 1.0)
- **1.0**: Training scripts found with 3+ key constructs (optimizer, loss, dataloader, etc.)
- **0.75**: Training scripts with some constructs
- **0.5**: Training scripts found but lacking key constructs
- **0.0**: No training scripts

### Inference Code (0.0 - 1.0)
- **1.0**: Inference scripts with model loading/prediction logic
- **0.7**: Inference scripts found
- **0.0**: No inference scripts

### Configuration & Arguments (0.0 - 1.0)
- **1.0**: Both config files and argument parsing present
- **0.5**: Either config files or argument parsing present
- **0.0**: Neither present

### Environment Specification (0.0 - 1.0)
- Weighted sum based on files found:
  - requirements.txt: 0.4
  - environment.yml: 0.4
  - pyproject.toml: 0.3
  - setup.py: 0.3
  - Others: 0.2

### Documentation (0.0 - 1.0)
- **0.3**: README exists
- **+0.2**: Contains installation instructions
- **+0.2**: Contains usage instructions
- **+0.1**: Mentions training
- **+0.2**: Includes example commands

## Exit Codes

- **0**: Good score (≥ 0.6)
- **1**: Low score (0.3 - 0.6)
- **2**: Very low score (< 0.3)

## Development

```bash
# Install in development mode
pip install -e .

# Run from source
python -m replicode.cli /path/to/repo
```

## License

MIT
