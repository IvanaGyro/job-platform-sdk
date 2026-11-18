# Instructions for coding agents

These project rules apply to contributors and AI coding agents working on the
SDK, CLI, API service, tests, and integration workflows. Read
[docs/tw104-hybrid-transport.md](docs/tw104-hybrid-transport.md) before live
104 work.

## Minimize authentication (important)

**Do not repeatedly sign in to 104 unless a new login is actually required.**
Login is a costly, stateful operation that may trigger MFA, risk controls, or
temporary access failures. A fresh login is not a prerequisite for each API
call, resume section, test function, independent read-back, or retry.

1. First do static source inspection and unit/loopback tests **without any
   live login**. Group genuinely necessary live checks into one planned batch.
2. Within a batch, open **one** `FreshBrowserSession(AuthConfig(...))` and
   reuse its authenticated browser context, proxy and `Resume104Client` for
   sequential operations. Do not create a new `FreshBrowserSession` inside
   every API method, test case, or resume-field update.
3. For HTTP work, call `session.http_transport()` and reuse the resulting
   `CurlCffiTransport` / `Resume104Client` across requests. An independently
   verifying second HTTP session may be created **from the same authenticated
   browser session**; it does **not** require a second sign-in. Each transport
   must independently GET a fresh document / `104-profile-ver` before writing.
4. If the remaining batch needs no browser UI, the opt-in
   `session.http_transport(close_browser=True)` or
   `session.resume_client(transport="curl_cffi_detached")` can close Chromium
   **after** transferring cookies. Keep the same proxy and retain the HTTP
   transport until the batch ends. Browser-only actions then require a new
   browser session; plan their order accordingly.
5. For an API server or workflow, design the session owner/lifetime explicitly:
   reuse an authenticated transport across related calls **while valid**;
   avoid a fresh login on every route invocation. Scope reuse to the authorized
   account and execution context, and clean up when finished.
6. Log in again only after session expiry/revocation is established, an
   operation needs a new browser-only context after detachment, or a test
   deliberately requires login isolation / a different account. Diagnose
   authentication or connectivity errors first: **403, redirect, or curl
   failure alone does not prove expired cookies**. Never loop through
   automatic sign-in/MFA retries or silently rotate proxies to bypass blocks.

### Preferred read-only pattern

```python
async with FreshBrowserSession(AuthConfig.from_env()) as session:
    browser_client = Resume104Client(session.page)
    resume_list = await browser_client.list_resumes()
    # More reads can reuse browser_client, without signing in again.
    http = Resume104Client(transport=await session.http_transport())
    # For an independent GET, obtain a second HTTP transport from *session*,
    # not a second FreshBrowserSession/login.
    verifier = Resume104Client(transport=await session.http_transport())
```

## Security and safe live writes

- Maintain the original authenticated login proxy, 104-domain cookie scope
  and user-agent constraints. Do not silently fall back to direct access.
- Do not commit or print credentials, cookies, identity-verification data,
  proxy URLs with secrets, actual resume values, or private integration logs.
  Keep private backups outside the public repository. Do not introduce
  persistent login caches merely to avoid authentication.
- Reuse authentication, **not stale resume state**. Perform fresh GETs and
  timestamp checks before writes. Require the transport's latest available
  `104-profile-ver`; do not assume it guarantees atomic server-side
  concurrency control. Avoid concurrent writers on the same resume.
- For any permitted live write: back up the target privately, change only a
  uniquely identifiable reversible test item, verify through independent GET,
  then restore and verify the original content. A second HTTP transport
  derived from the same login is sufficient for a separate request path.
- If a write response is ambiguous, **read and reconcile first; never blindly
  retry** a POST/PUT/DELETE. Don't reauthenticate just to retry a failed write.
- Respect the user's instruction to keep PRs open until explicitly asked to
  merge. Complete 104 coverage before adding Cake, Yourator or Greenhouse.

In short: **authenticate once per planned live batch, reuse the session for
many operations, refresh document state when needed, and reauthenticate only
when there is a concrete reason.**
