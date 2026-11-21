# 104 sign-in and curl handoff troubleshooting

## Verified outcome and scope

On 2026-11-21 (Taipei), standalone headed Patchright under Xvfb completed
104 sign-in and MFA, verified the real resume overview, and closed Chromium.
A synchronous `curl_cffi.Session` on the same proxy then returned valid
resume-list JSON on two consecutive GETs. Both of these combinations passed:

| Browser | curl impersonation | Result after Chromium exit |
|---|---|---|
| Chrome for Testing 150.0.7871.124 | `chrome150` | Two overview GETs returned 200 with valid lists |
| Chromium 149 | `chrome150` | Two overview GETs returned 200 with valid lists |

The successful requests copied the browser's raw HTTP header names and
values from NetLog, including its complete Cookie header. These were
standalone probes. The SDK's existing login and HTTP adapters have not
been updated to this procedure. Success establishes this specific
read-only handoff; other endpoints and writes need their own verification.

## 1. Establish an authenticated browser baseline

1. Reuse a working authenticated browser on its original proxy when one
   exists. Confirm `GET /profile/ajax/overview` returns JSON containing
   `data.formData.overview` as an array.
2. For a fresh session, use headed Patchright under Xvfb and a fresh
   temporary persistent Chromium profile. Keep one explicit configured
   proxy for the whole login and handoff.
3. Start at the official link exposed by the 104 public home page,
   `https://login.104.com.tw/login`. Allow the official redirects to
   `signin.104.com.tw`. Direct visits to the sign-in host previously
   returned a visible account form while the page's own `login_init`
   returned 401. The linked entry returned init 200 in successful runs.
4. Wait for the actual visible account and password fields, allowing
   about 55 seconds per field. The user has observed account-form
   initialization taking about 40 seconds. Use visibility conditions
   and observe background requests.
5. Complete the account, password and official MFA flow using private
   runtime credentials. Verify the destination host before filling
   credentials. Follow the site's optional contact-update dialog
   without changing account contact details.
6. Wait for PDA redirects to settle, then issue the overview GET in the
   authenticated PDA page. A profile path is not a required final URL.
   Navigation cancellation or a destroyed execution context may occur
   during redirects. Inspect the resulting page and retry a read only
   after navigation settles.
7. Require a valid authenticated overview before testing curl. For editor
   work, separately GET the authorized resume and verify its identity.

A visible form, successful MFA response or HTTP 200 HTML alone does not
establish authenticated resume access. The standalone successful flow
observed the page's own init request. The SDK also issues an explicit
same-origin init gate, so its behavior differs.

## 2. Capture the actual successful request

Capture the same method, host, path and query that curl will use:
`GET https://pda.104.com.tw/profile/ajax/overview`.

- Use CDP request/extra-info and response events to associate the successful
  GET with its status, protocol and browser session.
- For HTTP/1.1 spelling and order, launch Chromium with
  `--log-net-log=PRIVATE_PATH` and `--net-log-capture-mode=Everything`.
  After Chromium closes and flushes the log, inspect the matching
  `HTTP_TRANSACTION_SEND_REQUEST_HEADERS` event. Select the target
  overview request and correlate its source/events if multiple reads exist.
- Keep the raw request line, ordered header names and values in memory
  during replay. Preserve the complete Cookie header exactly as sent
  on that GET. Exporting a cookie jar later can observe rotated values.
- CDP header mappings are useful for field/value comparison. Lowercasing
  their keys or sorting them loses raw spelling/order evidence.

NetLog Everything, raw HTTP bytes, TLS debug data and screenshots can
contain cookies, account information and credentials. Store them only
in a permission-restricted directory outside Git. Return sanitized
comparisons, never raw values.

## 3. Close Chromium and hand off to curl

1. Capture and verify the browser baseline, then close its context and
   confirm the profile's Chromium process has exited.
2. Create a synchronous `curl_cffi.requests.Session` using the original
   proxy, `trust_env=False`, `impersonate="chrome150"` and
   `default_headers=False`.
3. Supply the captured ordered header names and values, including Cookie.
   Keep them private and bound to the captured host and endpoint. Use
   `allow_redirects=False` so the replay cannot follow a redirect to
   another destination with copied credentials.
4. Send one overview GET. Record CONNECT and destination HTTP status
   separately. Require valid resume-list JSON.
5. If it succeeds, repeat the same read on the same curl session to verify
   reuse after Chromium exit. A reused connection may report CONNECT 0
   because that request did not create a new tunnel.
6. Reuse the successful HTTP session for the planned batch. For other
   endpoints, use their confirmed request contract, fresh revision state
   and updated session cookies. The captured Cookie header is a snapshot;
   this probe does not implement long-lived Set-Cookie rotation.

The essential configuration is:

```python
from curl_cffi.requests import Session

# Populate these privately from the successful browser request/session.
# captured_headers preserves the raw header spelling and order.
with Session(
    proxy=original_proxy,
    proxy_auth=original_proxy_auth,
    trust_env=False,
    impersonate="chrome150",
    default_headers=False,
    headers=captured_headers,
    timeout=20,
) as http:
    response = http.get(
        "https://pda.104.com.tw/profile/ajax/overview",
        allow_redirects=False,
    )
    response.raise_for_status()
    overview = response.json()["data"]["formData"]["overview"]
    if not isinstance(overview, list):
        raise ValueError("Authenticated overview response changed")
```

Private standalone reproduction scripts are under
`/workspace/104-private/integration-tests/`:

- `handoff-chrome150-netlog.py` used Chrome for Testing 150.
- `handoff-chrome149-raw-settled.py` used Chromium 149.

These scripts use private credential/proxy files. Recover the existing
private workspace when continuing this investigation. The public SDK
transport selection and write gates are documented in
[the hybrid transport contract](tw104-hybrid-transport.md).

