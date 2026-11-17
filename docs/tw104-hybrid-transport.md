# 104 hybrid browser / HTTP transport

The default is still `BrowserTransport`: Patchright authenticates and issues
same-origin requests. An opt-in `CurlCffiTransport` instead uses `curl_cffi`
0.17 / Chrome 146 impersonation after a **successful browser login**.

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
- A 401, 403 or redirect is an authentication/network-risk failure, but a
  403 does **not** prove an expired cookie. A 2xx HTML response or malformed
  JSON is rejected, not treated as a successful API result.
- An authenticated browser session is still needed to obtain cookies;
  reuse without the original proxy remains **unverified/blocked** by the
  previous A/B network tests.
- The version header has been used in real successful BIO, LINK and FILE
  writes. Server-side conflict behavior, session-cookie rotation, complete
  resume lifecycle and other section write/restore remain unverified.
- Signed media URLs, native response bodies and session secrets are never
  logged by the transport. Private integration test evidence remains outside
  this public repository.

## Test evidence

- **Synthetic unit tests:** cookie-domain scoping, proxy binding, read
  decoding, 401/403/redirect/non-JSON handling, header version propagation,
  write gate, form encoding, `CurlMime` cleanup and uncertain-write non-retry.
- **Local HTTP transport test:** `ThreadingHTTPServer` parses actual multipart
  bodies for both text-only LINK and synthetic PDF FILE including native
  version headers. This test is conditional on the optional `curl_cffi`
  dependency; the base CI skips it if the extra is not installed.
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
- **Intermittent transport issue:** with the same login Proxy #4 and valid
  Chromium session, curl code 7 (connection failure before any HTTP status)
  appeared at times for **both** synchronous and asynchronous curl variants,
  including the SDK; other sessions returned 200 for all. Both variants
  could reach a public TLS test endpoint through the same proxy. Resource
  contention, network routing, and risk-based filtering remain unproven
  explanations. Do not silently retry a write when its outcome is unknown.
- These observations do not prove that matching JA4 alone determines
  upstream authorization, or that a proxy-free connection is viable.
