# 104 sign-in and transport troubleshooting

Use this runbook for authorized, read-only diagnosis. Keep one working
browser session open until you have verified the intended HTTP path.
Start by recording the failing stage, then change one variable at a time.

## 1. Locate the failure

1. **Existing session:** use the existing browser on its original proxy.
   Read `GET /profile/ajax/overview` and, for editor work, read
   `GET /profile/ajax/resumeByBlock` for the authorized test resume.
   Require the expected authenticated JSON and resume identity. A rendered
   page or an HTTP 200 alone is insufficient. If an editor control is
   missing while both reads pass, investigate the editor route/initialization
   and its own network requests. Preserve the working session.
2. **Fresh login:** identify the stage in `prelogin_diagnostics`:
   `proxy_config`, `chromium_launch`, PDA navigation, official
   `signin_navigation`, `signin_hostname`, `signin_form`, or `login_init`.
   The SDK already tries the official sign-in flow on the same proxy
   after a PDA *entry* 403 without a challenge signal. Test authenticated
   PDA reads separately after sign-in.
3. **After prelogin:** identify account validation, password form/submit,
   MFA, return to PDA, or authenticated overview. Use the browser's Network
   panel and the official UI to check the result at that step. The
   prelogin diagnostics cover the stages before account entry only.
   `AuthenticationRequired` also covers an unavailable password step,
   failed post-login access, and some curl HTTP failures. Use the
   underlying response before deciding to sign in again.

## 2. Interpret the evidence

| Evidence on the failing request | What it supports | Next action |
|---|---|---|
| No destination HTTP response; Chromium `ERR_PROXY_CONNECTION_FAILED` or `ERR_TUNNEL_CONNECTION_FAILED`, or curl exit 5/6/7/28/35/60 | Proxy DNS, target DNS, connection, timeout, or TLS failure. Curl 7 can refer to either the host or proxy. | Check the failed phase, runner egress, proxy config, DNS, or certificate trust. Compare a neutral HTTPS control and the official sign-in host on the same proxy. |
| HTTP 407, or CONNECT itself returns 403 | Proxy authentication or proxy tunnel policy. | Check proxy credentials and policy for that destination. Use another configured, permitted route if the proxy transport is unavailable. |
| `cf-mitigated: challenge`, including on HTTP 200 | Cloudflare Challenge Page. | Use the normal browser flow if the site offers a user-facing check. If it persists, stop SDK probes and record the evidence for 104 support. |
| Explicit Cloudflare block page, such as Cloudflare error 1020 | Cloudflare security denial. | Stop SDK probes. Retain a timestamp and Ray ID privately for 104 support. |
| Destination HTTP 403 with only `cf-ray` or `server: cloudflare`, or with no identifiable response marker | Denial source is unresolved. Edge headers identify the response path. Even an unbranded 403 can come from Cloudflare in some cases. | Inspect the response category and redirect target locally. Compare official sign-in, the browser reference read and the same curl read. If the evidence stays inconclusive, report it as such. |
| Recognizable 104 application JSON error or official account message | The evidence points to 104 application behavior. The specific error may indicate a session, MFA, account, permission or endpoint issue. | Follow the indicated 104 flow. Compare a known-good authenticated read with the failing endpoint before deciding that the whole session is invalid. |
| Known authenticated browser read now consistently returns 401 or redirects to the official sign-in page | The current browser session likely needs renewal. | Reauthenticate once using the normal flow on the known working route. Recheck authenticated JSON before resuming. |
| HTTP 429, lockout, explicit policy denial, or unresolved challenge | Access is limited or requires user/site action. | Stop retries and proxy comparisons. Honor `Retry-After` if provided and resume when the limit or denial is resolved. |

