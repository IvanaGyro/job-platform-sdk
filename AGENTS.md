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

## Collateral-write preservation for direct native mutations (2026-11-20)

Every newly added native writer must verify its requested target *and* call
`verify_untouched_blocks(before, after, changed=section)` before claiming
successful persistence. This includes record CRUD, theme changes, sorting,
CUSTOM and upload flows. `changed` must name exactly the section whose
write is intended; numbered CUSTOM slots remain protected independently.
An aggregate `custom` layout theme is a permitted special target, not a
license to ignore changes in custom1..custom6. The shared comparator
intentionally ignores only four regenerated access tokens in PORTFOLIO
**FILE**, never LINK URLs or other metadata. A collateral change is a
verification failure; never retry an already-submitted write or claim an
automatic rollback. This is a synthetic-tested client safety guard and is
not upstream 104 atomic concurrency support.

## Local HTTP idempotency persistence (2026-11-21)

The server defaults to its original in-memory result map. For a stateful
single-worker local API, opt in with `JOB_PLATFORM_IDEMPOTENCY_DB` pointing
to a private, absolute SQLite file under an existing trusted POSIX folder.
`SQLiteIdempotencyJournal` reserves the opaque HMAC-keyed request before
network I/O and persists successful verification via a journal-backed
`entry.update()`; every new route using `idempotency_results[key] = entry`
**must read back** `entry = idempotency_results[key]` before calling upstream.
Otherwise its successful in-memory dict mutation will not be committed to
disk. Never auto-expire/reuse ambiguous entries, store raw request bodies,
print private identity strings, or upload the SQLite file. A restarted
service must replay successful results from disk and refuse uncertain
entries with 409. This is not remote 104 transactional or multi-process
locking. Test with synthetic app restarts and disk-read checks only.

## Sensitive UNDER18 identity writes (2026-11-20)

The official Vuex source describes only CREATE/UPDATE via
`resumeByBlock/under18`, with `birthdayDocument`, `idType` and
`selfIdentityConfirmed`. New `mutate_under18()` is experimental, requires
`acknowledge_identity_write=True`, and never includes those values in
success/error results. CLI `under18` additionally requires
`--acknowledge-identity-write` and explicit confirmation, while HTTP
POST/PUT needs `X-Identity-Write-Acknowledgement: true`, experimental
write opt-in, Bearer, If-Match and Idempotency-Key. Do not add a guessed
DELETE, infer legal attestation values, log actual identity data, or
claim that frontend source mapping proves website acceptance. The known
authorized resume had no UNDER18 GET sample; synthetic tests only. Treat
any newly discovered native field or media value as unsupported until it
has an authorized, privacy-preserving contract and write/restore evidence.

## Multi-section PATCH read-back and pre-PUT checks (2026-11-20)

Do **not** approve a write solely because the requested value matches
GET. `save_edit()` uses `patch_verification.verify_patch_transition()`
to verify all non-target native blocks; BIO/CERTIFICATE/EXPERIENCE also
protect their other form fields and SIDEBAR protects entire row metadata.
A real no-op double GET documented only four volatile PORTFOLIO **FILE**
access fields; LINK URLs, file names and content fields remain strict.
Before the second and every later PUT, re-GET the resume, check the
latest `resumeTimestamp` and compare all known blocks to the previous
verified snapshot. A pending block changed by another writer must never
be overwritten using an earlier-serialized body. These checks are
synthetic-tested and conservative, not atomic CAS/transaction support;
never retry a submitted but unverified write or claim an automatic rollback.

## CUSTOM source-defined content slots (2026-11-20)

Official bundle module 5255 defines `contentNumber` as 1 for CLASSIC,
BANNER and TEXT, and 2 for IMAGE/MAGAZINE. Do not restore the old generic
six-item limit or widen CLASSIC/BANNER `mutate_custom_layout()` to multiple
rows without new upstream evidence and a separately tested safe lifecycle.
`custom_theme_capabilities()` exposes these static constraints through the
SDK/CLI/HTTP with explicit evidence labels and no site login. IMAGE's
single PNG raw POST was accepted in older live tests, so the offline image
serializer permits one or two inputs. MAGAZINE's former one-item POSTs
failed, so the planner only models a complete two-item candidate and **no
successful MAGAZINE write is asserted**. The capability catalog does not
imply current server approval or enable a new write API.

## CUSTOM CLASSIC/BANNER writer boundary (2026-11-20)

