# Instructions for coding agents

## Choose the next 104 task

- Follow the active checkpoint and priority order in [the editor backlog](docs/unimplemented-editor-fields.md). Stay on the assigned item when access fails and troubleshoot the blocker before moving on. Complete 104 before adding other providers. Keep the PR open until asked to merge.
- Keep missing writers in the backlog and existing writers awaiting live verification in [the coverage inventory](docs/tw104-editor-coverage.md). Report the backlog ID and count newly live-verified fields only after authorized persistence, independent GET and exact restoration.

## Authenticate and diagnose access

- Start with source inspection and local tests. Before live access, follow the [104 sign-in and transport runbook](docs/tw104-login-troubleshooting.md).
- Reuse one authenticated browser context and its proxy for a planned batch. Derive HTTP transports from that login. Verify the browser can read the same endpoint before diagnosing a curl failure, and classify the failing stage and response before starting a fresh profile or trying another proxy.
- Keep credentials, cookies, MFA/identity data, proxy details, resume data, backups and raw diagnostics private. Keep HTTP handoff state in memory.

## Protect live writes

- Use source-confirmed operations on the authorized test resume only. Back up privately, use a uniquely identifiable reversible change, verify persistence through a fresh independent GET, and verify exact restoration.
- Validate revision preconditions with `revision_guard.revision_matches()` and honor the transport's `104-profile-ver` requirement. Use a fresh GET before each subsequent write in a multi-step edit. Verify the intended target and protect sibling fields and blocks with `verify_patch_transition()` or `verify_untouched_blocks()`, as applicable.
- Reconcile ambiguous writes with a fresh GET before taking any further action. Avoid automatic write retries or rollback. Follow the [editor and transport contracts](docs/tw104-hybrid-transport.md) for read-only planners, batch writes, optional HTTP idempotency, and sensitive or media-specific writers.