See [Cloudflare Challenge responses](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/),
[Cloudflare 403](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-403/),
[Cloudflare 1020](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1020/),
and [libcurl error codes](https://curl.se/libcurl/c/libcurl-errors.html).

## 3. Decide whether to start a fresh profile or use another proxy

- **Fresh SDK login already uses a clean temporary Chromium profile per
  attempt.** Never delete the user's browser profile. If a manually restored
  context on a working connection appears stale, preserve it and compare one
  clean SDK session on the same proxy. A generic 403 or curl-only failure
  does not justify replacing an authenticated browser context.
- **Proxy comparison tests connectivity first.** Use only configured,
  trusted proxies. On the same runner, run one unauthenticated request to an
  approved neutral HTTPS endpoint and one to `https://signin.104.com.tw/`
  per candidate. A successful neutral request checks the proxy route in
  general. The official sign-in result checks the intended destination and
  may differ by client. Compare browser navigation before entering account
  details. Continue to a different index only for a diagnosed proxy
  configuration, connection or route failure. Pause the proxy comparison on
  a destination 403 with unresolved provenance and use the evidence table.
  Stop on site denials or account/MFA errors and report the stage.
- **Use one explicit index for each diagnosed fresh attempt.** Set
  `JOB_PLATFORM_104_PROXY_PRIORITY` to one 1-based line number from the
  private proxy file. Leaving it unset lets the SDK advance through its
  default list on pre-account failures. It selects a proxy once the
  pre-account checks pass and keeps that proxy for account, password, MFA
  and PDA access. After a successful login, keep the original proxy attached
  to its browser and HTTP sessions. A different route starts a new session.

For the unauthenticated connectivity checks, use standalone curl with the
proxy configuration in a private, permission-restricted curl config file
outside Git. The config should contain only the explicit proxy and its
credentials and disable `NO_PROXY` bypass (curl `noproxy = ""`). Pass
each public URL once and record the exit status as well as CONNECT and
destination HTTP codes. Keep stderr private. The command does not follow
redirects or load the user's default curl config. CONNECT 200 confirms the
proxy opened a tunnel. Curl exit 0 confirms an HTTP exchange completed and
can accompany a destination 403. Neither confirms sign-in.

```sh
curl -q --config "$TW104_PRIVATE_CURL_CONFIG" --silent --show-error \
  --connect-timeout 10 --max-time 20 --output /dev/null \
  --write-out 'connect=%{http_connect} http=%{response_code}\n' \
  https://signin.104.com.tw/
```

For the SDK, choose the index established by those checks and run the
normal browser read. In this example, `TW104_PROXY_INDEX` contains the
selected 1-based index and the SDK credential and proxy file paths are
already configured privately.

```sh
JOB_PLATFORM_104_PROXY_PRIORITY="$TW104_PROXY_INDEX" job-platform --transport browser list
```

This CLI command owns a fresh login. Use the Python flow below if the
goal is to compare browser and curl on the *same* login. Omit the separate
CLI invocation in that case.

## 4. Compare browser and curl on the same login

Use the SDK's `curl_cffi` transport for the authenticated phase
(`pip install '.[curl]'`). The handoff keeps 104-domain cookies in memory
and uses the original login proxy. Standalone curl above is a connectivity
probe and does not need account cookies.

```python
from job_platforms.providers.tw104 import AuthConfig, FreshBrowserSession


async def read_only_comparison(test_resume_id):
    async with FreshBrowserSession(AuthConfig.from_env()) as session:
        browser = await session.resume_client(transport="browser")
        http = await session.resume_client(transport="curl_cffi")

        await browser.list_resumes()
        await http.list_resumes()

        await browser.get_resume(test_resume_id)
        await http.get_resume(test_resume_id)
```

Keep the resume ID and response data private. For a failing read, compare
the **same** method, path and query inputs, in the same time window. If the
browser read succeeds and curl fails, keep the browser and classify the HTTP
handoff failure. Check that the expected session and proxy were used and
record the client versions, the exact failing endpoint category and sanitized
response evidence. One endpoint's success does not establish another's.
The SDK currently has a fixed curl client profile. A browser/curl version
difference by itself does not explain a 403. If both clients fail,
classify the observed responses using the table before replacing the session.

If both paths work, reuse them for the rest of the batch. A second
`await session.http_transport()` provides an independently reading HTTP
session from the same login. If you intentionally test detachment, create
any verifier before the final `session.http_transport(close_browser=True)`.
Then recheck the required GET using the detached HTTP transport before any
write. Closing Chromium removes the same-session browser fallback. See the
[hybrid transport contract](tw104-hybrid-transport.md) for lifecycle and
write gates.

## Live check on 2026-11-21 (Taipei)

A read-only check used the SDK's existing Patchright and `curl_cffi`
backends with a configured proxy in the same runner. No resume write was
sent.

| Observed stop point | Result |
|---|---|
| Fresh browser sign-in and same-endpoint GET | Sign-in and MFA completed. Browser `GET /profile/ajax/overview` returned HTTP 200 and passed SDK shape validation. |
| Attached `curl_cffi` GET of the same overview | The standard same-proxy handoff attempted the same GET. Curl reported code 7 before an HTTP response, which the SDK surfaced as `UpstreamError`. |
| Unauthenticated standalone curl controls on two configured proxies | Both had CONNECT 200 and neutral HTTPS 200. Official sign-in and PDA returned destination HTTP 403 on both. This shows the proxy tunnels worked for standalone curl. The source of the destination 403 was unconfirmed. |
| Fresh-browser attempts to check detached mode | One stopped during official sign-in navigation with `ERR_ABORTED`. Another received a PDA entry 403 with edge headers, then HTTP 200 HTML at the official sign-in page and HTTP 401 JSON from `login_init`. Both stopped before account entry and before handing off to curl. |

The first run verified browser authentication and isolated a curl connection
failure on the same endpoint. This round did not establish current attached
or detached curl access. Earlier successful detached reads and reversible
operations are documented in the [hybrid transport test evidence](tw104-hybrid-transport.md#test-evidence).
A curl failure before HTTP, a destination 403 after CONNECT, and a
`login_init` 401 require separate diagnoses. Treat the last one as a
pre-account failure, even if the login page loaded successfully. A browser
navigation abort also needs its own diagnosis. Record the resulting page
and SDK stage without inferring credential rejection or an HTTP block from
the abort alone.

### Follow-up connection controls

On two configured proxies, `curl_cffi` itself completed CONNECT and a
neutral HTTPS GET with either the SDK's credential-in-URL format or
separate proxy credentials. Both forms returned CONNECT 200 and HTTP 200.
That verifies the proxy authentication format against the control endpoint.
It leaves the earlier destination-specific curl code 7 unexplained.

Two attempts to verify detached mode stopped before account entry. The
normal attempt saw PDA entry 403 with edge headers, then official sign-in
HTML 200 with the account input missing. In a separate attempt, observing
the form for eight additional seconds still produced no account input.
The page's own `login_init` returned HTTP 401 JSON. This result does not
support extending the form timeout as a fix. When the same condition
occurs, check the browser's background sign-in requests before changing
curl settings. Resume detached verification once the normal sign-in flow
again reaches an authenticated browser overview.

### Standalone headed browser check

A standalone probe ran headed Patchright under Xvfb without importing
the SDK. It waited for the official account field to become visible,
with a 55-second budget to account for slower renders. The flow relied
on the page's own initialization instead of issuing an extra
`login_init` request.

On the live attempt, the account field appeared about one second after
the visibility wait started. A PDA background request had already
returned HTTP 403 with `cf-mitigated: challenge`. The probe stopped
before credential entry. It did not reach the authenticated overview
or curl handoff. In this case a visible sign-in form was compatible
with a challenge on a separate PDA request.

A loopback control used the same standalone libraries and confirmed
that headed Chromium could establish a synthetic HttpOnly session,
close completely and leave `curl_cffi` able to read the authenticated
overview with HTTP 200. This control exercised the handoff mechanics
without the third-party proxy or 104 rules.

A follow-up started at the official sign-in page directly. The page
returned HTTP 200 and the account field became visible after about
1.2 seconds. The page's own `login_init` returned HTTP 401. The probe
timed out during the account step, before reaching the password step
or making an authenticated overview request.

### Proxy and entry-route comparison

Two configured proxies were checked with fresh headed Chromium sessions
on the same runner. Direct official sign-in returned HTTP 200 and
displayed the account form on both routes. On both routes the page's
own `login_init` returned HTTP 401, with no challenge marker observed
on these responses. No account credentials were entered. This shows
that changing between these two proxy routes did not resolve the
pre-account 401.

The SDK uses a fresh persistent Chromium context, begins at the PDA
entry page, may visit PDA profile before official sign-in, and runs
an explicit same-origin `login_init` gate before account entry. The
standalone direct probe uses a fresh ordinary browser context and
observes the page's own init request. A separate same-proxy probe used
the SDK-style context and initial PDA route, but received HTTP 403 on
that first document without a challenge marker and stopped there.
It did not exercise the SDK's official sign-in fallback. The earlier
successful SDK browser login saw init 200. The available comparisons
do not isolate a cause for the different results.

### Live browser success via the official login link

The public 104 home page links to `https://login.104.com.tw/login`.
On a configured route, starting from that link led to a 200
`login_init`, successful password and MFA steps, and a return to PDA.
Waiting for the PDA profile navigation to finish allowed headed
Patchright, without the SDK, to read a valid resume list from
`GET /profile/ajax/overview` on two runs.

- In the first run, asynchronous `curl_cffi` on the same route and
  with the same approved session returned curl error 7 and no HTTP
  response. An immediate browser recheck on that session returned 200.
- On a separate fresh login with the same route and endpoint,
  synchronous `curl_cffi` established proxy CONNECT (200), then
  received a destination HTTP 403 with Cloudflare edge headers and no
  observed challenge marker. The response body was not retained, so
  the denial source remains unresolved. Chromium was not deliberately
  detached for either comparison.

In the preceding three-route comparison, two routes reached a 200 PDA
entry page but stopped during sign-in with 401, before obtaining an
authenticated list. The other route returned a first-document 403
with a 104-branded error page. The page had one iframe, with no observed
Cloudflare challenge iframe, challenge DOM or challenge header. Keep
such a 403 distinct from a confirmed challenge on a background request.
A generic `403` or `cf-ray` alone does not establish an IP block.

### Browser closed before the curl request

A later live run verified a valid browser overview (HTTP 200), retained
the scoped session state in memory, closed Chromium and confirmed that
its profile process exited. A fresh `curl_cffi` client on the same
configured route then received CONNECT 200, negotiated TLS 1.2 and
HTTP/1.1, and sent the overview GET. The destination response was
HTTP 403 with Cloudflare edge headers and no observed challenge
marker. Curl did not obtain a resume list. Chromium had likewise used
TLS 1.2 and HTTP/1.1 for its successful GET.

An earlier curl attempt while Chromium was still open got 429 during
CONNECT. These are separate runs. The later success establishing the
tunnel does not prove browser connection occupancy caused the earlier
429. The source of the destination 403 is still unconfirmed.

### Same-session header comparison and confirmed challenge

A live headed-browser GET returned a valid overview with HTTP 200.
After Chromium exited, the independent curl client used the same route,
matched the browser's ordinary Accept, Accept-Language and same-origin
Referer, and received CONNECT 200. Its request reached the destination
over HTTP/1.1 and TLS 1.2. The overview response was HTTP 403 HTML with
both `cf-mitigated: challenge` and Cloudflare challenge markup.

The two outbound requests had the same 17 non-Cloudflare cookie names,
with 16 equal values. Accept-Encoding differed. Chromium also sent
its usual User-Agent, connection, Fetch Metadata and client hints.
Only field names, aggregate equality counts and response indicators
were retained. The observations establish an active challenge on
this curl request. They do not isolate which signal triggered it.
Follow the challenge guidance above before any further direct-client
testing.

### Impersonation with identical outbound HTTP headers

A real-site read used headed Chromium 149 to authenticate and obtain a
valid overview. CDP captured the successful GET's complete outbound
headers in memory, including its exact Cookie header. After Chromium's
profile process exited, curl_cffi used the same proxy, chrome150
impersonation, default_headers=False, and those captured headers.
Chrome 150 was selected because the installed curl_cffi has no Chrome
149 impersonation profile.

The curl debug callback confirmed equal header-name sets, equal values
for every captured header and a byte-identical Cookie header value.
CONNECT returned 200. TLS 1.2 and HTTP/1.1 negotiated successfully.
The overview GET returned 403 with cf-mitigated: challenge and did not
yield a resume list. No account or resume mutation was attempted.
This establishes equality of HTTP header fields in this comparison.
TLS handshake details, profile version and connection state were not
proven identical. It does not identify the challenge trigger.

### Successful standalone handoff using Chrome 150 and raw request headers

The next authorized real-site run succeeded. Headed Patchright under Xvfb
used Chrome for Testing 150.0.7871.124 with the established official
login entry, completed password and MFA, and verified the overview.
Chromium NetLog capture mode Everything retained its actual HTTP/1.1
request line and header lines privately. After closing Chromium and
confirming its profile process had exited, a synchronous curl_cffi
Session on the same proxy used chrome150 impersonation,
default_headers=False and those raw header names and values, including
the complete original Cookie header in memory.

CONNECT returned 200. The first and second GETs of the real overview
both returned HTTP 200 with valid resume-list JSON. The second GET
reused the curl session. No SDK or test server was used.

Raw comparison established equal request lines and equal HTTP field
names/values. Curl moved Connection from the second header to the
last position. All other header spellings and their relative order
matched. This means the raw header block was not byte-identical.

Captured PDA ClientHello messages had equal cipher-suite lists,
supported-group lists and ALPN offers (h2 and http/1.1), after
excluding GREASE IDs. Their extension ID sets matched, while extension
order differed. The last captured browser PDA ClientHello was 2013
bytes and curl's was 1821 bytes. Among their shared extensions,
session_ticket (35) had a different length. The browser's last PDA
handshake was not conclusively associated with the overview connection,
so these observations characterize captured handshakes, not an exact
connection-to-connection proof.

Several variables changed together from the previous failed run:
browser major version, raw header spelling/order input and a later
fresh login/session. This success does not isolate the cause of the
earlier challenge or guarantee future acceptance. NetLogs, TLS debug
chunks, screenshots and request bytes contain sensitive session data
and remain outside Git. The standalone reproduction script remains
in the private integration-tests workspace as handoff-chrome150-netlog.py.

## What to leave in the handoff

Record UTC time, proxy index, client/version, stage, host and path without
query, method, proxy CONNECT and destination HTTP status or network error,
redirect host/path without query, response type, and the Cloudflare signal.
For example, record `edge_headers`, `challenge`, `explicit_block` or
`unconfirmed` and whether each authenticated read passed. These are runbook
categories. The SDK uses only `edge_headers`, `challenge` and
`unconfirmed` in prelogin diagnostics. Library exceptions can collapse
several causes into one error. For example, curl connection error 7 is
reported as an SDK `UpstreamError` with status 0. Capture the numeric
error code at the curl client boundary if the SDK reports status 0. If a
response exists, capture its HTTP status, body category and Cloudflare
signal before the SDK converts it into an exception. Keep raw headers,
body, URLs and exception text out of diagnostic output.

Share only sanitized fields. Keep raw headers, bodies, traces, proxy
endpoints, credentials, cookies, MFA data and resume identifiers private.
If a mutation may already have been sent, stop write attempts and use an
independent GET to reconcile the actual state before any restore or retry.
