# 104 hybrid browser / HTTP transport

The default is still `BrowserTransport`: Patchright authenticates and issues
same-origin requests. An opt-in `CurlCffiTransport` instead uses `curl_cffi`
0.17 / Chrome 146 impersonation after a **successful browser login**.

## Cross-section PATCH preservation and fresh GET between PUTs (2026-11-20)

An audit of `save_edit()` found that a correct **target value** could
conceal damage elsewhere: a seniority-only EXPERIENCE PUT previously
verified only `seniority.value`, not surviving `experiences[]`; BIO and
CERTIFICATE also projected only a subset of their native form metadata;
SIDEBAR read-back checked only reordered IDs, not the row contents. The
new `patch_verification.py` compares every known non-target native resume
block against the immediately preceding pre-PUT GET. Within the target
BIO, CERTIFICATE and EXPERIENCE blocks it also protects non-target fields;
SIDEBAR must contain each original row and complete metadata, regardless
of order. No type/category/media identifiers may be silently discarded.

The site regenerates exactly four known PORTFOLIO FILE access fields on
unmodified GETs: `fileId`, `thumbnailFileId`, `src`, and `url`. The guard
reuses the independently live-observed FILE-only exception from
`layout_theme.py`. It still checks LINK destination URLs, file names,
record identities, metadata and all other sections exactly. A changed
unrecognized field fails closed (possible false negative rather than a
false claim of verified persistence).

For multi-section PATCH, the SDK now makes an extra GET before **every
subsequent PUT**, comparing the latest global `resumeTimestamp` and all
known blocks to the last verified read-back. It aborts if a second editor
changes a pending block (or advances a previously verified revision) in
the interval. This remains client-side checking, **not atomic server-side
compare-and-swap**. A submitted but unverified write is not retried;
`PartialWriteError` reports verified earlier blocks if a later block fails.
All new checks were tested using synthetic GET/PUT fixtures; there was
no new 104 site login, read or write in this continuation.

## CUSTOM frontend content cardinalities and offline inspection (2026-11-20)

Production Vue module 5255 maps `CustomThemeImage` and
`CustomThemeMagazine` to `contentNumber=2`; other CUSTOM themes default
to exactly one. The previous generic CUSTOM serializer used a site-
unsupported six-item ceiling. Its new source-mapped per-theme guard
allows only one CLASSIC/BANNER/TEXT row, one or two IMAGE inputs (based on
past raw one-PNG server acceptance), or two MAGAZINE candidate rows. The
latter is **not claimed to succeed**: actual prior MAGAZINE writes failed.
`custom_theme_capabilities()` is exposed by the SDK static method,
`job-platform custom-themes` (offline) and token-protected local HTTP
`GET /v1/tw104/custom-themes` (no site GET). It carries limits, exact
implementation scope and historical evidence without account data. All
new regression tests are synthetic; no browser login or write was used.

## Guarded CUSTOM CLASSIC/BANNER no-media CRUD (2026-11-20)

The frontend's CUSTOM module 4228 supplies POST/PUT/DELETE
`/profile/ajax/resumeByBlock/custom` requests. Existing private 104
raw endpoint tests on 2026-11-17 confirmed reversible CLASSIC=1/BANNER=2
single no-media CRUD, but the **new SDK/CLI/HTTP wrapper remains synthetic-
tested only**. The SDK `mutate_custom_layout()` refuses occupied slots,
unknown themes, incomplete/complex native GET forms, media metadata,
multiple content rows, and any HTML/URL/date values outside the bounded
serializer. UPDATE preserves the current theme and unchanged fields; a
fresh GET must match all expected fields, and all sibling CUSTOM slots
must remain unchanged. The CLI's `custom-layout` and authenticated
HTTP `/custom-layout` endpoints use mandatory explicit write opt-in,
`If-Match`, and (for HTTP) an Idempotency-Key. No ambiguous remote
request is automatically retried. MAGAZINE, IMAGE and live wrapper
read-back are still unresolved, and the work made no new real-site writes.

## Shared mandatory revision guard for all writes (2026-11-20)

A follow-up SDK/HTTP audit found unsafe
`str(before.get("resumeTimestamp")) == str(expected_timestamp)` patterns:
missing GET revisions could appear equal to the text `"None"`, and boolean
or other invalid versions might compare equal to numeric revisions. The
single `revision_guard.py` now validates both the actual website GET revision
and requested `If-Match` or SDK `expected_timestamp` before any operation.
All native record CRUD, CUSTOM TEXT, LANGUAGE, theme, sort, multipart upload,
file conversion and HTTP endpoints use this guard; JSON Patch planning and
saving also require a valid revision. The guard allows native integer or
opaque text versions and an equivalent text/number representation, but rejects
missing/invalid values, sentinel strings and excessively long revisions.
A rejected HTTP preflight does **not** reserve the operation's Idempotency-Key.
These checks are synthetic-tested, not a proof that upstream 104 enforces
atomic conflicts or that no other site/account-level changes can occur.
No private credentials, browser session or real resume mutation were used.

