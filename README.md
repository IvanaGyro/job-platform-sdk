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
- JOB_PLATFORM_IDEMPOTENCY_DB: optional path to protected SQLite storage for durable duplicate-request prevention; use an existing non-world-writable directory outside the repository.

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
  Theme changes use a distinct upstream `layout` operation; the native
  theme API is now source-mapped as an experimental 104-only operation.
- `/experience/formData/seniority/value` updates only the overall seniority
  selection, using an independent 104 `experience.seniority` PUT. It never
  submits or overwrites the individual `experiences` list. **Synthetic-tested,
  not live-tested.** Independent EXPERIENCE record CRUD is documented below.

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
104 writes are not yet confirmed.** Adjacent ordering is available as a
separate experimental native swap operation.

### Experimental 104 education records (CRUD)

The SDK also supports `Resume104Client.mutate_education()` for one
record at a time. The HTTP API exposes:

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/v1/tw104/resumes/{resume_id}/educations` | Add a school |
| PUT | `/v1/tw104/resumes/{resume_id}/educations/{position}` | Update fields |
| DELETE | `/v1/tw104/resumes/{resume_id}/educations/{position}` | Delete a school |

Here `position` is the **current 1-based 104 `sort` number**.
Creation currently requires every mapped 104 native school field except
`sort`; updating accepts a nonempty subset of native fields, excluding
`sort`. Both send 104-specific flattened selectors and department ID lists.
Only the intended record is submitted, with unrelated records checked in the
read-back. All HTTP mutations require the API Bearer token, experimental opt-in,
`If-Match` and an `Idempotency-Key` of at least 16 characters. **Synthetic
tests passed; the writer is not yet live write-verified.** This is not a
generic cross-platform education model. Adjacent ordering is available as
a separate experimental native swap operation.

### Experimental BIO creation and clearing

The existing 104 BIO HTML editor supports a previously live-verified PUT
for both chi and eng HTML strings. Two separate actions are now mapped:

| HTTP method | Endpoint | Action |
|---|---|---|
| POST | /v1/tw104/resumes/{resume_id}/biography | Create empty BIO block |
| DELETE | /v1/tw104/resumes/{resume_id}/biography | Clear the whole BIO block |

Python callers use Resume104Client.mutate_bio(..., action, ...), with
action create or clear. The CLI supports:

    job-platform bio-action VERSION_NO create --changes-file private-chi-eng.json --if-match TIMESTAMP --confirm experimental-bio-action-write
    job-platform bio-action VERSION_NO clear --if-match TIMESTAMP --confirm experimental-bio-action-write

The public frontend module 8d88 uses POST with nested BIO data,
and DELETE with a different nonnested body. These cannot be replaced by
the already-verified PUT structure. The SDK refuses first creation of an
already initialized block, clearing of empty blocks, and unknown HTML
fields. Create requires both language fields, at least one nonempty.

Both new actions remain **synthetic-tested only**. They require explicit
experimental write opt-in, version matching and HTTP idempotency. We did
not clear or create any real 104 BIO section. A native DELETE could affect
section presentation; verify it on an expendable test resume first.

### Experimental 104 REFERRER CRUD

A 104 recommendation contact is a repeating record with five fields:
name, company, position, email and tel. Updates and deletes address the
current 1-based upstream sort value, not an array index. The 104-specific
Python method is Resume104Client.mutate_referrer(), and the optional
experimental HTTP endpoints are:

| Method | Endpoint | Action |
|---|---|---|
| POST | /v1/tw104/resumes/{resume_id}/referrers | Add one referrer |
| PUT | /v1/tw104/resumes/{resume_id}/referrers/{position} | Update fields |
| DELETE | /v1/tw104/resumes/{resume_id}/referrers/{position} | Delete record |

The CLI exposes job-platform record VERSION_NO referrer ACTION with its
usual confirmation, prior resumeTimestamp and private JSON changes file.
All writes require experimental opt-in, an API bearer token, If-Match and
Idempotency-Key for HTTP, and independent read-back. An ambiguous remote
write is not retried automatically.

The official frontend module f5d8 sends distinct POST/PUT/DELETE requests,
and converts the UI company selector to text in the native wire payload.
For first creation into empty formData the SDK reads the first
optionsReferrerTheme from the current 104 options endpoint, instead of
guessing a default numerical theme.

A fresh authenticated **read-only** check confirmed an empty referrer
formData on the designated test resume, two theme options, and five
field maximum lengths (name 30, company 35, position 20, email 50, tel 50).
The writer enforces those limits and requires at least one contact method.
This adapter and its HTTP routes are **synthetic-tested only**: no real
104 referrer has been added, modified or deleted. The first POST and
last DELETE are not live verified. Do not use real people's contact data
as fixtures or log them.

### Experimental 104 INFO resume fields

The existing `plan_edit()` / `save_edit()` and experimental HTTP PATCH
support **individual replacements** for known fields under
`/info/formData/info/{field}`,
`/info/formData/addOn/{field}`, and
`/info/formData/summaryDisplay`.

The outgoing payload is reconstructed from the official 104 frontend
`c40f.postData()`: it uses `blockValueList.info.info`,
`blockValueList.info.addon`, `themeChoose` and `summaryDisplay`.
It includes the frontend's city/category/selector conversions,
conditional military-discharge dates, profile-link type rules, and
optional supplemental contact/display fields. A partial patch retains
unchanged native INFO siblings in memory and sends **one** INFO PUT.

**Not writable through this adapter:** account-owned phone number,
date of birth, login identity, job-seeking status, avatar/cover/signature
upload or delete, and arbitrary visual theme/background changes. Unknown,
missing or unrecognized native forms fail closed before any write.
Like the other new writers, this INFO path is **synthetic-tested only**;
there has been no real 104 write/read-back/restore test.

### More experimental 104-native operations

These operations are implemented as separate methods, not as arbitrary JSON
Patch replacement of whole record arrays. **They have only synthetic tests,
not real 104 write/read-back/restore verification.** Use the original site or
source to confirm any upstream changes before enabling writes.

| Operation | Python SDK | HTTP endpoint |
|---|---|---|
| Experience create | `mutate_experience(..., "create", changes=...)` | `POST /v1/tw104/resumes/{resume_id}/experiences` |
| Experience update/delete | `mutate_experience(..., "update"/"delete", position=...)` | `PUT/DELETE /v1/tw104/resumes/{resume_id}/experiences/{position}` |
| Local/foreign language CRUD | `mutate_language(..., kind, action, ...)` | `POST/PUT/DELETE /v1/tw104/resumes/{resume_id}/languages/{kind}[/{position}]` |
| Theme selection | `set_theme(..., section, selected_theme)` | `PUT /v1/tw104/resumes/{resume_id}/themes/{section}` |
| Adjacent skill/education/language swap | `sort_records(..., section, from_position, to_position)` | `PUT /v1/tw104/resumes/{resume_id}/sort/{section}` |

Record methods use 104's native selectors and one-based `sort` positions.
Experience salary is serialized according to the native job type. Local and
foreign language proficiency fields differ; changes to linked foreign
certificates are blocked until the separate association API is mapped.
Theme selections are validated against `GET /profile/ajax/options`, not a
locally guessed numeric range. Sorting permits **adjacent** SKILL/EDUCATION swaps and **adjacent**
local/foreign LANGUAGE swaps. The language group is an explicit kind
parameter; non-adjacent move behavior is not yet verified.

HTTP routes are protected by the bearer token and
`JOB_PLATFORM_104_ENABLE_EXPERIMENTAL_WRITES=1`; all write routes require
`If-Match` and an `Idempotency-Key`. Errors after a possibly committed
remote write are **not retried** automatically. The idempotency cache is
**not durable** after server restart, and independent 104 requests are
not one atomic transaction.

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

### Native 104 record, theme, and sort CLI

Every new 104-native operation also has a CLI entry point. These commands
**actually write to the selected resume** and are experimental. Supply
a fresh `resumeTimestamp`; create/update changes must be a private JSON
object matching native 104 fields.

```bash
job-platform record VERSION_NO experience update --position 1 \
  --changes-file private-changes.json --if-match TIMESTAMP \
  --confirm experimental-record-write
