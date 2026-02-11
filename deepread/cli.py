"""
Command-line interface for replicode.
"""

import argparse
import sys
from pathlib import Path

from .analyzers import analyze_repository
from .report import print_console_report, save_json_report


def main():
    """
    Main entry point for the CLI.
    """
    parser = argparse.ArgumentParser(
        description='Score the reproducibility readiness of ML code repositories',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  replicode /path/to/repo
  replicode /path/to/repo --json-out results.json
  replicode /path/to/repo --no-color
  python -m replicode.cli /path/to/repo
        """
    )

    parser.add_argument(
        'repo_path',
        type=str,
        help='Path to the repository to analyze'
    )

    parser.add_argument(
        '--json-out',
        type=str,
        metavar='PATH',
        help='Save JSON output to the specified file'
    )

    parser.add_argument(
        '--no-color',
        action='store_true',
        help='Disable colored terminal output'
    )

    parser.add_argument(
        '--version',
        action='version',
        version='replicode 0.1.0'
    )

    args = parser.parse_args()

    # Validate repository path
    repo_path = Path(args.repo_path)
    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {args.repo_path}", file=sys.stderr)
        sys.exit(1)

    if not repo_path.is_dir():
        print(f"Error: Path is not a directory: {args.repo_path}", file=sys.stderr)
        sys.exit(1)

    try:
        # Run analysis
        print(f"Analyzing repository: {args.repo_path}")
        print()

        results = analyze_repository(str(repo_path))

        # Print console report
        use_color = not args.no_color
        print_console_report(results, use_color=use_color)

        # Save JSON if requested
        if args.json_out:
            save_json_report(results, args.json_out)

        # Exit with status based on overall score
        overall_score = results['scores']['overall_repro_readiness']
        if overall_score < 0.3:
            sys.exit(2)  # Very low score
        elif overall_score < 0.6:
            sys.exit(1)  # Low score

        sys.exit(0)  # Good score

    except Exception as e:
        print(f"Error during analysis: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
