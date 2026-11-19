# Job Platform SDK

An unofficial, extensible Python SDK, CLI and optional HTTP API for managing job-seeker profiles and resumes across hiring platforms.

**Status: alpha.** The initial working provider is [104 Job Bank](https://www.104.com.tw/) in Taiwan. Providers for **Cake**, **Yourator**, and **Greenhouse** are planned, but **not implemented**.

**For coding agents:** Read [AGENTS.md](AGENTS.md) before development.
In particular, reuse an authenticated 104 browser/HTTP session across a
planned batch of API calls and tests; do not repeatedly log in unless
authentication has expired or a new browser-only context is genuinely needed.

## Provider capabilities

| Capability | 104 | Cake | Yourator | Greenhouse |
|---|---|---|---|---|
| Fresh login | Implemented (browser) | Planned | Planned | Planned |
| List resumes | Live tested | Planned | Planned | Platform-dependent |
| Read full resume | Live tested | Planned | Planned | Platform-dependent |
| Create resume | Browser flow tested; SDK not yet live-tested | Planned | Planned | Platform-dependent |
| Edit multiple fields locally | JSON Patch supported | Planned | Planned | Platform-dependent |
| Persist edits to website | **Selected native fields/record CRUD live-tested; other mapped fields experimental** | Planned | Planned | Platform-dependent |
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

### Latest 104 test-resume coverage checkpoint (2026-11-17)

The authorized 104 test resume has now passed additional real
write/read-back/restore cycles:

- CUSTOM TEXT=3: SDK POST create, PUT update, DELETE clear; exact
  empty CUSTOM slot restored.
- CUSTOM CLASSIC=1 and BANNER=2: source-mapped raw native
  POST/PUT/DELETE succeeded; generic SDK mutation of these themes
  has **not** yet been enabled.
- CUSTOM IMAGE=4: a generated blank 69-byte PNG was accepted
  by the real 104 POST and removed from the empty CUSTOM slot.
  This does **not** verify media replacement, preview or physical
  backend file garbage collection.
- CUSTOM MAGAZINE=5: both a NONE-media and synthetic-image POST
  were rejected upstream. Remains unsupported until the missing
  payload/validation requirement is identified.
- PORTFOLIO: the native three-entry 1→3 action uses **insertion**,
  not an endpoint swap. The SDK independently verified this move
  with two synthetic links, then deleted both and confirmed the
  original displayed file remained.
- REFERRER: SDK create, update and delete verified with an
  example.invalid synthetic contact; original empty block restored.
- SKILL: SDK create, update and delete verified with a temporary
  synthetic skill; the original two records were preserved.

Read-only PORTFOLIO conversion status now uses the exact official
BFF route /api/resumes/files/convert-status. It reports only status
and preview count, **never signed preview URLs**, and does not
request conversion. A real conversion-status GET attempt hit
an authentication error, so the feature is source-mapped and
synthetic-tested but not real status-verified.

**Still incomplete:** CUSTOM MAGAZINE and complex media update
flows, account-level certification CRUD/links, binary previews/
thumbnail/conversion, remaining INFO/UNDER18/SIDEBAR fields and
live tests for EDUCATION/EXPERIENCE/LANGUAGE/JOB_CONDITION.
See the PR body's completed/unfinished checklist and the
[redacted integration report](docs/tw104-live-smoke-report.md).

### Read-only dynamic CUSTOM slots and UNDER18

Full 104 resume GET responses can include dynamically numbered
CUSTOM sections from custom1 through custom6, as well as an optional
UNDER18 section on relevant profiles. The SDK now exposes these
native keys for read-only field/schema introspection without guessing
which fields are editable.

- CLI: job-platform custom-slots VERSION_NO
- CLI: job-platform get-section VERSION_NO custom1
- CLI: job-platform get-section VERSION_NO under18
- HTTP: GET /v1/tw104/resumes/{resume_id}/custom-slots
- HTTP: GET /v1/tw104/resumes/{resume_id}/sections/custom1
- SDK: client.list_custom_slots(version_no), client.get_section(...)

The custom-slots response includes detected names and field
schemas only, not full personal values; get-section returns the
actual private section contents and is bearer-protected in HTTP.
If the full GET does not include a dynamic slot, it is not invented.
No dynamic CUSTOM or UNDER18 mutation route has been enabled.

### Live 104 test-resume verification (2026-11-17)

A user-authorized test resume has now independently verified and
restored CERTIFICATE first PUT + text-only DELETE and PROJECT no-media
POST + record PUT update + record DELETE, **using the actual SDK wrappers**. The true CERTIFICATE GET has
certifications:[] and can omit certificates even though the PUT sends
certificates:[]. The decoder and source-mapped projection now handle
this link-free form, while rejecting unverified attached records.
Real PROJECT GET returns month selectors, an array-valued progress
state and an object-valued NONE cover.

PROJECT sorting, PORTFOLIO link/media changes, all CUSTOM writers,
global certificate CRUD and resume associations are not yet verified live. A PORTFOLIO link test aborted before network mutation
because an existing attachment did not match the initial private
snapshot. See docs/tw104-live-smoke-report.md for a redacted report.

### Offline native 104 CUSTOM text and certification connection plans

The last two native 104 workflows still lack a validated populated GET
contract and/or their exact deployed API route. They are deliberately
implemented as **offline request planners**, not experimental network
writers. They never start the browser or read stored credentials:

- `job-platform custom-text-plan create --slot 1 --name "Portfolio notes" --html-file private-intro.html --options-file private-site-options.json`
- `job-platform custom-text-plan update --slot 1 --name "Updated heading" --existing-form-file private-custom-form.json`
- `job-platform custom-text-plan delete --slot 1`
- `job-platform certificate-link-plan connect --ids-file private-cert-ids.json`
- `job-platform certificate-link-plan disconnect --record-id 123`
- `job-platform certificate-link-plan disconnect-other`

The first command takes an options JSON object containing
`optionsCustomTheme`, as returned by the 104 editor. CUSTOM uses
numbered slots `custom1`–`custom6`. The official frontend modules
4228/5255 map **CustomThemeText=3**, strip UI-only duration fields,
normalize its media to NONE=0, and convert selectedTheme to an integer.
Only one text-only content item with conservative HTML tags is supported
here. Any media-containing or non-text CUSTOM update fails closed.

The certification association planner is independent from global
certification CRUD: frontend module 779c sends
`{"certIds":[...]}` for `certificationConnect/put`, and has separate
`delete` and `deleteOther` actions. Their public frontend action
names are mapped, but live endpoint URL, account-level ID semantics,
read-back and restore have not been verified.

Both planners return `persisted:false` and `network_sent:false`;
no authentication or write happens. **Do not send the generated
request body directly** until the target 104 version, source path
and native read-back are independently confirmed. These features are
not counted as complete resume editor writes.

### REFERRER two-record ordering

The official f5d8 frontend hardcodes
`blockValueList.referrer.referrers.sort={from:2,to:1}`.
The existing source-mapped adjacent-sort SDK/HTTP/CLI now accepts
REFERRER **only when exactly two distinct records exist**. It does
not generalize to three or more records because the website action
itself ignores the requested drag positions. No real REFERRER sort
was executed; synthetic tests validate the exact POST body and
independent read-back.

### Experimental 104 CERTIFICATE block initialization / text clearing

The real test resume has an empty CERTIFICATE formData. Its public
frontend module 779c maps first-creation to **PUT**, not POST, with
blockValueList.certificate.certificates=[] and an others text value.
The whole-block clear uses **DELETE** with the two fields set to
empty strings (certificates="", others=""). Neither operation is
the same as account-global certification CRUD or linking a certificate
to a resume.

The new Resume104Client.mutate_certificate_block() method and the
experimental HTTP endpoint /v1/tw104/resumes/{resume_id}/certificate-block
support first initialization (POST in *our* HTTP API; upstream PUT) and
text-only clearing (DELETE in both). The CLI commands are:

    job-platform certificate-block VERSION_NO initialize --others-file private-text.txt --if-match TIMESTAMP --confirm experimental-certificate-write
    job-platform certificate-block VERSION_NO clear --if-match TIMESTAMP --confirm experimental-certificate-write

The adapter requires empty formData for initialization and enforces
a conservative 1-200-character nonempty others text limit. Clearing is
permitted only when the resume block has **no linked certificate
entries**, to prevent breaking other certification associations. All
actions use the normal optimistic timestamp and independent read-back;
HTTP also uses opt-in bearer authorization and in-memory idempotency.

**Live-verified:** the corrected native SDK certificate-block
initialize and clear completed a real PUT/GET/DELETE/GET cycle on the
designated test resume, independently restoring the empty section.
Account-wide certification CRUD, suggestion search and
certificationConnect association/disassociation remain unimplemented.

### Experimental 104 PORTFOLIO binary file upload

The official editor module 44aa submits native PORTFOLIO FILE=1 items
using FormData with **five text fields plus one browser File object**.
The browser transport now handles this path in memory, including
the 104-profile-ver request header and browser-created multipart boundary.

The SDK entrypoint is
`Resume104Client.upload_portfolio_file(resume_id, expected_timestamp=...,
name=..., attach_name=..., filename=..., content_type=..., content=...)`.
It creates one item and independently checks a newly addressable file
handle while preserving the identities of preexisting portfolio items.

Equivalent CLI and local HTTP entrypoints:

    job-platform portfolio-file VERSION_NO --file /private/test.pdf --name "Test work" --if-match TIMESTAMP --confirm experimental-file-upload
    POST /v1/tw104/resumes/{resume_id}/portfolio-files
    Authorization: Bearer LOCAL_API_TOKEN
    If-Match: TIMESTAMP
    Idempotency-Key: UNIQUE_KEY_AT_LEAST_16_CHARS

The local HTTP request uses application/json, not a public binary
hosting endpoint, with exactly the following **generic synthetic**
structure (base64 is the entire local file, not a file path):

    {"name":"Test work","attachName":"test.pdf",
     "filename":"test.pdf","contentType":"application/pdf",
     "base64":"JVBERi0xLjQK..."}

Current limits: **5 MiB**, PDF/PNG/JPEG only, filename and content
signature checks. The body is decoded to memory, not persisted in
SQLite, temporary local server files, or the public repository.
Do not expose this localhost service to the internet.

The native file branch sends `attachType=1`, an empty
`attach.src` and the binary `attachment` part. Source mapping
is confirmed from frontend module 44aa. **A PDF file upload/read-back/
delete cycle has now been live tested**; asynchronous conversion,
thumbnail, document preview and download remain TODO.
A successful upload method response has `preview_verified:false`.
An uncertain remote write must not be blindly retried.

PORTFOLIO file GET returns long opaque fileId, signed URL and preview
fields. These are not guaranteed to be stable across logins. The
one-record delete and create verifiers now compare ordered stable
display identity (portfolio title, attachment display name, FILE/LINK
type; destination URL for LINK), refusing duplicates and preserving
preexisting records. This guards against token churn being mistaken
for a deleted attachment, but it is **not a globally unique
immutable file identifier**. See the PR's remaining work table.

### Live PORTFOLIO link and PDF file roundtrips (2026-11-17)

In separate authenticated sessions on the designated disposable test
resume, the SDK successfully created a synthetic external link
(LINK=2), verified it with an independent GET, and removed precisely
that temporary item. The original portfolio file's opaque fileId,
thumbnailFileId, src and URL changed between independent GETs, while
its stable displayed identity remained unchanged.

The SDK then uploaded a generated **621-byte synthetic, one-page PDF**
(FILE=1) through the new binary multipart transport. The GET
contained an addressable file item. The SDK deleted only that uniquely
titled temporary PDF and independently verified the original displayed
one-item PORTFOLIO identity. BIO remained unchanged; PROJECT and
CERTIFICATE remained empty.

**Not yet verified:** physical deletion of detached server-side file
blobs, file download/checksums, thumbnail generation, PDF preview,
conversion, replacement, other media types and native sorting.
The test PDF had no thumbnailFileId after its initial GET.
The result has preview_verified=false and file-content-checksum
verification remains outside the SDK.

See docs/tw104-live-smoke-report.md. No credential, private
resume ID or real attachment bytes are committed.

### PORTFOLIO adjacent sorting: authenticated 104 verification

The source-mapped 104 swapRecordBySort/portfolio API now has a
verified **two-item adjacent swap and reverse-swap** roundtrip.
We inserted a uniquely titled synthetic link next to the existing
portfolio file, swapped their positions, verified the order,
swapped back, and deleted the synthetic link. The original
one-item displayed portfolio identity was independently restored.

Opaque fileId, signed download URLs and thumbnail access tokens
are **not compared** during PORTFOLIO sort read-back because they
rotated in real native GETs. Uniqueness checks still reject
duplicate indistinguishable titles/filenames. This verifies
displayed record ordering, not original file bytes or physical
backend storage. Non-adjacent ordering and 3+ entries remain
unverified. See docs/tw104-live-smoke-report.md.

### Experimental 104 PROJECT and PORTFOLIO actions

The 104 PROJECT section is initially empty on the designated test resume.
The official frontend (module 1d22) uses a separate POST for first record
creation, PUT for one-record editing, DELETE by native sort ID, and a
swapRecordBySort endpoint for ordering.

The Python SDK exposes:
- Resume104Client.mutate_project(resume_id, action, changes=..., position=...,
  expected_timestamp=...) for create, update and delete.
- Resume104Client.mutate_portfolio(resume_id, "delete", position=...,
  expected_timestamp=...) for **deleting a single existing portfolio**.
- Resume104Client.sort_records(resume_id, "project"/"portfolio", from_position,
  to_position, expected_timestamp=...) for adjacent positions only.

The experimental HTTP endpoints are:
| Method | Endpoint | Operation |
|---|---|---|
| POST | /v1/tw104/resumes/{resume_id}/projects | Create a no-media project |
| PUT | /v1/tw104/resumes/{resume_id}/projects/{position} | Update existing no-media project |
| DELETE | /v1/tw104/resumes/{resume_id}/projects/{position} | Delete one project |
| POST | /v1/tw104/resumes/{resume_id}/portfolios | Add a link-only portfolio item using FormData |
| DELETE | /v1/tw104/resumes/{resume_id}/portfolios/{position} | Delete one portfolio entry |
| PUT | /v1/tw104/resumes/{resume_id}/sort/project | Adjacent project swap |
| PUT | /v1/tw104/resumes/{resume_id}/sort/portfolio | Adjacent portfolio swap |

All mutations require experimental HTTP opt-in, authentication,
If-Match and Idempotency-Key. The equivalent CLI commands use
job-platform record and job-platform sort with explicit confirmation.

PROJECT creation requires these **no-media** fields: name, duration
(startYear/startMonth/endYear/endMonth), isInProgress, introduction
(HTML string) and url (optional http/https URL). The adapter generates
file.type=0 and an empty file.content, without accepting cover images,
video uploads, file metadata or arbitrary extra fields. It refuses
updates of existing projects with nonempty media, preventing accidental
loss of an uploaded image or video. The first creation resolves its
initial theme from the current optionsProjectTheme, not a fixed value.
104 inputField read-only validation reported max 6 PROJECT entries,
name 120 characters, introduction HTML 4000 and url 200.

The PORTFOLIO entry GET shape was checked with a real, **read-only**
104 response (one existing attachment). Link-only creation uses a
browser-built FormData (no binary file) and the native LINK=2
attachment type from module 401c. It requires name, attachName and
url (an http/https URL), with an existing or site-default portfolio
theme. The POST form contains five entries, including the nested
attach name and URL; browser-provided multipart boundaries are used.
Deletion uses the native
blockValueList.portfolio.sort list, **not** the PROJECT or REFERRER
delete shape. A deletion can permanently remove an uploaded attachment
from the 104 service; do not run it without an independent private
backup. File **upload** uses a separate binary multipart request and, for
some formats, thumbnail/preview processing: this remains TODO.
Link-only additions do not upload local files or fetch remote thumbnails.

**These new write/sort actions have synthetic tests only.** No remote
PROJECT or PORTFOLIO writes, deletions, links or uploads have been performed.
Before production use, first-create POST, native GET, update, delete
and restore must be individually verified on a safe test resume.

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
Patch replacement of whole record arrays. Their validation levels vary:
**EXPERIENCE CREATE (companyVisibility=True) and DELETE, and LANGUAGE local
CREATE/DELETE, were live-verified with independent read-back and exact
restoration**; other cases remain experimental. The 104 site previously
changed companyVisibility=False into True on EXPERIENCE CREATE, so the SDK
now rejects that unsupported privacy choice *before* any write.
See [104 coverage](docs/tw104-editor-coverage.md) for per-operation evidence.
Use the upstream source and a private backup before other experimental writes.

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
A real 104 FOREIGN POST with an existing same-kind type **overwrote the
original record** instead of adding another; the original was restored.
The SDK now rejects any LANGUAGE CREATE with a type already present
in the selected kind before sending a request; UPDATE rejects **all**
language-type changes because the official frontend may delete the old row as
part of its multi-request edit flow. In-place proficiency UPDATE is supported.
Canonical
numeric language IDs are enforced for wire serialization. Before a
LANGUAGE CREATE/UPDATE, the SDK fetches the current 104 `/profile/ajax/options`
catalog and requires every supplied language/proficiency selector to match
its numeric ID **and display text**. `optionsForeignType` / `optionsLocalType`
are separate; `optionsLanguageType` only selects the UI category. Invalid,
missing or stale option catalogs fail before the write. Use UPDATE to edit an
existing language. A genuinely new FOREIGN CREATE remains live-unverified.
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


#### CLI: add a portfolio link

Create a local JSON file (do not commit it) with the three fields
name, attachName and url, then run:

    job-platform record VERSION_NO portfolio create --changes-file private-link.json --if-match TIMESTAMP --confirm experimental-record-write

For PORTFOLIO, this create action accepts only a link URL; file uploads
and replacement of existing attachments are deliberately rejected.
It sends text-only multipart fields inside the authenticated browser
and validates independent native read-back. The original in-process
HTTP idempotency and opt-in protections apply. There is no SQLite or
persistent state requirement for disposable SDK use.

### Optional hybrid 104 HTTP transport

[104 hybrid browser/HTTP transport](docs/tw104-hybrid-transport.md) documents the opt-in curl_cffi adapter, proxy-bound cookie handoff,
experimental write safeguards, and verification status. The default remains
the browser transport; the HTTP adapter needs `pip install '.[curl]'`.