## Read-only native editor field constraints (2026-11-20)

`Resume104Client.get_editor_limits(section)` requests only the site's
`/profile/ajax/inputField` data and exposes numeric/bool field boundaries,
not full raw metadata. `job-platform editor-limits project` and bearer-only
`GET /v1/tw104/editor-limits/project` use the same SDK method. The native
frontend uses plural groups `projects`/`portfolios`/`referrers`/`customs`;
these are mapped to the SDK's singular section names. A sanitizer omits
all unknown scalar fields, strings (including regexes), arrays and invalid
values; malformed or missing groups fail closed. This work is synthetic-
tested; the current upstream response has not been rechecked live, and
field constraints do not establish write support.

## Versioned JSON Patch planning and writer discovery (2026-11-20)

- `Resume104Client.plan_edit()` is a strict, non-writing preflight. It requires
  the original GET to supply a usable `resumeTimestamp`, permits `test`
  preconditions against readable fields, but rejects `replace` operations
  outside the explicitly mapped whitelist. All changed native sections are
  serialized and validated **before** issuing a plan. A plan preview therefore
  no longer promises persistence for an unsupported field. `save_edit()`
  independently checks the version again and rejects a missing revision.
- `job-platform writable-paths` reads the explicit mapping **offline without
  authentication**, and the bearer-token-protected
  `GET /v1/tw104/writable-paths` and Python
  `Resume104Client.supported_patch_paths()` expose the same catalog. A
  source-mapped path is not necessarily live-write verified on the website;
  native record CRUD, theme, media and upload routes are separate.
- The HTTP `POST .../plan` response identifies `planned_sections`, an upper
  bound on section PUT requests, and `atomic:false` for caller guidance.
  Actual multi-section PATCH remains non-transactional. Tests are entirely
  synthetic; **no 104 authentication or live mutation** was used here.

## Guarded 2026-11-20 continuation — no new real mutations

- LANGUAGE DELETE verification now protects surviving FOREIGN certificate
  associations and all unrelated section metadata, not just option IDs.
  GET arrays may arrive out of `sort` order; the SDK normalizes only unique
  contiguous identifiers and rejects duplicate language IDs.
- Read-only `get_language_editor_options` is exposed by the Python SDK,
  CLI `language-options`, and authenticated HTTP API GET. Each uses current
  site options, the selected kind's count limit, and GET sort identities.
  These paths have synthetic parity tests only, and do not enable writes.
- LANGUAGE CREATE checks the current `GET /profile/ajax/inputField`
  per-kind `count` limit before POST. Source-mapped and synthetic-tested,
  not a new live successful create.
- Three private single-login attempts stopped before HTTP writes: #4
  browser authenticated but detached HTTP resume access failed; #6 detached
  HTTP resume reads succeeded but BFF input-validation GET was denied; a
  final #6 browser login failed. These failures are not interpreted as a
  Cloudflare challenge or proof of expired cookies. No real resume record
  was changed in these test attempts. No repeated login attempts followed.

## Latest verified work — 2026-11-19

- **LANGUAGE selector preflight (source + synthetic):** the frontend
  chooses actual foreign/dialect IDs from different option arrays and its
  INSERT action uses PUT for an existing same-kind ID, POST only for a new
  ID. SDK CREATE/UPDATE now uses a read-only current options GET to validate
  all supplied language and proficiency selectors before any HTTP write.
  This is not a new live foreign CREATE verification.
- **LANGUAGE FOREIGN duplicate type observed:** one real POST attempted
  to CREATE a second foreign row with an already-present type; instead
  the existing row was overwritten. The SDK reported the CREATE as
  unverified, then performed a guarded SDK UPDATE restoring the exact
  original LANGUAGE formData; a second HTTP transport independently
  verified the restoration. The SDK now rejects duplicate same-kind
  LANGUAGE CREATE **before sending HTTP**, rather than risking another
  silent overwrite. A unique FOREIGN CREATE/DELETE remains unverified.
- **SDK EXPERIENCE CREATE/DELETE/restore:** using one authorized
  browser login and two independent HTTP transports on the same
  proxy, a uniquely marked fifth row was created with
  companyVisibility=True, independently read back, deleted by the
  SDK, and independently verified to restore the **exact original
  EXPERIENCE formData** (four original records). BIO was unchanged.
  Both SDK methods returned verified=true; all private snapshots
  and logs remain outside the repository.
