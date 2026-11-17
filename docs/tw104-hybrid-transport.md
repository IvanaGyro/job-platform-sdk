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
- JSON, URL-encoded form fields and bounded multipart files are supported by
  source-based implementation and synthetic tests. No automatic retry occurs;
  ambiguous network failures during writes raise `VerificationError`.
- A 401, 403 or redirect is an authentication/network-risk failure, but a
  403 does **not** prove an expired cookie. A 2xx HTML response or malformed
  JSON is rejected, not treated as a successful API result.
- An authenticated browser session is still needed to obtain cookies;
  reuse without the original proxy remains **unverified/blocked** by the
  previous A/B network tests.
- Multipart profile version, real write headers, server-side conflict rules,
  cookie rotation and write/restore must still be verified against 104.
- Signed media URLs, native response bodies and session secrets are never
  logged by the transport. Private integration test evidence remains outside
  this public repository.

## Test evidence

- **Synthetic unit tests:** cookie-domain scoping, proxy binding, read
  decoding, 401/403/redirect/non-JSON handling, header version propagation,
  write gate, form encoding and uncertain-write non-retry.
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
- **New transport writes:** only synthetic-tested. A real reversible BIO
  PUT/read-back/restore smoke test is separate and must not be marked
  complete unless the private test log confirms it.
- These observations do not prove that matching JA4 alone determines
  upstream authorization, or that a proxy-free connection is viable.