## 4. Locate the failure before changing the session

| Evidence | Interpretation and next check |
|---|---|
| Curl error 5/6/7/28/35/60, or Chromium network error | Inspect proxy DNS, connection, CONNECT and TLS phases. Preserve the actual code. Curl 7 alone does not identify the failed phase. |
| CONNECT 407 | Check proxy authentication. |
| CONNECT 403 or 429 | The failure occurred while establishing the tunnel, before the destination GET. Honor Retry-After when present. A working existing browser connection does not prove a new tunnel will succeed. |
| CONNECT 200, then GET 401 or sign-in redirect | Check request cookie scope, rotation, official login completion and whether the browser can still read the same endpoint. |
| CONNECT 200, then GET 403 with only cf-ray/server edge headers | Denial source is unresolved. Inspect the response and compare the same browser request. |
| cf-mitigated: challenge | A Cloudflare Challenge Page was returned. Record the exact failing request and use the official browser verification flow. |
| Explicit Cloudflare block page or error 1020 | Record the block evidence and timestamp for site support. |
| Recognizable 104 application error | Check the application message and endpoint-specific permissions or initialization. |
| Destination 429 or account lockout | Stop repeated requests and honor the site's recovery instructions. |
| Browser still reads the list but curl fails | Preserve the authenticated baseline while diagnosing handoff, unless testing deliberate detachment. Check actual outbound fields and the failure phase. |
| Both authenticated paths fail | Inspect session validity and site responses before deciding to log in again. |

An SDK `AuthenticationRequired` may represent pre-account initialization,
a missing password form, failed post-login reads or HTTP rejection.
Prelogin diagnostics cover only the pre-account phase. An SDK
`UpstreamError` with status 0 may hide a curl connection error. Capture
the numeric code and safe response evidence at the transport boundary.

## 5. Inspect 403 pages and compare configured proxies

A healthy HTTPS proxy can still encounter destination-specific failures.
A neutral HTTPS check establishes general connectivity, not 104 access.

- Private records identify indices #1, #4 and #6 as previously reaching
  authenticated browser access; #6 completed the latest detached curl
  reads. Indices refer to the private proxy list used in those probes.
  They are historical observations, not permanent rankings.
- If an initialization or destination failure persists, compare configured
  proxies sequentially with the same official entry, browser settings,
  field waits and target endpoint. Create a fresh context per candidate.
  Keep the selected proxy fixed once its login succeeds.
- Inspect a 403 document's screenshot, visible error text, iframe hosts,
  challenge DOM and response headers. Inspect background failures too.
  One observed 104-branded 403 had one iframe without an observed
  Cloudflare challenge iframe or challenge marker.
- An iframe alone is insufficient to classify a challenge. A visible
  official login form can coexist with a denied PDA background request.
  Identify which host/path failed before deciding the next action.
- If one route fails and another succeeds under the same procedure, the
  result supports a route/IP-dependent difference. It does not identify
  whether Cloudflare or 104 made the decision. Respect explicit
  challenges, account restrictions and rate limits.
- With the current SDK, `JOB_PLATFORM_104_PROXY_PRIORITY` accepts an
  explicit 1-based index or comma-separated indices. Its automatic
  fallback ends after pre-account checks pass. Post-account failures
  require separate diagnosis.

Fresh SDK attempts already create temporary profiles. Preserve a working
context when diagnosing a curl-only failure. Reauthenticate after
established session expiry, or when a new browser is required after
detachment. Never delete the user's own browser profile.

## Evidence and remaining uncertainty

| Observed case | Result |
|---|---|
| Direct sign-in host on two proxies | Form visible, page init 401; changing those two routes did not resolve it |
| Official login link, headed browser | Init 200, password/MFA completed, valid overview 200 |
| Curl while browser was open in one run | CONNECT 429 surfaced as curl error 7; no destination GET |
| Curl after browser exit in another run | CONNECT 200, destination GET 403 |
| Chromium 149 + chrome150, mapped/lowercased copied fields | Header names and values matched, but GET returned a confirmed challenge |
| Chrome 150 + chrome150, raw NetLog headers | Two valid overview GETs after browser exit |
| Chromium 149 + chrome150, raw NetLog headers | Two valid overview GETs after browser exit |

The successful raw comparison found equal request lines, header-name
sets, values and Cookie header. Curl moved Connection to the final
header position; the remaining spelling and relative order matched.

In captured Chrome 150 and curl ClientHello messages, cipher suites,
supported groups, ALPN offers and extension ID sets matched after
excluding GREASE IDs. Extension order and session_ticket (35) length
differed. The browser's last PDA handshake was not conclusively linked
to the overview connection, so this is not a connection-specific
fingerprint comparison.

Version mismatch alone did not prevent the successful Chromium 149 run.
Fresh sessions and header representation also changed between runs.
Neither the cause of earlier challenges nor the effect of closing
Chromium on a previous CONNECT 429 has been isolated. Read-only success
does not establish live write compatibility or long-term session stability.

## Handoff record

Record UTC time, proxy index, browser/curl versions, stage, host/path
without query, method, CONNECT status, destination status, network code,
response category and Cloudflare signal. Report whether authenticated
JSON validation passed and whether Chromium was closed. For comparisons,
report field names and equality counts without values.

Keep credentials, account/resume identifiers, cookies, proxy endpoints,
MFA data and raw traces private. If a mutation may already have been
submitted, reconcile it with a fresh independent GET before any retry
or restoration.

## References

- [Cloudflare Challenge response detection](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/)
- [Cloudflare 403 troubleshooting](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-403/)
- [Cloudflare error 1020](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1020/)
- [libcurl error codes](https://curl.se/libcurl/c/libcurl-errors.html)