- **Earlier residual test row cleanup completed:** the earlier
  fifth synthetic EXPERIENCE record from a previous mismatched POST
  was independently identified, deleted through the SDK, and the
  entire original section was restored exactly. No pending synthetic
  EXPERIENCE residue remains in the verified read-back.
- **Privacy preflight:** 104 previously changed submitted
  companyVisibility=false into true. The SDK now refuses this
  unsupported EXPERIENCE CREATE *before writing*. The successful
  live CREATE used true, not an unverified normalization.
- **PDA 403 fallback:** independent curl and Chromium checks showed
  the PDA entry page can return 403 while official sign-in succeeds.
  A non-challenge 403 on PDA entry is logged and then followed by
  the official sign-in path; `cf-mitigated: challenge` remains a
  hard stop. In a subsequent single-attempt-per-proxy round,
  four of ten proxies completed login and authenticated overview
  checks. This does not guarantee future availability or establish
  that every 403 was issued by Cloudflare.

## Session lifecycle

1. `FreshBrowserSession` signs in using its selected proxy (including MFA).
2. `http_transport()` copies **104-domain cookies only** from in-memory
   `context.storage_state()` into a new `curl_cffi.requests.AsyncSession`.
3. The HTTP session uses the **same proxy** and the browser's User-Agent.
   Environment proxies are disabled; it never silently switches to direct IP.
4. HTTP requests share a lock and refresh the in-memory `104-profile-ver`
   response header. HTTP session cookies update from Set-Cookie.
5. The HTTP transport closes with the browser session. No SQLite or disk cache.

Both implementations share the `Resume104Client` method surface, so the
client can read overview, resumeByBlock and options through either transport.

## Diagnostic stages for 104 browser sign-in

`FreshBrowserSession.open()` now retains a bounded, **sanitized**
`prelogin_diagnostics` list with one `PreloginDiagnostic` per failed proxy
attempt and includes summaries in the final `AuthenticationRequired`
message when no proxy reaches the account step. No raw Playwright trace,
proxy URL, cookie, account data, URL query or response body is logged.

- `proxy_config`: missing index or malformed `host:port:user:password` line.
- `chromium_launch`: Chromium failed to start with this proxy.
- `pda_entry_navigation` and `pda_profile_navigation`: the 104
  entry/profile request failed before the sign-in form was reached.
- `signin_navigation` / `signin_hostname`: sign-in page network error,
  unexpected destination or observed HTTP error.
- `signin_form`: the expected `input#identity` field is missing.
- `login_init`: the same-origin `/v1/api/login/init` request failed.
- `reason` is a stable, sanitized failure code; `status` is included
  **only** when the browser actually observed a numeric HTTP response.
  Chromium `net::ERR_*` codes are extracted from Playwright exceptions
  into `net=...`, but the exception text is never included.

For example, diagnostic output can look like:

```text
proxy#3 stage=signin_navigation reason=http_error status=403 cf=edge_headers
proxy#4 stage=pda_entry_navigation reason=Error net=ERR_TUNNEL_CONNECTION_FAILED cf=unconfirmed
proxy#5 stage=login_init reason=login_init_http_error status=403 cf=challenge
```

These lines are **illustrations, not observed upstream test results**.
`cf=challenge` requires `cf-mitigated: challenge`, even if the HTTP
status is 200; `cf=edge_headers` means Cloudflare response headers
were present, **not** that Cloudflare itself caused the status.
`cf=unconfirmed` means the browser has no such evidence, not that
Cloudflare was absent. A 403 from the origin is distinct from a failed
Proxy CONNECT / navigation (`net::ERR_*`) that produced no HTTP status.

This diagnostic only describes the **pre-account phase**; a later account,
password, MFA or resume-access failure may still have a separate root cause.
No raw response headers, cookies, or private values should be printed.

## Selecting a backend

CLI: `job-platform --transport curl_cffi list`, or set
`JOB_PLATFORM_104_TRANSPORT=curl_cffi` for CLI and localhost HTTP server.
Install optional Python dependency with `pip install '.[curl]'`.
Default `browser` remains the fallback.

