# 104 resume editor coverage inventory

This is a **104-only** implementation checklist, not a cross-platform resume
schema. Source: inspected 104 editor JavaScript modules and structural, value-
redacted GET responses (November 2026). The site can change at any time.

**Do not equate GET field presence, observed frontend calls, synthetic tests
and successful real 104 writes.** Each is a separate evidence level.

| Native group | Frontend operation families seen | Implementation in this PR | Live 104 write/read-back |
|---|---|---|---|
| `info` | PUT; related identity and optional information | Source-mapped selected resume INFO fields (experimental); account/media excluded | **No** |
| `education` | POST, PUT, DELETE; ordering | Native record CRUD + adjacent swap sorting (experimental) | **No** |
| `experience` | POST, PUT, DELETE; ordering, seniority | Seniority-only PUT + native record CRUD (experimental); record ordering pending | **No** |
| `jobCondition` | PUT; separate layout/theme PUT | Source-mapped full native form serializer, experimental | **No** |
| `skill` | POST, PUT, DELETE; ordering | Source-mapped record CRUD + adjacent swap sorting (experimental) | **No** |
| `certificate` | PUT, DELETE; certification connections | Existing text PUT plus first-empty PUT and guarded clear; global associations excluded | **SDK initialize + clear verified and restored live** |
| `language` | POST, PUT, DELETE; local/foreign records | Native local/foreign record CRUD + adjacent local/foreign sorting (experimental); linked certificates blocked | **No** |
| `project` | POST, PUT, DELETE; reorder; attachments | No-media CRUD and adjacent reorder; media pending | **SDK create, update and delete verified live and restored**; sorting synthetic |
| `portfolio` | POST, DELETE; attachments/upload; reorder | LINK=2 POST, FILE=1 bounded binary POST, one-record DELETE, adjacent reorder; preview/conversion pending | **SDK LINK/FILE create-read-delete live verified**; sort/preview untested |
| `bio` | POST, PUT, DELETE | HTML PUT live-verified; first-create POST and clear DELETE experimental | **PUT only** |
| `referrer` | POST, PUT, DELETE; reorder | Native record CRUD, empty-form first-create, **exactly-two-record** hardcoded adjacent swap (experimental) | **No** |
| `sidebar` | PUT | Complete-list reorder only; metadata edits rejected | **No** |
| `layout` | PUT | Theme selection for 11 native sections using current 104 option values (experimental) | **No** |
| `custom` | POST, PUT, DELETE | **Read-only** custom1..custom6 section/schema discovery plus offline TEXT=3 payload planner; no remote mutation | No |
| `under18` | POST, PUT | Optional native section/schema **read-only**; no remote writer | No |

For source details see [104 upstream contract](tw104-upstream-contract.md).
Some frontend functions call additional endpoints not in `resumeByBlock`, such
as certificate association, media uploads, and record sort operations.

## Known native field families

These are **field families observed in responses**, not a complete inventory of
every possible UI control.

- `info.formData.info`: employment status, birth date, military, phone,
  city/street, biography summary, motto, traits, personal links and photos.
  `info.formData.addOn` includes supplemental contact, driver's license,
  transportation and other optional records. Theme and summary display use
  additional formData members.
- `education.formData.educations[]`: schools, departments, education level,
  attendance dates and graduation/current-status data, ordering.
- `experience.formData.experiences[]`: company, job title, industry, dates,
  job category, job description, skills, management, compensation, display
  settings, ordering. `seniority` is separate.
- `jobCondition.formData.jobCondition`: job-time/willingness/period fields,
  shifts, onboarding dates, salary, preferred areas/titles/job types/industries,
  work description and remote-work preference. The outgoing PUT serializes
  select values and category numbers, and uses conditional date/salary branches.
- `skill.formData.skills[]`: names, descriptions, tags and ordering.
- `language.formData.languages`: local and foreign language collections.
- `portfolio.formData.portfolios[]`: names, attached media, types and order.
- `bio.formData.bio`: `chi` and `eng` HTML strings.
- `sidebar`: ordered section ID list (GET may include read-only completion
  metadata).
