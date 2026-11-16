"""Command line interface: one fresh browser session per invocation."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from job_platforms.providers.tw104 import AuthConfig, FreshBrowserSession, Resume104Client


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="job-platform")
    parser.add_argument("--provider", default="tw104", choices=["tw104"],
                        help="Implemented job platform provider")
    parser.add_argument("--headless", action="store_true",
                        help="Unsupported by some 104 anti-bot checks")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("probe", help="Authentication and resume count; no personal values")
    sub.add_parser("list", help="Print private resume summaries as JSON")
    get = sub.add_parser("get", help="Print a private resume as JSON")
    get.add_argument("resume_id")
    schema = sub.add_parser("schema", help="Print the nested field schema")
    schema.add_argument("resume_id")
    create = sub.add_parser("create", help="Create exactly one real resume")
    create.add_argument("--confirm", choices=["create-one"], required=True)
    plan = sub.add_parser("plan", help="Validate multi-field edits without saving")
    plan.add_argument("resume_id")
    plan.add_argument("--patch-file", required=True)
    apply_cmd = sub.add_parser("apply", help="Explicitly write supported BIO fields (experimental)")
    apply_cmd.add_argument("resume_id")
    apply_cmd.add_argument("--patch-file", required=True)
    apply_cmd.add_argument("--if-match", required=True,
                           help="resumeTimestamp from a prior GET, used as precondition")
    apply_cmd.add_argument("--confirm", required=True,
                           choices=["experimental-bio-write"])
    return parser


async def _run(args):
    cfg = AuthConfig.from_env()
    cfg.headless = args.headless
    async with FreshBrowserSession(cfg) as session:
        client = Resume104Client(session.page)
        if args.command == "probe":
            result = {"authenticated": True,
                      "resume_count": len(await client.list_resumes())}
        elif args.command == "list":
            result = await client.list_resumes()
        elif args.command == "get":
            result = await client.get_resume(args.resume_id)
        elif args.command == "schema":
            result = await client.get_schema(args.resume_id)
        elif args.command == "create":
            result = await client.create_resume()
        elif args.command in ("plan", "apply"):
            operations = json.loads(Path(args.patch_file).read_text(encoding="utf-8"))
            plan, _ = await client.plan_edit(args.resume_id, operations)
            if args.command == "plan":
                result = {
                    "resume_id": plan.resume_id,
                    "base_timestamp": plan.base_timestamp,
                    "operations": [{"op": op.op, "path": op.path}
                                   for op in plan.operations],
                    "persisted": False,
                }
            else:
                from job_platforms.core.errors import ConflictError
                if str(plan.base_timestamp) != args.if_match.strip('"'):
                    raise ConflictError("Resume has changed since the caller read it")
                result = await client.save_edit(plan)
        else:
            raise ValueError("Unrecognized command")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    args = _parser().parse_args()
    try:
        asyncio.run(_run(args))
    except Exception as exc:
        # Never print exception messages from a browser page: they may contain
        # OAuth query parameters, MFA redirect URLs or user data.
        print(f"job-platform: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
