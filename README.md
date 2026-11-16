# Job Platform SDK

An unofficial, extensible Python SDK, CLI and optional HTTP API for managing job-seeker profiles and resumes across hiring platforms.

**Status: alpha.** The initial working provider is [104 Job Bank](https://www.104.com.tw/) in Taiwan. Providers for **Cake**, **Yourator**, and **Greenhouse** are planned, but **not implemented**.

## Provider capabilities

| Capability | 104 | Cake | Yourator | Greenhouse |
|---|---|---|---|---|
| Fresh login | Implemented (browser) | Planned | Planned | Planned |
| List resumes | Live tested | Planned | Planned | Platform-dependent |
| Read full resume | Live tested | Planned | Planned | Platform-dependent |
| Create resume | Browser flow tested; SDK not yet live-tested | Planned | Planned | Platform-dependent |
| Edit multiple fields locally | JSON Patch supported | Planned | Planned | Platform-dependent |
| Persist edits to website | **BIO only: experimental, website write unverified** | Planned | Planned | Platform-dependent |
| HTTP wrapper | Mock-tested | Planned | Planned | Planned |

The SDK does **not** claim successful persistence from local-only edits. Unsupported write operations return an explicit error.

## Install

Requires Python 3.11+, Chromium, and a display for headed browser automation.

```bash
python -m pip install -e ".[http]"
python -m patchright install --with-deps chromium
# Linux: run in an Xvfb display using xvfb-run -a
```

### Private environment variables for 104

- `JOB_PLATFORM_104_CREDENTIALS_FILE`: private UTF-8 key/value file containing `A`, `P`, `ISSUE_DATE`, `ISSUE_LOCATION`, and `ISSUE_METHOD`.
- `JOB_PLATFORM_104_PROXY_FILE`: private proxy list (`host:port:username:password`, one per line).
- `JOB_PLATFORM_API_TOKEN`: secret bearer token for the optional HTTP server (at least 24 characters).

All secrets are read at runtime. **Never commit actual credentials, proxy lists, session state, resumes, or raw browser logs.** The files in this repository contain no real user data.

## Python API

```python
import asyncio
from job_platforms.providers.tw104 import AuthConfig, FreshBrowserSession, Resume104Client

async def main():
    async with FreshBrowserSession(AuthConfig.from_env()) as browser:
        client = Resume104Client(browser.page)
        summaries = await client.list_resumes()
        if summaries:
            version = summaries[0]["versionNo"]
            resume = await client.get_resume(version)
            schema = await client.get_schema(version)

asyncio.run(main())
```

`client.create_resume()` creates **one real** resume through the website, then verifies the list delta. Do not call merely to test imports.

`client.plan_edit(version, changes)` applies RFC 6901 JSON Pointers to a **local copy** of the original response. `client.save_edit(plan)` currently supports *only* replacing `/bio/formData/bio/chi` and `/bio/formData/bio/eng` and preserves the unchanged sibling. It uses a versioned `PUT`, then reads the fields back for exact verification. **The upstream write has not yet passed a live integration test, so treat it as experimental.** Other sections still raise `UnsupportedWrite`.

## CLI

```bash
export JOB_PLATFORM_104_CREDENTIALS_FILE=/run/secrets/104-credentials
export JOB_PLATFORM_104_PROXY_FILE=/run/secrets/104-proxies
xvfb-run -a job-platform --provider tw104 probe
xvfb-run -a job-platform --provider tw104 list
xvfb-run -a job-platform --provider tw104 get VERSION_NO
xvfb-run -a job-platform --provider tw104 schema VERSION_NO
xvfb-run -a job-platform --provider tw104 plan VERSION_NO --patch-file changes.json
# Experimental: writes BIO only. The precondition is resumeTimestamp from a prior GET:
xvfb-run -a job-platform --provider tw104 apply VERSION_NO --patch-file changes.json \
  --if-match TIMESTAMP --confirm experimental-bio-write
# Explicitly creates a resume; no automatic retry after an uncertain outcome:
xvfb-run -a job-platform --provider tw104 create --confirm create-one
```

The `list` and `get` commands output **private** resume data; redirect them to protected files, never CI logs. The `probe` command reports metadata only.

## HTTP API

Start a local server with a strong `JOB_PLATFORM_API_TOKEN`:

```bash
xvfb-run -a job-platform-server --host 127.0.0.1 --port 8000
```

Routes:

- `GET /healthz`
- `GET /v1/providers` (provider capabilities)
- `GET /v1/{provider}/resumes`
- `GET /v1/{provider}/resumes/{resume_id}`
- `GET /v1/{provider}/resumes/{resume_id}/schema`
- `POST /v1/{provider}/resumes` (requires `Idempotency-Key`)
- `POST /v1/{provider}/resumes/{resume_id}/plan` (dry run only)
- `PATCH /v1/{provider}/resumes/{resume_id}` (**501 by default**; experimental BIO-only write when explicitly enabled)

Except `/healthz`, routes require `Authorization: Bearer <token>`. The HTTP process maintains a browser session while running. In-process idempotency is not durable across server restarts. Keep it on localhost behind an authenticated TLS reverse proxy if remote access is needed.

## GitHub Actions

`.github/workflows/probe.yml` is a manually triggered, **read-only** login/list-count smoke test using GitHub Actions Secrets. It is not a permanent API host. This workflow has **not** been validated on a GitHub-hosted runner.

## Internal architecture

```text
src/job_platforms/
  core/                 # capabilities, errors, JSON Patch
  providers/
    tw104/              # currently implemented browser provider
    cake/               # placeholder
    yourator/           # placeholder
    greenhouse/         # placeholder
  cli.py                # one-shot operations
  http_api.py           # long-running local API
tests/                  # synthetic fixtures only
```

The 104 provider uses same-origin browser `fetch()` for private My104 API calls. Simply copying browser cookies to `curl-cffi` caused HTTP 403 on some authenticated endpoints, even though `login/init` sometimes worked. An authenticated browser is the known-good baseline.

The 104 frontend uses `resumeByBlock` for sections including personal data, education, experience, job conditions, skill, certificates, language, projects, portfolio, biography, and referees. The correct write payloads and server-side read-back checks still need to be implemented and verified one section at a time.

**No guarantee is made that these unofficial integrations will continue to work if the upstream websites change.**

## Experimental BIO write protocol

The official 104 frontend sends `PUT /profile/ajax/resumeByBlock/bio?vno=VERSION_NO`
with JSON `{"blockValueList":{"bio":{"bio":{"chi":"...","eng":"..."}}}}`.
Its HTTP interceptor also propagates the **private `104-profile-ver` version header**
from a prior server response into all `PUT` / `POST` / `DELETE` requests.
The SDK now replicates this handshake in memory, without logging the header.

In preliminary live tests, PUT without this header returned HTTP 400, and the
remote biography remained unchanged. A later test with the header did not reach
the PUT because the fresh-login session was denied; **successful real persistence
is therefore still unverified**. Existing biographical data was compared against
its private backup and found unchanged.

For local HTTP writes, set `JOB_PLATFORM_104_ENABLE_EXPERIMENTAL_WRITES=1`
**only when you accept the risk of an unverified writer**. `PATCH` additionally
requires `If-Match: <resumeTimestamp>` and a unique `Idempotency-Key` of at
least 16 characters. The cache is in-process only; it does not survive server
restarts. On an ambiguous error, inspect the resume before attempting another
write. Neither this opt-in nor the presence of the API guarantees support for
all editable sections. The BIO writer currently supports one or both biography
language fields in a single PUT. Other fields return HTTP 501.

Run the unit test suite with `python -m unittest discover -s tests -v`.
This repository contains only synthetic fixtures, never account data or backup
content. Dedicated live integration scripts stay outside the public repository.