Optional `--transport curl_cffi_detached` transfers cookies and **closes
Chromium immediately after login**, freeing browser resources while retaining
the proxy-bound HTTP session. This is a deliberate tradeoff: browser fallback
and browser-only new-resume creation are unavailable until a new login session.
The option is not the default, and HTTP writes remain separately opt-in.
A private same-session trial found synchronous curl, asynchronous curl,
and the SDK adapter all returned HTTP 200 JSON after Chromium closed.
In private authorized tests, detached mode completed **real, reversible 104
BIO PUT, PORTFOLIO LINK POST/DELETE and synthetic PDF FILE POST/DELETE**,
each with two independent HTTP Sessions and independent read-back.
The exact original BIO values and the original PORTFOLIO display identities
were restored. This does **not** establish that browser resource contention
caused earlier connection failures, nor verify other editor sections or
server-side physical file deletion.

HTTP transport **writes are disabled** unless
`JOB_PLATFORM_104_CFFI_ENABLE_WRITES=1` is explicitly set. For the localhost
HTTP service, this is in addition to the existing
`JOB_PLATFORM_104_ENABLE_EXPERIMENTAL_WRITES=1` gate. This flag enables
**experimental**, not yet fully live-verified, writes. Never enable for an
unattended production resume without a private backup and independent GET.

## Guarantees and limitations

- Accepts relative 104 paths only; rejects external hostnames and fragments.
- POST/PUT/DELETE require a previously observed `104-profile-ver`.
  Version refresh alone is not an atomic concurrency guarantee.
- JSON, URL-encoded form fields and bounded multipart files are supported.
  The `CurlMime` serializer is also covered by a real **localhost HTTP wire
  test** of form-only LINK and generated PDF FILE requests, confirming exact
  field and file bytes. These loopback checks are separate from the live
  authenticated 104 write/restore tests below. No automatic retry occurs;
  ambiguous network failures during writes raise `VerificationError`.
- For GET, a 401, 403 or redirect indicates an authentication/network-risk
  failure; a 403 does **not** prove an expired cookie. For writes, 401/403,
  redirects, 429, 5xx, and 2xx non-JSON or malformed JSON raise an
  **uncertain-write** verification error; never resubmit without fresh GET.
  HTTP 409/412 become explicit conflict errors, while other 4xx retain
  sanitized upstream errors. BrowserTransport has matching safeguards.
  These conflict codes are synthetic-tested but **not confirmed on 104**.
- An authenticated browser session is still needed to obtain cookies;
  reuse without the original proxy remains **unverified/blocked** by the
  previous A/B network tests.
- The version header has been used in real successful BIO, LINK and FILE
  writes. Server-side conflict behavior, session-cookie rotation, complete
  resume lifecycle and other section write/restore remain unverified.
- Signed media URLs, native response bodies and session secrets are never
  logged by the transport. Private integration test evidence remains outside
  this public repository.

### Proxy connectivity status at 2026-11-18 continuation

Earlier authorized tests completed full 104 sign-in via two proxies
in the new private ten-proxy list. During this continuation, those two
connections failed at `pda_entry_navigation` with a sanitized
`reason=Error` and no observed HTTP 403. Independently, **all ten**
proxies in the new list failed unauthenticated requests to both a
public TLS diagnostic site and the 104 login page with curl error 7.
Therefore **no usable current transport** was established, no
Cloudflare 403 was proven, and no EXPERIENCE DELETE was submitted.
**Historical status only:** the initial residual EXPERIENCE record
was subsequently removed with an independently verified SDK DELETE
on 2026-11-19. Later binary-curl and browser diagnostics showed
client-specific responses even when an earlier curl_cffi connection
failed. Prefer recent, per-client connectivity evidence, not a
single old error, and do not repeatedly log in without cause.

## Test evidence

- **Synthetic unit tests:** cookie-domain scoping, proxy binding, read
  decoding, 401/403/redirect/non-JSON handling, header version propagation,
  write gate, form encoding, `CurlMime` cleanup and uncertain-write non-retry.
- **Local HTTP wire tests:** `ThreadingHTTPServer` parses multipart LINK
  and synthetic PDF FILE with revision headers. A loopback `Set-Cookie`
  response is automatically carried to the next HTTP request, verifying
  in-memory session rotation. Optional `curl_cffi` is required; base CI
  skips these tests without the extra. **Real 104 cookie rotation remains
  unverified.**
- **Earlier private live observation (not this implementation):** Chrome 146
  `curl_cffi` + **original login proxy** + session cookies returned HTTP 200
  resume-overview JSON; the same request directly returned 403.
- **New transport, real read-only 104 A/B (2026-11-17):** browser login
  succeeded on the original proxy; both implementations independently
  returned successful JSON for `overview`, `resumeByBlock` and `options`
  with the same top-level data keys (1, 17 and 51 keys, respectively).
  The requested resume version was confirmed, and a `104-profile-ver`
  header was observed by the HTTP transport after native GET requests.
  Signed media tokens and full-field equality were **not** checked.
