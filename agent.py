"""Thin entrypoint that wires CLI parsing to app orchestration."""

import asyncio

import config
from app import main_async
from cli import parse_args, startup_plan
from prompts import issue_ref_to_prompt


def main() -> None:
    args = parse_args()
    if args.dry_run:
        config.DRY_RUN = True

    initial_prompt, batch_issues = startup_plan(args, issue_ref_to_prompt)

    asyncio.run(main_async(
        initial_prompt=initial_prompt,
        initial_thread=args.session,
        batch_issues=batch_issues,
        debug=args.debug,
        chunk_timeout=args.chunk_timeout,
    ))


if __name__ == "__main__":
    main()