job-platform record VERSION_NO language delete --kind local --position 1 \
  --if-match TIMESTAMP --confirm experimental-record-write
job-platform theme VERSION_NO skill 2 \
  --if-match TIMESTAMP --confirm experimental-theme-write
job-platform sort VERSION_NO education 1 2 \
  --if-match TIMESTAMP --confirm experimental-sort-write
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

Except `/healthz`, routes require `Authorization: Bearer <token>`. The HTTP process maintains a browser session while running. Idempotency is in-process by default; optional SHA-256-only SQLite reservations prevent duplicate submissions across restarts when JOB_PLATFORM_IDEMPOTENCY_DB is configured. Keep it on localhost behind an authenticated TLS reverse proxy if remote access is needed.

## Optional durable HTTP duplicate prevention

The HTTP API normally keeps used Idempotency-Key records in memory,
which are lost on restart. Configure JOB_PLATFORM_IDEMPOTENCY_DB before
starting the local server to enable a persistent at-most-once guard:

    export JOB_PLATFORM_IDEMPOTENCY_DB=/private/secure-state/job-platform-idempotency.sqlite3
    xvfb-run -a job-platform-server --host 127.0.0.1 --port 8000

The parent directory must exist and must not be world writable.
SQLite uses a file with mode 0600. Only SHA-256 hashes of request
identities and (optional) request fingerprints are persisted: no
raw resume content, idempotency keys, login tokens or HTTP responses
are written to the ledger. Repository ignore rules exclude SQLite
files; keep the configured file private and on persistent storage.