- `project`, `referrer` and `certificate` can have empty formData, so
  initialization and CRUD must not be inferred from a nonempty GET fixture.

## Next technical milestones

1. Observe every control in the **104** editor and capture the request *shape*
   for its create/update/delete/reorder actions. Do not store real payload
   values in the repository.
2. Extend the existing native record/layout encoders for `info`, referrer,
   project, portfolio, certificate connections, media, and remaining ordering; validate every supported JSON Patch path before network I/O.
3. Live-test each source-mapped operation on the designated test resume,
   using private backups and exact read-back/restore where reversible.
4. Extend the synthetic Python SDK, HTTP API and CLI test matrix; harden
   remote-conflict reconciliation and login recovery. SQLite and persistent
   idempotency are out of scope for disposable execution.

Current definitions:

- **Verified:** Real 104 mutation submitted, exact changed-value read-back,
  then original restored and independently read back.
- **Experimental:** Upstream source-mapped serializer plus synthetic tests,
  with no successful real 104 write/read-back yet.
- **Unavailable:** No safe writer; PATCH is rejected rather than guessed.

The scope is **only 104**. No common data schema or adapter behavior is being
designed for other job platforms.


## 2026-11-17 incremental coverage

- **EXPERIENCE records:** source-mapped create, update and delete; salary
  serialization distinguishes salaried job types from part-time pay, with
  one-based positions. Changing the section's overall seniority uses its own
  existing adapter. Record CRUD is **not live write-verified**.
- **LANGUAGE records:** independent local and foreign CRUD with different
  selector fields. Mutations involving linked foreign certificates are
  intentionally blocked until the association API can be verified.
- **LAYOUT:** one section theme at a time, with valid values fetched from
  `/profile/ajax/options`. Unknown/uninitialized theme shapes fail closed;
  media, background color and layout ordering are not covered.
- **SKILL / EDUCATION ordering:** adjacent swap only, sent through
  `/profile/ajax/swapRecordBySort/{section}`. Exact read-back checks the
  permutation and all unaffected records. Arbitrary moves and sorting other
  sections require further verification.
- Above actions are accessible in the Python SDK, experimental 104 HTTP routes
  and CLI. All mutations use version checks and independent read-back; HTTP
  additionally requires a bearer token, experimental opt-in and a unique
  idempotency key. No durability beyond a single HTTP process is claimed.
- This initial checkpoint used synthetic tests only for the new
  record writers. Later 2026-11-17 integration additionally verified
  PROJECT CRUD and the CERTIFICATE block lifecycle on a real test resume.


## 2026-11-17 incremental coverage

- **EXPERIENCE records:** source-mapped create, update and delete; salary
  serialization distinguishes salaried job types from part-time pay, with
  one-based positions. Changing the section's overall seniority uses its own
  existing adapter. Record CRUD is **not live write-verified**.
- **LANGUAGE records:** independent local and foreign CRUD with different
  selector fields. Mutations involving linked foreign certificates are
  intentionally blocked until the association API can be verified.
- **LAYOUT:** one section theme at a time, with valid values fetched from
  `/profile/ajax/options`. Unknown/uninitialized theme shapes fail closed;
  media, background color and layout ordering are not covered.
- **SKILL / EDUCATION ordering:** adjacent swap only, sent through
  `/profile/ajax/swapRecordBySort/{section}`. Exact read-back checks the
  permutation and all unaffected records. Arbitrary moves and sorting other
  sections require further verification.
- Above actions are accessible in the Python SDK, experimental 104 HTTP routes
  and CLI. All mutations use version checks and independent read-back; HTTP
  additionally requires a bearer token, experimental opt-in and a unique
  idempotency key. No durability beyond a single HTTP process is claimed.
- This initial checkpoint used synthetic tests only for the new
  record writers. Later 2026-11-17 integration additionally verified
  PROJECT CRUD and the CERTIFICATE block lifecycle on a real test resume.


