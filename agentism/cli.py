"""CLI parsing and startup plan helpers."""
import argparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agentism - platform dev agent")
    parser.add_argument("--session", metavar="NAME", default="main",
                        help="Named conversation thread to start in / resume (default: main)")
    parser.add_argument("--issue", metavar="REF",
                        help="Kick off with a GitHub issue (owner/repo#N or full URL)")
    parser.add_argument("--issues", metavar="OWNER/REPO",
                        help="Batch-process all open issues in a repo matching --label")
    parser.add_argument("--label", metavar="LABEL", default="agent-ready",
                        help="Issue label filter for --issues (default: agent-ready)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview writes/commits without making real changes")
    parser.add_argument("--debug", action="store_true",
                        help="Print raw LangGraph chunk keys each turn for debugging")
    parser.add_argument("--chunk-timeout", metavar="SECS", type=float, default=1200.0,
                        help="Seconds to wait for each model chunk before giving up (default: 1200)")
    return parser.parse_args()


def startup_plan(args: argparse.Namespace, issue_prompt_fn):
    """Return (initial_prompt, batch_issues) derived from parsed CLI args."""
    initial_prompt = ""
    batch_issues = None

    if args.issues:
        batch_issues = [
            f"Fetch all open issues in {args.issues} with label '{args.label}' "
            "using the MCP list_issues tool, then process each one following the "
            "issue-driven workflow."
        ]
    elif args.issue:
        initial_prompt = issue_prompt_fn(args.issue)

    return initial_prompt, batch_issues