The server reserves the idempotency key *before* an upstream mutation
using SQLite's atomic uniqueness constraint. Following a restart,
any previously used key returns HTTP 409 (indeterminate), **even if
the earlier request succeeded**. This prevents blindly sending the
same non-idempotent mutation twice but does not replay completed
responses across processes. Within one process, successful replies
remain cached and can be replayed. Inspect the actual 104 state before
deciding on a fresh key after any ambiguous outcome.

If the database is lost or deleted, duplicate protection is lost too.
The ledger is not a distributed transaction, does not reconcile remote
commit uncertainty and does not change the CLI's one-shot semantics.

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

The 104 frontend uses `resumeByBlock` for sections including personal data, education, experience, job conditions, skill, certificates, language, projects, portfolio, biography, and referees. Some native field encoders and record actions are implemented; others still require per-field mapping and real 104 write/read-back verification.

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
PUT requests. Other unmapped fields return HTTP 501.

Run the synthetic unit test suite with `python -m unittest discover -s tests -v`.
This repository contains only synthetic fixtures, never account data or backup
content. Dedicated live integration scripts stay outside the public repository.


## Latest 104 read-only compatibility check

A fresh authenticated **read-only** 104 check of the designated test
resume verified the protected BIO backup and successfully parsed INFO,
EXPERIENCE, LANGUAGE and INFO theme structures. It exposed legitimate
mixed integer/string experience salaries, optional company-size
selector objects, and descending record `sort` values. Those cases
are now covered by the 104 encoder and synthetic regression tests.
**No newly added writer has been real 104 write/read-back/restore verified;
the new check performed no mutations.**


### Experimental native LANGUAGE ordering

The 104 editor implements independent language groups, local and foreign.
Both groups have separate native sort entries, with the inactive group
sent as an empty list. The API requires an explicit kind in its body;
the CLI example is:

    job-platform sort VERSION_NO language 1 2 --kind local --if-match TIMESTAMP --confirm experimental-sort-write

Only adjacent moves are source-mapped, with exact read-back checks.
Arbitrary-distance sorting and live writes remain unverified.
