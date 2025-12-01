"""
Analysis functions for scoring repository reproducibility readiness.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

from .utils import (
    find_files_by_pattern,
    find_files_by_name,
    search_file_content,
    search_regex_in_file,
    get_all_python_files,
    read_file_safely,
)


def analyze_training_code(repo_path: str) -> Tuple[float, List[str]]:
    """
    Analyze the presence and quality of training code.

    Returns:
        (score, flags) where score is 0.0-1.0 and flags are messages
    """
    flags = []
    score = 0.0

    # Look for training scripts
    training_file_patterns = [
        'train.py', 'train_*.py', 'trainer.py', 'training.py',
        '**/train.py', '**/train_*.py', '**/trainer.py'
    ]

    training_files = []
    for pattern in training_file_patterns:
        found = find_files_by_pattern(repo_path, [pattern])
        training_files.extend(found)

    # Remove duplicates
    training_files = list(set(training_files))

    if not training_files:
        flags.append("No training script found (e.g., train.py, trainer.py)")
        return 0.0, flags

    # Found training files - give partial score
    score = 0.5
    flags.append(f"Found {len(training_files)} training script(s): {', '.join(training_files[:3])}")

    # Check for training-related keywords in these files
    training_keywords = [
        'optimizer', 'loss', 'backward', 'backprop',
        'train_loader', 'dataloader', 'epoch', 'gradient',
        'torch.optim', 'tf.train', 'model.fit', 'train_step'
    ]

    keywords_found = set()
    for train_file in training_files[:5]:  # Check up to 5 files
        full_path = os.path.join(repo_path, train_file)
        found = search_file_content(full_path, training_keywords, case_sensitive=False)
        keywords_found.update(found)

    if len(keywords_found) >= 3:
        score = 1.0
        flags.append(f"Training code contains key constructs: {', '.join(list(keywords_found)[:5])}")
    elif len(keywords_found) >= 1:
        score = 0.75
        flags.append(f"Training code has some training constructs: {', '.join(keywords_found)}")
    else:
        flags.append("Training scripts found but lack common training constructs")

    return score, flags


def analyze_inference_code(repo_path: str) -> Tuple[float, List[str]]:
    """
    Analyze the presence of inference/demo code.

    Returns:
        (score, flags) where score is 0.0-1.0 and flags are messages
    """
    flags = []

    # Look for inference/demo scripts
    inference_patterns = [
        'inference.py', 'infer.py', 'predict.py', 'demo.py',
        'sample.py', 'generate.py', 'eval.py', 'evaluate.py',
        '**/inference.py', '**/predict.py', '**/demo.py'
    ]

    inference_files = []
    for pattern in inference_patterns:
        found = find_files_by_pattern(repo_path, [pattern])
        inference_files.extend(found)

    inference_files = list(set(inference_files))

    if not inference_files:
        flags.append("No inference/demo script found")
        return 0.0, flags

    score = 0.7
    flags.append(f"Found {len(inference_files)} inference/demo script(s): {', '.join(inference_files[:3])}")

    # Check for model loading keywords
    inference_keywords = ['load_model', 'torch.load', 'model.load', 'predict', 'inference']

    keywords_found = set()
    for inf_file in inference_files[:3]:
        full_path = os.path.join(repo_path, inf_file)
        found = search_file_content(full_path, inference_keywords, case_sensitive=False)
        keywords_found.update(found)

    if len(keywords_found) >= 2:
        score = 1.0
        flags.append("Inference code contains model loading/prediction logic")

    return score, flags


def analyze_config_and_args(repo_path: str) -> Tuple[float, List[str]]:
    """
    Analyze configuration files and argument parsing.

    Returns:
        (score, flags) where score is 0.0-1.0 and flags are messages
    """
    flags = []
    score = 0.0

    # Check for config files
    config_patterns = ['*.yaml', '*.yml', '*.json']
    config_files = []

    for pattern in config_patterns:
        found = find_files_by_pattern(repo_path, [pattern])
        # Filter for likely config files (in configs/ or root, not package.json etc.)
        for f in found:
            if ('config' in f.lower() or
                f.startswith('configs/') or
                f.count('/') == 0 or
                f.endswith('.yml') or f.endswith('.yaml')):
                config_files.append(f)

    config_files = list(set(config_files))

    has_config_files = len(config_files) > 0
    if has_config_files:
        score += 0.5
        flags.append(f"Found {len(config_files)} configuration file(s)")

    # Check for argument parsing in Python files
    python_files = get_all_python_files(repo_path)
    argparse_patterns = [
        r'argparse\.ArgumentParser',
        r'import\s+argparse',
        r'from\s+argparse',
        r'import\s+click',
        r'@click\.',
        r'fire\.Fire',
        r'import\s+fire',
    ]

    has_argparse = False
    for py_file in python_files[:20]:  # Check first 20 Python files
        full_path = os.path.join(repo_path, py_file)
        if search_regex_in_file(full_path, argparse_patterns):
            has_argparse = True
            break

    if has_argparse:
        score += 0.5
        flags.append("Scripts use argument parsing (argparse/click/fire)")
    else:
        flags.append("No argument parsing detected in main scripts")

    if score == 0:
        flags.append("No configuration files or argument parsing found")

    return score, flags


def analyze_environment_spec(repo_path: str) -> Tuple[float, List[str]]:
    """
    Analyze environment specification files.

    Returns:
        (score, flags) where score is 0.0-1.0 and flags are messages
    """
    flags = []
    score = 0.0

    env_files = {
        'requirements.txt': 0.4,
        'environment.yml': 0.4,
        'environment.yaml': 0.4,
        'pyproject.toml': 0.3,
        'setup.py': 0.3,
        'setup.cfg': 0.2,
        'Pipfile': 0.3,
        'poetry.lock': 0.2,
        'conda.yml': 0.4,
        'conda.yaml': 0.4,
    }

    found_files = []
    for env_file, weight in env_files.items():
        file_path = os.path.join(repo_path, env_file)
        if os.path.isfile(file_path):
            found_files.append(env_file)
            score += weight

    # Cap at 1.0
    score = min(score, 1.0)

    if found_files:
        flags.append(f"Environment specification found: {', '.join(found_files)}")
    else:
        flags.append("No environment specification file found (requirements.txt, environment.yml, etc.)")

    return score, flags


def analyze_documentation(repo_path: str) -> Tuple[float, List[str]]:
    """
    Analyze documentation quality, especially README.

    Returns:
        (score, flags) where score is 0.0-1.0 and flags are messages
    """
    flags = []
    score = 0.0

    # Look for README
    readme_patterns = ['README.md', 'README.rst', 'README.txt', 'README', 'readme.md']
    readme_files = find_files_by_name(repo_path, readme_patterns)

    if not readme_files:
        flags.append("No README file found")
        return 0.0, flags

    score = 0.3
    readme_path = os.path.join(repo_path, readme_files[0])
    flags.append(f"README found: {readme_files[0]}")

    # Read README content
    readme_content = read_file_safely(readme_path, max_size_mb=5)
    if not readme_content:
        return score, flags

    readme_lower = readme_content.lower()

    # Check for important sections
    has_installation = any(keyword in readme_lower for keyword in
                          ['## installation', '# installation', 'install', 'setup', 'requirements'])
    has_usage = any(keyword in readme_lower for keyword in
                   ['## usage', '# usage', 'how to use', 'getting started', 'quickstart'])
    has_training = any(keyword in readme_lower for keyword in
                      ['train', 'training', 'train.py', 'python train'])

    if has_installation:
        score += 0.2
        flags.append("README contains installation instructions")

    if has_usage:
        score += 0.2
        flags.append("README contains usage instructions")

    if has_training:
        score += 0.1
        flags.append("README mentions training")

    # Check for example commands (lines starting with $ or containing python/bash commands)
    command_patterns = [
        r'^\s*\$\s+python',
        r'^\s*python\s+\w+\.py',
        r'```bash\n.*python',
        r'```shell\n.*python',
        r'^\s*\$\s+bash',
    ]

    has_example_command = False
    for pattern in command_patterns:
        if re.search(pattern, readme_content, re.MULTILINE | re.IGNORECASE):
            has_example_command = True
            break

    if has_example_command:
        score += 0.2
        flags.append("README includes example commands")
    else:
        flags.append("README lacks concrete usage examples")

    return min(score, 1.0), flags


def analyze_repository(repo_path: str) -> Dict:
    """
    Run all analyses on the repository.

    Args:
        repo_path: Path to the repository

    Returns:
        Dictionary containing scores, flags, and metadata
    """
    if not os.path.isdir(repo_path):
        raise ValueError(f"Repository path does not exist: {repo_path}")

    results = {
        'repo_path': os.path.abspath(repo_path),
        'scores': {},
        'flags': [],
        'details': {}
    }

    # Run all analyzers
    analyzers = [
        ('training_code', analyze_training_code),
        ('inference_code', analyze_inference_code),
        ('config_and_args', analyze_config_and_args),
        ('environment_spec', analyze_environment_spec),
        ('documentation', analyze_documentation),
    ]

    all_flags = []
    for name, analyzer_func in analyzers:
        score, flags = analyzer_func(repo_path)
        results['scores'][name] = round(score, 2)
        results['details'][name] = flags
        all_flags.extend([f"[{name}] {flag}" for flag in flags])

    # Calculate overall score
    scores = results['scores'].values()
    overall_score = sum(scores) / len(scores) if scores else 0.0
    results['scores']['overall_repro_readiness'] = round(overall_score, 2)

    # Collect top-level flags (issues/concerns)
    results['flags'] = [flag for flag in all_flags if any(
        keyword in flag.lower() for keyword in ['no ', 'not ', 'lack', 'missing', 'without']
    )]

    return results