- **Live BIO PUT (2026-11-18):** a uniquely marked synthetic field update
  passed independent second-session GET, exact original BIO restoration and
  independent verification. A private backup was saved before writing.
- **Live PORTFOLIO LINK POST and DELETE (2026-11-18):** one temporary
  uniquely identified `example.invalid` link was added via text-only
  `CurlMime`, independently GET-verified and safely deleted by its current
  sort position; independent GET confirmed the original ordered displayed
  identities were restored.
- **Live PORTFOLIO PDF FILE POST and DELETE (2026-11-18):** a generated
  621-byte synthetic PDF was sent via `CurlMime`, independently GET-verified
  as an addressable FILE record and safely deleted. Independent GET confirmed
  the original displayed attachment identities were restored. PDF preview,
  downloaded-byte checksum, and underlying backend blob garbage collection
  were **not** verified; rotating signed URL/file IDs cannot prove identity.
- The three live cycles used the **original login proxy**, disposed of
  Chromium after cookie transfer, checked the baseline in two independent
  HTTP sessions before mutation, and kept private original backups. Their
  success does not validate remaining 104 fields, conflict recovery, file
  conversion or session-cookie rotation.
- **Live JOB_CONDITION and INFO PUT (2026-11-18):** two independent
  authenticated curl_cffi sessions preflighted the same timestamp and
  original form. The native strings `jobCondition.preferJobContent` and
  `info.motto` were each PUT, independently GET-verified, and restored to
  their **exact original full formData**. The SDK rejected stale
  `resumeTimestamp` edit plans without submitting them; this is **not**
  evidence of upstream rejection of an outdated `104-profile-ver`.
- **Live SIDEBAR reorder PUT (2026-11-18):** one adjacent swap among eight
  items passed two independent preflight GETs, independent read-back and
  exact original record-order restoration. Metadata edits remain unsupported.
- **LAYOUT JOB_CONDITION theme PUT and exact restoration (2026-11-18):**
  an initial detached HTTP attempt was inconclusive and independently
  confirmed unchanged. A browser PUT then **did change the theme**, but
  the SDK falsely returned `VerificationError` because its global verifier
  expected byte-identical unrelated PORTFOLIO FILE tokens. Two unchanged
  consecutive 104 GETs showed fileId, thumbnailFileId, src and url rotate.
  The verifier now excludes exactly those fields for FILE=1, **never** LINK
  destinations, names, status or other resume fields. A subsequent browser
  SDK test successfully changed and restored JOB_CONDITION's theme with
  real read-back and exact original section restoration. The other ten
  section themes remain unverified.
- **Live EDUCATION POST/DELETE and SDK correction (2026-11-18):**
  an authorized synthetic school was successfully created via the detached
  HTTP transport, but the original SDK GET validator rejected the server's
  empty domestic region selector. A private raw DELETE recovered only the
  unique test record and independently proved the exact original form.
  After a narrow serializer fix, the **SDK itself** successfully repeated
  create, independent second-session read-back, delete and exact restoration.
  Tests also reject empty region when foreign codes are present. The
  full EDUCATION list and theme were preserved. Other EDUCATION options
  and reorder operations remain unverified.
- **Single-login multi-operation batch (2026-11-18):** one
  FreshBrowserSession authenticated the designated test resume once.
  Two separate curl_cffi transports derived from that same login
  completed independent, safe preflight and read-back; Chromium
  was closed after the handoff. LANGUAGE local SDK create/delete
  was verified, then the exact original formData restored.
  EXPERIENCE POST also created a synthetic fifth record but reported
  a mismatch: companyVisibility=false was stored as true, so SDK
  verification failed. A later GET ordered the records
  [4,5,3,2,1]. The parser has been fixed to accept contiguous
  sort-key permutations. **This was a historical blocker:**
  the original residual row was later removed on 2026-11-19
  with independently verified SDK DELETE and exact restoration.
  A second live SDK CREATE/DELETE round trip also completed with
  companyVisibility=True. See the latest checkpoint above.
- **Intermittent transport issue:** with the same login Proxy #4 and valid
  Chromium session, curl code 7 (connection failure before any HTTP status)
  appeared at times for **both** synchronous and asynchronous curl variants,
  including the SDK; other sessions returned 200 for all. Both variants
  could reach a public TLS test endpoint through the same proxy. Resource
  contention, network routing, and risk-based filtering remain unproven
  explanations. Do not silently retry a write when its outcome is unknown.
- These observations do not prove that matching JA4 alone determines
  upstream authorization, or that a proxy-free connection is viable.
