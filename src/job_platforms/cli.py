"""Command line interface: one fresh browser session per invocation."""
from __future__ import annotations

import argparse
import mimetypes
import os
import asyncio
import json
import sys
from pathlib import Path

from job_platforms.providers.tw104 import AuthConfig, FreshBrowserSession, Resume104Client
from job_platforms.providers.tw104.custom_themes import custom_theme_capabilities
from job_platforms.providers.tw104.writers import (
    checked_write_paths, changed_sections, patch_path_catalog,
)
from job_platforms.providers.tw104.custom_text_contract import (
    custom_text_create_body, custom_text_update_body, custom_delete_body,
)
from job_platforms.providers.tw104.certificate_connection_contract import (
    certificate_connect_plan, certificate_disconnect_plan,
    certificate_other_text_disconnect_plan,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="job-platform")
    parser.add_argument("--provider", default="tw104", choices=["tw104"],
                        help="Implemented job platform provider")
    parser.add_argument("--headless", action="store_true",
                        help="Unsupported by some 104 anti-bot checks")
    parser.add_argument(
        "--transport", choices=("browser", "curl_cffi", "curl_cffi_detached"),
        default=os.getenv("JOB_PLATFORM_104_TRANSPORT", "browser"),
        help="104 API backend; curl_cffi reuses browser login cookies and proxy",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    cert_plan = sub.add_parser(
        "certificate-link-plan",
        help="Offline 104 certification association request planning; no write",
    )
    cert_plan.add_argument(
        "action", choices=["connect", "disconnect", "disconnect-other"],
    )
    cert_plan.add_argument("--ids-file", default=None)
    cert_plan.add_argument("--record-id", type=int, default=None)
    layout = sub.add_parser(
        "custom-layout",
        help="104 CLASSIC/BANNER single no-media CUSTOM slot CRUD (experimental)",
    )
    layout.add_argument("resume_id")
    layout.add_argument("action", choices=["create", "update", "delete"])
    layout.add_argument("--slot", type=int, required=True)
    layout.add_argument("--theme", type=int, choices=[1, 2], default=None,
                        help="Required for create; existing theme retained on update")
    layout.add_argument("--name", default=None)
    layout.add_argument("--content-file", default=None,
                        help="Private JSON with full no-media content; required for create")
    layout.add_argument("--if-match", required=True)
    layout.add_argument("--confirm", choices=["experimental-custom-layout-write"],
                        required=True)
    custom_write = sub.add_parser(
        "custom-text",
        help="104 native CUSTOM TEXT=3 create/update/delete with read-back",
    )
    custom_write.add_argument("resume_id")
    custom_write.add_argument("action", choices=["create","update","delete"])
    custom_write.add_argument("--slot",type=int,required=True)
    custom_write.add_argument("--name",default=None)
    custom_write.add_argument("--html-file",default=None)
    custom_write.add_argument("--if-match",required=True)
    custom_write.add_argument(
        "--confirm",choices=["experimental-custom-write"],required=True,
    )
    custom_plan = sub.add_parser(
        "custom-text-plan",
        help="Offline source-mapped CUSTOM TEXT=3 request planning; never sends a write",
    )
    custom_plan.add_argument("action", choices=["create", "update", "delete"])
    custom_plan.add_argument("--slot", type=int, required=True)
    custom_plan.add_argument("--name", default=None)
    custom_plan.add_argument("--html-file", default=None)
    custom_plan.add_argument("--options-file", default=None)
    custom_plan.add_argument("--existing-form-file", default=None)
    sub.add_parser(
        "custom-themes",
        help="Offline CUSTOM theme/editor content slot capacities and writer evidence",
    )
    sub.add_parser(
        "writable-paths",
        help="Offline list of source-mapped JSON Patch replacement paths; no login",
    )
    sub.add_parser("probe", help="Authentication and resume count; no personal values")
    sub.add_parser("list", help="Print private resume summaries as JSON")
    get = sub.add_parser("get", help="Print a private resume as JSON")
    get.add_argument("resume_id")
    schema = sub.add_parser("schema", help="Print the nested field schema")
    schema.add_argument("resume_id")
    custom_slots = sub.add_parser(
        "custom-slots",
        help="Inspect discovered native custom1..custom6 schema without writing",
    )
    custom_slots.add_argument("resume_id")
    editor_limits = sub.add_parser(
        "editor-limits",
        help="Read current site numeric/bool limits for one native 104 section",
    )
    from job_platforms.providers.tw104.editor_limits import INPUT_FIELD_GROUPS
    editor_limits.add_argument("section", choices=tuple(INPUT_FIELD_GROUPS))
    language_choices = sub.add_parser(
        "language-options",
        help="Read current 104 foreign/local language choices and capacity; no write",
    )
    language_choices.add_argument("resume_id")
    language_choices.add_argument("kind", choices=["foreign", "local"])
    section = sub.add_parser("get-section", help="Read one native resume section")
    section.add_argument("resume_id")
    section.add_argument("section", choices=Resume104Client.SECTIONS)
    create = sub.add_parser("create", help="Create exactly one real resume")
    create.add_argument("--confirm", choices=["create-one"], required=True)
    plan = sub.add_parser("plan", help="Validate multi-field edits without saving")
    plan.add_argument("resume_id")
    plan.add_argument("--patch-file", required=True)
    batch_plan = sub.add_parser(
        "batch-plan", help="Read-only current-site preflight for first batch step",
    )
    batch_plan.add_argument("resume_id")
    batch_plan.add_argument("--steps-file", required=True,
                            help="Private JSON list of ordered supported operations")
    batch_plan.add_argument("--if-match", required=True,
                            help="resumeTimestamp from prior GET; no write")
    batch = sub.add_parser(
        "batch", help="Sequential 104 record/PATCH/theme/sort writes (non-atomic)",
    )
    batch.add_argument("resume_id")
    batch.add_argument("--steps-file", required=True,
                       help="Private JSON list of ordered supported operations")
    batch.add_argument("--if-match", required=True,
                       help="resumeTimestamp from prior GET")
    batch.add_argument("--confirm", choices=["experimental-nonatomic-batch"],
                       required=True)
    apply_cmd = sub.add_parser("apply", help="Explicitly write supported 104 sections (experimental)")
    apply_cmd.add_argument("resume_id")
    apply_cmd.add_argument("--patch-file", required=True)
    apply_cmd.add_argument("--if-match", required=True,
                           help="resumeTimestamp from a prior GET, used as precondition")
    apply_cmd.add_argument("--confirm", required=True,
                           choices=["experimental-bio-write", "experimental-section-write"],
                           help="Explicitly acknowledge unverified section writers")
    certificate_block = sub.add_parser(
        "certificate-block",
        help="Initialize or clear resume-owned CERTIFICATE text (experimental)"
    )
    certificate_block.add_argument("resume_id")
    certificate_block.add_argument("action", choices=["initialize", "clear"])
    certificate_block.add_argument("--others-file", default=None)
    certificate_block.add_argument("--if-match", required=True)
    certificate_block.add_argument(
        "--confirm", choices=["experimental-certificate-write"], required=True,
    )
    under18_action = sub.add_parser(
        "under18",
        help="104 native age/identity data POST or PUT (EXPERIMENTAL; sensitive)",
    )
    under18_action.add_argument("resume_id")
    under18_action.add_argument("action", choices=["create", "update"])
    under18_action.add_argument("--changes-file", required=True,
        help="Locally protected JSON with all 3 identity fields (never print/commit)")
    under18_action.add_argument("--if-match", required=True)
    under18_action.add_argument("--acknowledge-identity-write", action="store_true",
        help="Explicit confirmation to submit sensitive age/identity data")
    under18_action.add_argument(
        "--confirm", choices=["experimental-under18-write"], required=True,
    )
    bio_action = sub.add_parser(
        "bio-action", help="104 initial BIO POST or clear/delete (experimental)"
    )
    bio_action.add_argument("resume_id")
    bio_action.add_argument("action", choices=["create", "clear"])
    bio_action.add_argument("--changes-file", default=None,
                            help="Private JSON chi/eng values for create only")
    bio_action.add_argument("--if-match", required=True)
    bio_action.add_argument("--confirm", choices=["experimental-bio-action-write"],
                            required=True)
    record = sub.add_parser(
        "record", help="104-native record CRUD (experimental; not live write verified)"
    )
    record.add_argument("resume_id")
    record.add_argument("section", choices=["skill", "education", "experience", "language", "referrer", "project", "portfolio"])
    record.add_argument("action", choices=["create", "update", "delete"])
    record.add_argument("--kind", choices=["local", "foreign"], default=None,
                        help="Required only for LANGUAGE records")
    record.add_argument("--position", type=int, default=None,
                        help="Current 1-based sort number for update/delete")
    record.add_argument("--changes-file", default=None,
                        help="Private JSON object for create/update; never commit")
    record.add_argument("--if-match", required=True, help="Prior 104 resumeTimestamp")
    record.add_argument("--confirm", choices=["experimental-record-write"], required=True)
    theme = sub.add_parser("theme", help="104 LAYOUT section theme (experimental)")
    theme.add_argument("resume_id")
    theme.add_argument("section", choices=[
        "info", "education", "experience", "jobCondition", "skill",
        "certificate", "language", "project", "portfolio", "referrer", "custom",
    ])
    theme.add_argument("selected_theme", type=int)
    theme.add_argument("--if-match", required=True)
    theme.add_argument("--confirm", choices=["experimental-theme-write"], required=True)
    portfolio_status = sub.add_parser(
        "portfolio-conversion",
        help="Read a PORTFOLIO file conversion status; no write or signed URLs",
    )
    portfolio_status.add_argument("resume_id")
    portfolio_status.add_argument("--position",type=int,required=True)
    portfolio_file = sub.add_parser(
        "portfolio-file", help="104 PORTFOLIO binary file upload (EXPERIMENTAL)"
    )
    portfolio_file.add_argument("resume_id")
    portfolio_file.add_argument("--file", required=True, help="Local PDF/JPEG/PNG, <=5 MiB")
    portfolio_file.add_argument("--name", required=True, help="Portfolio item title")
    portfolio_file.add_argument("--attach-name", default=None,
                                help="Attachment display name; defaults to file name")
    portfolio_file.add_argument("--if-match", required=True)
    portfolio_file.add_argument("--confirm",
                                choices=["experimental-file-upload"], required=True)
    ordering = sub.add_parser("sort", help="104 adjacent record move (experimental)")
    ordering.add_argument("resume_id")
    ordering.add_argument("section", choices=["education", "skill", "language", "project", "portfolio", "referrer"])
    ordering.add_argument("--kind", choices=["local", "foreign"], default=None,
                          help="Required only for LANGUAGE record sorting")
    ordering.add_argument("from_position", type=int)
    ordering.add_argument("to_position", type=int)
    ordering.add_argument("--if-match", required=True)
    ordering.add_argument("--confirm", choices=["experimental-sort-write"], required=True)
    return parser


async def _run(args):
    if args.command == "certificate-link-plan":
        if args.action == "connect":
            if args.ids_file is None or args.record_id is not None:
                raise ValueError("Connect requires --ids-file only")
            ids = json.loads(Path(args.ids_file).read_text(encoding="utf-8"))
            operation = certificate_connect_plan(ids)
        elif args.action == "disconnect":
            if args.record_id is None or args.ids_file is not None:
                raise ValueError("Disconnect requires --record-id only")
            operation = certificate_disconnect_plan(args.record_id)
        else:
            if args.record_id is not None or args.ids_file is not None:
                raise ValueError("Disconnect-other takes no identifier")
            operation = certificate_other_text_disconnect_plan()
        print(json.dumps({
            "section": "certificate", "operation": args.action,
            "persisted": False, "network_sent": False,
            **operation,
        }, ensure_ascii=False, indent=2))
        return
    if args.command == "custom-themes":
        print(json.dumps(custom_theme_capabilities(), ensure_ascii=False, indent=2))
        return
    if args.command == "writable-paths":
        print(json.dumps(
            patch_path_catalog(),
            ensure_ascii=False, indent=2,
        ))
        return
    if args.command == "custom-text-plan":
        # Deliberately offline. No login/session/remote write or state persists.
        name, html, options, existing = (
            args.name, args.html_file, args.options_file,
            args.existing_form_file,
        )
        if args.action == "create":
            if not name or not html or not options or existing is not None:
                raise ValueError("CUSTOM create requires name, html, options only")
            body = custom_text_create_body(
                slot=args.slot, name=name,
                introduction_html=Path(html).read_text(encoding="utf-8"),
                theme_options=json.loads(Path(options).read_text(encoding="utf-8")),
            )
        elif args.action == "update":
            if not existing or options is not None or (name is None and html is None):
                raise ValueError("CUSTOM update needs prior native form and changed fields")
            form = json.loads(Path(existing).read_text(encoding="utf-8"))
            if (
                not isinstance(form, dict)
                or not isinstance(form.get("custom"), dict)
                or form["custom"].get("sort") != args.slot
            ):
                raise ValueError("CUSTOM form slot does not match requested target")
            body = custom_text_update_body(
                form, name=name,
                introduction_html=(
                    Path(html).read_text(encoding="utf-8")
                    if html is not None else None
                ),
            )
        else:
            if name is not None or html is not None or options is not None or existing is not None:
                raise ValueError("CUSTOM delete only accepts slot")
            body = custom_delete_body(slot=args.slot)
        print(json.dumps({
            "section": "custom", "action": args.action,
            "slot": args.slot, "persisted": False,
            "network_sent": False, "verified_against_live_get": False,
            "body": body,
        }, ensure_ascii=False, indent=2))
        return
    upload_file = None
    if args.command == "portfolio-file":
        from job_platforms.providers.tw104.transport import (
            BrowserUpload, MAX_BROWSER_UPLOAD_BYTES,
        )
        src = Path(args.file)
        if not src.is_file() or not 8 <= src.stat().st_size <= MAX_BROWSER_UPLOAD_BYTES:
            raise ValueError("Local portfolio file missing or exceeds the 5 MiB limit")
        kind = mimetypes.guess_type(src.name)[0]
        upload_file = BrowserUpload(
            "attachment", src.name, kind or "", src.read_bytes(),
        )
        upload_file.validate()
    cfg = AuthConfig.from_env()
    cfg.headless = args.headless
    async with FreshBrowserSession(cfg) as session:
        if args.transport == "browser":
            client = Resume104Client(session.page)
        else:
            client = await session.resume_client(
                transport=args.transport,
                allow_http_writes=(
                    os.getenv("JOB_PLATFORM_104_CFFI_ENABLE_WRITES") == "1"
                ),
            )
        if args.command == "probe":
            result = {"authenticated": True,
                      "resume_count": len(await client.list_resumes())}
        elif args.command == "list":
            result = await client.list_resumes()
        elif args.command == "get":
            result = await client.get_resume(args.resume_id)
        elif args.command == "schema":
            result = await client.get_schema(args.resume_id)
        elif args.command == "custom-slots":
            result = await client.list_custom_slots(args.resume_id)
        elif args.command == "get-section":
            result = await client.get_section(args.resume_id, args.section)
        elif args.command == "editor-limits":
            result = await client.get_editor_limits(args.section)
        elif args.command == "language-options":
            result = await client.get_language_editor_options(
                args.resume_id, args.kind,
            )
        elif args.command == "create":
            result = await client.create_resume()
        elif args.command == "custom-layout":
            if args.action == "create":
                if args.theme is None or args.name is None or args.content_file is None:
                    raise ValueError("CUSTOM layout create requires theme/name/content")
            elif args.action == "update":
                if args.theme is not None or (args.name is None and args.content_file is None):
                    raise ValueError("CUSTOM layout update retains theme and needs changes")
            else:
                if any(x is not None for x in (
                    args.theme, args.name, args.content_file,
                )):
                    raise ValueError("CUSTOM layout delete accepts no changed fields")
            contents = (
                json.loads(Path(args.content_file).read_text(encoding="utf-8"))
                if args.content_file is not None else None
            )
            result = await client.mutate_custom_layout(
                args.resume_id, args.action, slot=args.slot,
                expected_timestamp=args.if_match.strip('"'),
                theme=args.theme, name=args.name, content=contents,
            )
        elif args.command == "custom-text":
            if args.action == "create" and (
                not args.name or not args.html_file
            ):
                raise ValueError("CUSTOM create requires --name and --html-file")
            if args.action == "update" and (
                args.name is None and args.html_file is None
            ):
                raise ValueError("CUSTOM update needs name or HTML")
            if args.action == "delete" and (
                args.name is not None or args.html_file is not None
            ):
                raise ValueError("CUSTOM delete accepts no changed fields")
            result = await client.mutate_custom_text(
                args.resume_id,args.action,slot=args.slot,
                expected_timestamp=args.if_match.strip('"'),
                name=args.name,
                introduction_html=(
                    Path(args.html_file).read_text(encoding="utf-8")
                    if args.html_file is not None else None
                ),
            )
        elif args.command == "batch-plan":
            steps = json.loads(Path(args.steps_file).read_text(encoding="utf-8"))
            result = await client.plan_batch(
                args.resume_id, steps,
                expected_timestamp=args.if_match.strip('"'),
            )
        elif args.command == "batch":
            steps = json.loads(Path(args.steps_file).read_text(encoding="utf-8"))
            result = await client.apply_batch(
                args.resume_id, steps,
                expected_timestamp=args.if_match.strip('"'),
            )
        elif args.command == "under18":
            if not args.acknowledge_identity_write:
                raise ValueError("Sensitive UNDER18 write needs --acknowledge-identity-write")
            changes = json.loads(Path(args.changes_file).read_text(encoding="utf-8"))
            result = await client.mutate_under18(
                args.resume_id, args.action, changes=changes,
                expected_timestamp=args.if_match.strip('"'),
                acknowledge_identity_write=True,
            )
        elif args.command == "certificate-block":
            if (args.action == "initialize") != (args.others_file is not None):
                raise ValueError("--others-file required only for initialize")
            others = (
                Path(args.others_file).read_text(encoding="utf-8")
                if args.others_file is not None else None
            )
            result = await client.mutate_certificate_block(
                args.resume_id, args.action, others=others,
                expected_timestamp=args.if_match.strip('"'),
            )
        elif args.command == "bio-action":
            if (args.action == "create") != (args.changes_file is not None):
                raise ValueError("--changes-file is required only for create")
            fields = None
            if args.changes_file is not None:
                fields = json.loads(Path(args.changes_file).read_text(encoding="utf-8"))
                if not isinstance(fields, dict):
                    raise ValueError("BIO create needs a JSON object")
            result = await client.mutate_bio(
                args.resume_id, args.action, changes=fields,
                expected_timestamp=args.if_match.strip('"'),
            )
        elif args.command == "record":
            # Explicit 104-native operation; malformed combinations never
            # become a browser write. No generic multi-provider data model.
            if (args.section == "language") != (args.kind is not None):
                raise ValueError("--kind is required only for LANGUAGE")
            needs_position = args.action in ("update", "delete")
            if needs_position != (args.position is not None):
                raise ValueError("--position required only for update/delete")
            needs_fields = args.action in ("create", "update")
            if needs_fields != (args.changes_file is not None):
                raise ValueError("--changes-file required only for create/update")
            changes = None
            if needs_fields:
                changes = json.loads(Path(args.changes_file).read_text(encoding="utf-8"))
                if not isinstance(changes, dict):
                    raise ValueError("Native changes file must be a JSON object")
            if args.section == "portfolio" and args.action == "update":
                raise ValueError("PORTFOLIO record replacement not yet supported")
            operation = getattr(client, f"mutate_{args.section}")
            params = {
                "expected_timestamp": args.if_match.strip('"'),
                "changes": changes, "position": args.position,
            }
            result = (
                await operation(args.resume_id, args.kind, args.action, **params)
                if args.section == "language"
                else await operation(args.resume_id, args.action, **params)
            )
        elif args.command == "portfolio-conversion":
            result = await client.get_portfolio_conversion_status(
                args.resume_id,position=args.position,
            )
        elif args.command == "portfolio-file":
            result = await client.upload_portfolio_file(
                args.resume_id, expected_timestamp=args.if_match.strip('"'),
                name=args.name, attach_name=args.attach_name or upload_file.filename,
                filename=upload_file.filename,
                content_type=upload_file.content_type,
                content=upload_file.content,
            )
        elif args.command == "theme":
            result = await client.set_theme(
                args.resume_id, args.section, args.selected_theme,
                expected_timestamp=args.if_match.strip('"'),
            )
        elif args.command == "sort":
            if (args.section == "language") != (args.kind is not None):
                raise ValueError("--kind required only for LANGUAGE sorting")
            result = await client.sort_records(
                args.resume_id, args.section, args.from_position,
                args.to_position, expected_timestamp=args.if_match.strip('"'),
                **({"kind": args.kind} if args.kind is not None else {}),
            )
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
                    "planned_sections": changed_sections(checked_write_paths(plan.operations)),
                    "atomic": False,
                }
            else:
                from job_platforms.core.errors import ConflictError
                if str(plan.base_timestamp) != args.if_match.strip('"'):
                    raise ConflictError("Resume has changed since the caller read it")
                if args.confirm == "experimental-bio-write":
                    paths = checked_write_paths(plan.operations)
                    if any(not path.startswith("/bio/") for path in paths):
                        raise ValueError(
                            "The BIO-only confirmation cannot authorize other sections"
                        )
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
