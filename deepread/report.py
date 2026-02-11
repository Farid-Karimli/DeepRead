"""
Report formatting for console and JSON output.
"""

import json
from typing import Dict, Optional

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


def get_score_color(score: float, use_color: bool = True) -> str:
    """
    Get color code for a score.

    Args:
        score: Score value (0.0-1.0)
        use_color: Whether to use color

    Returns:
        Color name for rich library or empty string
    """
    if not use_color:
        return ""

    if score >= 0.8:
        return "green"
    elif score >= 0.5:
        return "yellow"
    else:
        return "red"


def get_score_emoji(score: float) -> str:
    """
    Get emoji representation for a score.

    Args:
        score: Score value (0.0-1.0)

    Returns:
        Emoji string
    """
    if score >= 0.8:
        return "✅"
    elif score >= 0.5:
        return "⚠️ "
    else:
        return "❌"


def format_score(score: float) -> str:
    """
    Format score as percentage.

    Args:
        score: Score value (0.0-1.0)

    Returns:
        Formatted percentage string
    """
    return f"{score * 100:.0f}%"


def print_console_report(results: Dict, use_color: bool = True):
    """
    Print a human-readable console report.

    Args:
        results: Analysis results dictionary
        use_color: Whether to use colored output
    """
    if RICH_AVAILABLE and use_color:
        print_rich_report(results)
    else:
        print_plain_report(results, use_color=False)


def print_rich_report(results: Dict):
    """
    Print a rich-formatted console report.

    Args:
        results: Analysis results dictionary
    """
    console = Console()

    # Header
    console.print()
    console.print(Panel.fit(
        "[bold cyan]RepliCode - ML Repository Reproducibility Analysis[/bold cyan]",
        border_style="cyan"
    ))
    console.print()

    # Repository path
    console.print(f"[bold]Repository:[/bold] {results['repo_path']}")
    console.print()

    # Overall score
    overall_score = results['scores']['overall_repro_readiness']
    score_color = get_score_color(overall_score)
    emoji = get_score_emoji(overall_score)

    console.print(Panel(
        f"{emoji} [bold {score_color}]{format_score(overall_score)}[/bold {score_color}] "
        f"Overall Reproducibility Readiness",
        border_style=score_color
    ))
    console.print()

    # Detailed scores table
    table = Table(title="Detailed Scores", show_header=True, header_style="bold magenta")
    table.add_column("Category", style="cyan", width=25)
    table.add_column("Score", justify="right", width=10)
    table.add_column("Status", justify="center", width=8)

    categories = [
        ('training_code', 'Training Code'),
        ('inference_code', 'Inference/Demo Code'),
        ('config_and_args', 'Configuration & Arguments'),
        ('environment_spec', 'Environment Specification'),
        ('documentation', 'Documentation'),
    ]

    for key, label in categories:
        score = results['scores'][key]
        color = get_score_color(score)
        emoji = get_score_emoji(score)

        table.add_row(
            label,
            f"[{color}]{format_score(score)}[/{color}]",
            emoji
        )

    console.print(table)
    console.print()

    # Details for each category
    console.print("[bold]Analysis Details:[/bold]")
    console.print()

    for key, label in categories:
        details = results['details'].get(key, [])
        if details:
            console.print(f"[bold cyan]{label}:[/bold cyan]")
            for detail in details:
                # Color the detail based on sentiment
                if any(word in detail.lower() for word in ['no ', 'not ', 'lack', 'missing', 'without']):
                    console.print(f"  [red]• {detail}[/red]")
                elif any(word in detail.lower() for word in ['found', 'contains', 'includes']):
                    console.print(f"  [green]• {detail}[/green]")
                else:
                    console.print(f"  • {detail}")
            console.print()

    # Flags (issues)
    if results['flags']:
        console.print("[bold red]⚠️  Issues Detected:[/bold red]")
        for flag in results['flags']:
            console.print(f"  [red]• {flag}[/red]")
        console.print()


def print_plain_report(results: Dict, use_color: bool = False):
    """
    Print a plain text console report (fallback when rich is not available).

    Args:
        results: Analysis results dictionary
        use_color: Whether to use basic ANSI colors
    """
    # Header
    print()
    print("=" * 70)
    print("RepliCode - ML Repository Reproducibility Analysis")
    print("=" * 70)
    print()

    # Repository path
    print(f"Repository: {results['repo_path']}")
    print()

    # Overall score
    overall_score = results['scores']['overall_repro_readiness']
    emoji = get_score_emoji(overall_score)
    print(f"{emoji} Overall Reproducibility Readiness: {format_score(overall_score)}")
    print()

    # Detailed scores
    print("Detailed Scores:")
    print("-" * 70)

    categories = [
        ('training_code', 'Training Code'),
        ('inference_code', 'Inference/Demo Code'),
        ('config_and_args', 'Configuration & Arguments'),
        ('environment_spec', 'Environment Specification'),
        ('documentation', 'Documentation'),
    ]

    for key, label in categories:
        score = results['scores'][key]
        emoji = get_score_emoji(score)
        print(f"{emoji} {label:.<40} {format_score(score):>6}")

    print()

    # Details
    print("Analysis Details:")
    print("-" * 70)

    for key, label in categories:
        details = results['details'].get(key, [])
        if details:
            print(f"\n{label}:")
            for detail in details:
                print(f"  • {detail}")

    print()

    # Flags
    if results['flags']:
        print("⚠️  Issues Detected:")
        print("-" * 70)
        for flag in results['flags']:
            print(f"  • {flag}")
        print()


def save_json_report(results: Dict, output_path: str):
    """
    Save results as JSON file.

    Args:
        results: Analysis results dictionary
        output_path: Path to save JSON file
    """
    # Create a clean version for JSON output (without details)
    json_output = {
        'repo_path': results['repo_path'],
        'scores': results['scores'],
        'flags': results['flags']
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(json_output, f, indent=2, ensure_ascii=False)

    print(f"JSON report saved to: {output_path}")
