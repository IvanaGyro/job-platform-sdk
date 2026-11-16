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
| Persist edits to website | **BIO live-tested; other mapped fields experimental** | Planned | Planned | Platform-dependent |
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
            bio_section = await client.get_section(version, "bio")

asyncio.run(main())
```

`client.create_resume()` creates **one real** resume through the website, then verifies the list delta. Do not call merely to test imports.


`client.plan_edit(version, changes)` applies RFC 6901 JSON Pointers to a **local
copy** of the original response. `client.save_edit(plan)` supports:

- `/bio/formData/bio/chi` and `/bio/formData/bio/eng`. The BIO PUT has passed
  a real modified-value write, exact read-back, restore and read-back test.
- `/certificate/formData/certificate/others` and
  `/certificate/formData/certificate/certificates`. The CERTIFICATE PUT is
  frontend-source-mapped and unit-tested but **not yet live-tested**. It
  requires the native certificate section to be populated.
- `/sidebar` can replace the complete native sidebar list **only to reorder
  existing entries**. The writer sends the official source-observed
  `{"blockValueList":{"sidebar":[{"id":"..."}]}}` shape, rejects additions,
  removals and changes to entry metadata, then verifies the resulting ID order.
  **Source-mapped and synthetic-tested; real 104 write not yet verified.**
- `/jobCondition/formData/jobCondition/FIELD` can replace the 19 native
  preference fields. Selected nested leaf paths (job title, date and salary
  components) are also accepted. The source-mapped writer converts select
  objects to their upstream `value`, category objects to their `no`, and
  handles the 104-specific salary and onboarding branches. Unrecognized
  shapes are rejected before any request. **Synthetic-tested, not live-tested.**
  Theme changes use a distinct upstream `layout` operation and are not yet
  implemented.
- `/experience/formData/seniority/value` updates only the overall seniority
  selection, using an independent 104 `experience.seniority` PUT. It never
  submits or overwrites the individual `experiences` list. **Synthetic-tested,
  not live-tested.** Other experience fields and record CRUD remain unsupported.

### Experimental 104 skill records (CRUD)

The 104 editor uses *distinct* POST, PUT and DELETE requests for skills, not
a full-array replacement in JSON Patch. The SDK exposes
`Resume104Client.mutate_skill()`, and the optional HTTP service exposes:

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/v1/tw104/resumes/{resume_id}/skills` | Create a skill |
| PUT | `/v1/tw104/resumes/{resume_id}/skills/{position}` | Update its name, description or tags |
| DELETE | `/v1/tw104/resumes/{resume_id}/skills/{position}` | Delete the position |

`position` is the **1-based upstream `sort` value**, not a UUID.
Create accepts a JSON object with a nonempty `name` string and optional
`desc` string and `tag` list of `{"text":"...","value":"..."}` objects.
Update accepts any nonempty subset of these three fields. DELETE has no body.
All writes require the API Bearer token, experimental opt-in, an
`If-Match: <resumeTimestamp>` header, and an `Idempotency-Key` of at
least 16 characters. Each operation reads back the full skill list and
checks that unrelated records are unchanged. Do **not** blindly repeat an
ambiguous failure or use stale positions. **Synthetic-tested only; real
104 writes are not yet confirmed.** Ordering uses a different upstream
operation and is not yet implemented.

Each modified section is written once with sibling fields preserved, then
verified by reading back. **Multiple sections are not atomic**: if a later
section fails, `PartialWriteError` reports earlier verified sections and the
failed section without exposing resume data. Unmapped paths and operations are
rejected before any write.

## CLI