### INFO scope (2026-11-17)

The adapter uses the official frontend's `c40f.postData()` for its 104
`INFO` block. The mapped resume subfields include address, summary,
motto, personal links, conditional military dates, traits, supplementary
contact fields, driver/transport selectors and native display-summary
values. The encoder preserves untouched siblings and is exercised via
SDK and HTTP PATCH regression tests.

**Excluded until separately mapped and verified:** account-level identity
and login phone, birth date/job status, photos/cover/signature upload,
advanced profile visual presentation and other conditional media fields.
The full INFO editor is **not** yet implemented or live verified.


### 104 read-only validation and regression (2026-11-17)

On the designated test resume, a fresh one-proxy login succeeded. The
target's current identity was checked against its private marker, and its
BIO text matched the original protected backup; **no writes occurred**.
The SDK source-mapped INFO serializer, experience record extractor,
language record extractor and INFO theme selector all successfully
validated the actual GET response.

The inspection exposed two previously missing EXPERIENCE variants:
salary values may be native integers as well as strings, and optional
company size may be an object selector or an empty string. The GET's
`experiences[]` array was ordered by descending `sort` (newest first).
The adapter now accepts either consecutive ascending or descending
sorts, selects records by actual `sort` rather than list index, and
verifies create/update/delete without assuming ascending display order.
These changes have synthetic regression tests; **no new real POST,
PUT or DELETE has been executed**.


### REFERRER coverage (2026-11-17)

The frontend's f5d8 module provides native per-record CRUD and a separate
swapRecordBySort operation. The record fields are name, company, position,
email, tel and sort. Initial GET on the designated test resume returned
an empty referrer formData; the current site's first referrer theme is
selected for a first POST. A real read-only /profile/ajax/inputField
confirmed maximum characters 30/35/20/50/50 and the options endpoint
reported two available referrer themes. The encoder is synthetic-tested
with field length, record-identity, no-overwrite, optimistic concurrency
and HTTP idempotency regression cases.

Missing: real populated GET shape, first POST/read-back/restore, all UI
conditional contact-visibility options, and sorting. No real contacts or
credentials are in the public repository.


### LANGUAGE adjacent sort (2026-11-17)

Official frontend module 96e2 uses swapRecordBySort for independent
local and foreign collections. Drag-end emits a nested languages object
with both foreign.sort and local.sort; the inactive group is [].
The new SDK, CLI and HTTP route require an explicit group and preserve
the untouched group. These operations have synthetic tests only.


### BIO first creation and clearing (2026-11-17)

Source module 8d88 sends POST with chi/eng HTML nested under
blockValueList.bio.bio, while DELETE sends chi/eng empty strings directly
in blockValueList.bio. Both additional operations are exposed in SDK,
CLI and HTTP with strict state preconditions. The original BIO PUT has
passed a live read/modify/read/restore test; POST and DELETE have
synthetic tests only. No actual BIO deletion was attempted.


### PROJECT and PORTFOLIO native adapters (2026-11-17)

Read-only 104 verification on the designated test resume found an empty
PROJECT formData, a populated PORTFOLIO formData with one record, and
native options for three project themes and three portfolio themes.
The official editor inputField reports a maximum of six entries in
each section; PROJECT name 120 characters, intro text 2000 / HTML 4000,
link URL 200. The real PORTFOLIO record had native fields name, attach,
attachType and sort. Its attachment metadata uses name, status, url,
fileId, thumbnailFileId, src and crawler.

PROJECT no-media create/update/delete is mapped to frontend module
1d22. Native wire JSON uses projects[] and a theme selection; the
first POST initializes an empty form with the site-provided theme.
The encoder intentionally disallows uploading or overwriting media,
and now normalizes the real observed populated GET shape. One-record
PORTFOLIO delete follows module 44aa; its payload contains
blockValueList.portfolio.sort as a list. The link-only multipart POST now constructs FormData in the same-origin
authenticated browser. Binary file upload, conversion and asynchronous
thumbnail generation remain missing.