`mutate_custom_layout()` is a separate experimental SDK method for only
CLASSIC=1/BANNER=2 and exactly one content item with `{type:0}` media.
The CLI `custom-layout` and opt-in HTTP `/custom-layout` map the same native
POST/PUT/DELETE; they do not enable IMAGE, MAGAZINE, multi-content forms,
or theme conversion. A malformed or occupied native CUSTOM slot, any
media identifiers, extra content metadata or unsupported dates must abort
before an upstream write. The current revision and website theme options
are checked on create, updates preserve the existing theme, and each write
verifies the complete target content plus other CUSTOM slots. The earlier
private raw endpoint cycle succeeded in 104, but the new SDK/CLI/HTTP
path has **synthetic tests only**. No real account access was needed to
implement it. Do not equate earlier raw success with live wrapper coverage.

## Revision preflight for all direct writes (2026-11-20)

Always use `revision_guard.revision_matches(document, expected_timestamp)`
on every SDK or HTTP writer. A missing, `None`, bool, malformed, oversized
or sentinel-string `resumeTimestamp`/`If-Match` must fail before any site
mutation. Do **not** fall back to `str(doc.get("resumeTimestamp")) == str(expected)`:
this mistakenly accepts two missing values or a user-supplied `"None"`.
The guard is a necessary client precondition, not a server CAS primitive,
and does not supersede the transport `104-profile-ver` handshake. Tests
must ensure the HTTP preflight does not reserve an Idempotency-Key on a
missing/invalid revision. This is synthetic-tested; no 104 live write was
made for this refactor.

## Non-writing PATCH planning (2026-11-20)

Call `client.plan_edit()` or the CLI `plan` before a multi-section write. It
now requires a usable `resumeTimestamp`, checks every mapped write path and
serializes every affected block without submitting changes. Unsupported
account identity/media fields fail preflight; successful planning does **not**
prove the upstream website will accept a write. Use the offline command
`job-platform writable-paths` to list currently implemented `replace` paths,
not all fields returned by 104. Never interpret it as universal edit coverage.

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

## Completed 104 integration-test recovery (2026-11-19)

The uniquely marked fifth EXPERIENCE test record from 2026-11-18 was
**successfully removed** on 2026-11-19. One successful browser login
on the new private proxy list provided two independent HTTP transports.
The writer's SDK DELETE reported verified=true, and the second
transport's GET proved the entire original EXPERIENCE formData and
the four original rows were restored **field-for-field as structured
JSON** against the private backup. The previous hold on live writes
due to this specific synthetic residue is now lifted.

A separate authorized 2026-11-19 SDK cycle then **created** a uniquely
marked fifth EXPERIENCE row with companyVisibility=True, independently
read it, SDK-deleted it, and independently verified exact restoration
of all four original EXPERIENCE rows and unchanged BIO. Both SDK
CREATE and DELETE reported verified=true. All real private backups
and diagnostic logs remain outside Git. Never leave test rows in a
user's resume, and always verify restoration after an uncertain reply.

**Privacy guard:** a prior POST with companyVisibility=False was
persisted by 104 as True. New EXPERIENCE CREATE requests with False
now fail *before the HTTP write* instead of risking a public entry.
This behavior is not silently normalized. No claim is made that 104
supports creating a hidden-company record.

**LANGUAGE duplicate-type guard (live observation 2026-11-19):** an
attempted FOREIGN POST for a type already present in the designated
resume did **not** append a row. The server silently overwrote the
existing FOREIGN ability selectors; the SDK rejected the supposed
CREATE, then a guarded SDK UPDATE exactly restored the original
LANGUAGE formData, independently verified via a second transport.
Do not attempt another same-kind duplicate type CREATE; the SDK now
rejects it *before HTTP*. Use UPDATE for an existing type. A genuinely
new FOREIGN type CREATE/DELETE remains unverified live.

**2026-11-20 guarded FOREIGN CREATE attempts:** no real mutations were
submitted. Proxy index #4 browser login succeeded but detached HTTP resume
access failed. Index #6 completed two independent HTTP resume GETs, but a
BFF input-validation read was denied. A final #6 browser login failed;
authentication retries stopped. Offline code now guards the official native
`/profile/ajax/inputField` per-kind count before CREATE; however, this
count preflight and unique foreign CREATE/DELETE were **not** live verified
in this continuation. Do not resume an unverified write by blindly POSTing;
revalidate the test resume and backup from a fresh authorized session first.

**Sign-in guard:** PDA entry HTTP 403 does not necessarily mean that
the official signin.104.com.tw login flow is blocked. The adapter
retains HTTP/Cloudflare evidence and, for a non-challenge 403, attempts
the official sign-in before classifying login failure. Do not bypass
explicit Cloudflare challenges, and authenticate only as needed.

In short: **authenticate once per planned live batch, reuse the session for
many operations, refresh document state when needed, and reauthenticate only
when there is a concrete reason.**