```bash
export JOB_PLATFORM_104_CREDENTIALS_FILE=/run/secrets/104-credentials
export JOB_PLATFORM_104_PROXY_FILE=/run/secrets/104-proxies
# Optional: restrict connection attempts to a previously tested proxy index.
# Avoids lengthy retries across proxies during diagnosis:
export JOB_PLATFORM_104_PROXY_PRIORITY=4
xvfb-run -a job-platform --provider tw104 probe
xvfb-run -a job-platform --provider tw104 list
xvfb-run -a job-platform --provider tw104 get VERSION_NO
xvfb-run -a job-platform --provider tw104 schema VERSION_NO
xvfb-run -a job-platform --provider tw104 get-section VERSION_NO bio
xvfb-run -a job-platform --provider tw104 plan VERSION_NO --patch-file changes.json
# BIO has a verified writer; CERTIFICATE, SIDEBAR, JOBCONDITION and EXPERIENCE seniority remain experimental. Require resumeTimestamp:
xvfb-run -a job-platform --provider tw104 apply VERSION_NO --patch-file changes.json \
  --if-match TIMESTAMP --confirm experimental-bio-write
# For certificate, sidebar, job-condition or multi-section updates, use:
# --confirm experimental-section-write
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
- `GET /v1/{provider}/resumes/{resume_id}/sections/{section}`
- `POST /v1/{provider}/resumes` (requires `Idempotency-Key`)
- `POST /v1/{provider}/resumes/{resume_id}/plan` (dry run only)
- `PATCH /v1/{provider}/resumes/{resume_id}` (**501 by default**; experimental BIO / CERTIFICATE / SIDEBAR / JOBCONDITION write when explicitly enabled)

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

For the upstream block naming and exact version-header handshake, see
[104 editor contract notes](docs/tw104-upstream-contract.md). For the complete 104-only implementation and
validation checklist, see [editor coverage inventory](docs/tw104-editor-coverage.md).

The 104 provider uses same-origin browser `fetch()` for private My104 API calls. Simply copying browser cookies to `curl-cffi` caused HTTP 403 on some authenticated endpoints, even though `login/init` sometimes worked. An authenticated browser is the known-good baseline.

The 104 frontend uses `resumeByBlock` for sections including personal data, education, experience, job conditions, skill, certificates, language, projects, portfolio, biography, and referees. The correct write payloads and server-side read-back checks still need to be implemented and verified one section at a time.

**No guarantee is made that these unofficial integrations will continue to work if the upstream websites change.**

## Experimental BIO write protocol

The official 104 frontend sends `PUT /profile/ajax/resumeByBlock/bio?vno=VERSION_NO`
with JSON `{"blockValueList":{"bio":{"bio":{"chi":"...","eng":"..."}}}}`.
Its HTTP interceptor also propagates the **private `104-profile-ver` version header**
from a prior server response into all `PUT` / `POST` / `DELETE` requests.
The SDK now replicates this handshake in memory, without logging the header.


**BIO live verification:** a PUT without `104-profile-ver` returned HTTP 400.
With that header an identical-content PUT returned HTTP 200. A subsequent
bounded test changed one punctuation character, read back the **exact**
new value, restored the original, and again verified an exact match against
the protected private backup. Test contents were never logged or committed.

**CERTIFICATE remains experimental:** the update request structure is
confirmed from 104 frontend JavaScript, but the examined resume returned an
empty certificate formData. The SDK rejects unknown/missing section shapes
instead of guessing how to create a new section.

For local HTTP writes, set `JOB_PLATFORM_104_ENABLE_EXPERIMENTAL_WRITES=1`
**only when you explicitly accept the risks of direct upstream writes**. `PATCH` additionally
requires `If-Match: <resumeTimestamp>` and a unique `Idempotency-Key` of at
least 16 characters. The cache is in-process only; it does not survive server
restarts. On an ambiguous error, inspect the resume before attempting another
write. Neither this opt-in nor the presence of the API guarantees support for
all editable sections. BIO updates are verified and CERTIFICATE/SIDEBAR/JOBCONDITION updates are
experimental; supported sections may be combined in one plan, with non-atomic per-section
PUT requests. Other fields return HTTP 501.

Run the unit test suite with `python -m unittest discover -s tests -v`.
This repository contains only synthetic fixtures, never account data or backup
content. Dedicated live integration scripts stay outside the public repository.