PROJECT and PORTFOLIO adjacent sorting use swapRecordBySort and
independent sibling-preserving read-back. Non-adjacent sorting remains
unsupported until its move-vs-swap semantics are verified. PROJECT
create/update/delete have since passed real SDK-level write/readback/
restore, while PROJECT/PORTFOLIO sorting and PORTFOLIO writes
remain synthetic-only. No existing attachment was mutated.


### PORTFOLIO link-only multipart POST (2026-11-17)

The browser transport now supports text-only multipart FormData with the
same 104-profile-ver header as other mutations. The link-only frontend
path is module 44aa, with attachment type LINK=2 from 401c. The five
form keys are the selected portfolio theme, item name, attachType,
attach.name and attach.url. A no-attachment-file guard prevents this
route from uploading files or overwriting existing attachments.

For initial empty formData, the first site optionsPortfolioTheme is used;
for a populated form, the existing selectedTheme is preserved.
The returned new record must match the requested link, while all prior
attachment records remain unchanged on read-back. The HTTP endpoint
retains opt-in, If-Match and in-process Idempotency-Key protection.
Only synthetic HTTP/CLI/browser transport tests have been performed.


### CERTIFICATE text-only block lifecycle (2026-11-17)

Public module 779c.CREATE delegates to UPDATE, which issues a native
PUT for blockValueList.certificate={certificates:[],others:TEXT}.
It works with the initialized/certification-free branch, while the
site's actual empty formData was observed in an authenticated
read-only GET. The independent CLEAR action is DELETE with
certificates="" and others="". This writer refuses a clear when
the block has any linked certificates. It also refuses account-level
certification changes and association operations (certificationConnect).

The Python SDK, CLI and HTTP lifecycle APIs have synthetic regression
coverage only, with If-Match, in-memory Idempotency-Key, no blind retry
and exact read-back checks. Real initialization and restore are still
unverified.


### REFERRER two-record swap (2026-11-17)

Editor action f5d8.SORT hardcodes
blockValueList.referrer.referrers.sort={from:2,to:1} and ignores its
input. The sort adapter accepts exactly two records, either adjacent
direction, and rejects any other length. Existing SDK, CLI and HTTP
sort routes now recognize the source-defined REFERRER action.
Synthetic read-back must show an exact swap with no sibling changes.
The actual test resume's REFERRER formData was empty, so there is
no live two-record sort or restore confirmation.

### CUSTOM TEXT source-level only (2026-11-17)

Modules 4228, 5255 and 6330 establish five CUSTOM themes; TEXT has
value 3. CUSTOM contains numbered dynamic slots custom1..custom6
(up to six), with one or more content items depending on theme.
The postData() transformation strips UI-only duration
index/durationGroup, rewrites the isInProgress flag, and converts
file[] to native media; for TEXT=3 the file becomes NONE=0.
The safe text planner only supports one content item, a title and
a limited set of HTML tags, no media uploads and no populated
GET shape assumptions. It source-maps:
- POST/PUT body blockValueList.custom.custom plus themeChoose;
- DELETE body blockValueList.custom.custom.sort=[SLOT].

Offline CLI command custom-text-plan creates these request shapes
from private local input files. It neither authenticates nor writes
to 104. The native populated CUSTOM GET after first creation remains
unobserved and there is no remote CUSTOM mutation yet.

### CERTIFICATE association source-level only (2026-11-17)

Separate 779c frontend Vuex actions use
api/certificationConnect/put with {certIds:[IDs]},
api/certificationConnect/delete with an ID, and
api/certificationConnect/deleteOther with the current resume.
These are **not** the same as account-global
api/certifications/{get,post,put,delete} operations.

The new certificate-link-plan CLI and Python functions only
serialize action names and safe typed argument shapes. They do not
construct an unverified URL or initiate any remote mutation.
Real association/disassociation and independent read-back
must be established before making these executable.


### Authenticated 104 test resume results (2026-11-17)

Native CERTIFICATE initialization and text-only clear were verified
by independent GET and exact restore. A live GET after PUT contains
certificate.certifications=[] and certificate.others, **without**
certificate.certificates. This corrected an earlier faulty read-back.
PROJECT first POST and one-item DELETE were also verified and returned
its formData to exactly empty. Real PROJECT GET selectors and image
metadata are now covered by synthetic regression tests.

PORTFOLIO link testing aborted before writing because the previous
private snapshot's attachment identity did not match a fresh read.
See the separate redacted report tw104-live-smoke-report.md.


### Dynamic CUSTOM and UNDER18 read-only introspection

The SDK section allowlist includes the optional under18 section
and numbered custom1 to custom6 keys. It returns only sections
actually present in the full native resume GET, and the new
list_custom_slots method supplies schemas for discovered CUSTOM
blocks without returning personal content.

HTTP /custom-slots and CLI custom-slots expose this read-only
discovery. Missing dynamic sections are not synthesized and all
custom/under18 write paths remain unsupported. The user's test
resume has no CUSTOM or UNDER18 keys in its authenticated GET;
populated dynamic response shapes are not yet real-verified.


### Second completed SDK write/read-back/restore cycle

After adjusting the CERTIFICATE GET model, the authenticated SDK
successfully ran certificate initialize and clear, plus PROJECT
create, update and delete, all independently verifying their native
result. Final GET confirmed the two sections were empty and BIO
remained unchanged. All three PROJECT mutation methods are now
**live tested**, but PROJECT sorting and media editing are not.
See tw104-live-smoke-report.md.


### PORTFOLIO binary upload and stable identity checks (2026-11-17)

The source-mapped FILE=1 branch now creates a browser FormData object
with 5 nested text fields and an actual binary File appended as
`attachment`, rather than URL-encoding or treating bytes as JSON.
The in-memory upload transport validates:
- Local file bytes <= 5 MiB and minimum plausible signature length;
- PDF, PNG and JPEG magic headers/trailer and matching file extensions;
- Valid simple attachment name, selected existing or live site theme;
- Current resume timestamp and site-provided 104-profile-ver header;
- Single remote POST with no blind retry on uncertain response;
- GET read-back of exactly one addressable new file record, preserving
  preexisting displayed attachment identities.

CLI `portfolio-file` reads local files directly. The bearer-only
experimental localhost HTTP endpoint `/portfolio-files` accepts
JSON with base64 contents; it uses an in-memory idempotency key, and
does not require python-multipart or a persistent database.

The older FILE GET has fileId, url, thumbnailFileId and src values
that may represent time-limited access information. An original
attachment's stable displayed name, attachment filename and FILE=1
type are compared without treating those opaque strings as immutable.
Duplicate indistinguishable items fail closed before a mutation.

This **does not yet implement** actual preview/thumbnail conversion,
binary download, replacement, content-type negotiation for DOC/DOCX,
or live upload/readback/delete-and-restore. These remain on the PR
outstanding-work checklist. Existing real attachment data is not
published in fixtures.


### Live PORTFOLIO link and PDF verification (2026-11-17)

The official LINK=2 native multipart POST successfully created a
temporary URL item; the SDK independently verified it, and a
subsequent targeted DELETE removed it from the test resume.
The first cleanup guard rejected a valid operation because the
preexisting FILE entry's opaque access/preview fields rotated.
A separate diagnosis confirmed the stable displayed name,
attachment filename and FILE type had not changed. A later
targeted SDK DELETE removed the test link, and the original
displayed item remained.

A separate real session used the SDK binary FILE=1 multipart
adapter to upload a generated 621-byte PDF with no personal
content. GET showed an addressable uploaded record, the SDK
verified it, and a targeted DELETE restored the original
displayed one-item portfolio list.

The SDK does not yet validate PDF preview/thumbnail generation,
binary download or checksum equality, conversion lifecycle,
replacing attachments or physical backend blob garbage collection.
