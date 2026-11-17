# 104 resume editor: observed upstream contract

> Unofficial reverse engineering notes for SDK development, November 2026.
> These paths and data types can change without notice. This document contains
> no personal account responses, authorization values, or private resume data.

## Browser as the reference implementation

The successful baseline uses a new Patchright headed Chromium profile, one
stable proxy across sign-in, the official 104 authentication/MFA screens, then
an authenticated same-origin browser context for resume calls. Copying cookies
into an unrelated HTTP client has returned HTTP 403 for My104 endpoints.

A server-side response header named **`104-profile-ver`** is read by the
official frontend. Its request interceptor attaches that value to subsequent
`PUT`, `POST`, and `DELETE` requests. Treat it as sensitive in-memory
session state: do not print or store the value in reports, URLs or logs.
The SDK now caches it from same-origin API responses and refuses unsafe methods
until a valid value has been seen.

## Read endpoints

| Purpose | Request |
|---|---|
| List resume summaries | `GET /profile/ajax/overview` |
| Read a resume and all its blocks | `GET /profile/ajax/resumeByBlock?vno=VERSION_NO` |
| Read a single block | `GET /profile/ajax/resumeByBlock/BLOCK?vno=VERSION_NO` |
| Read complete list | `GET /profile/ajax/completeResumeList` |

The full document includes `resume.vno`, `resumeTimestamp` and independent
nested sections such as `info.formData`, `experience.formData`, and
`bio.formData`. Keep unknown fields in the in-memory representation; do not
silently discard them during a read/modify/write operation.

## Mutating requests

The frontend implements a common dispatcher for `PUT`, `POST` and `DELETE`:

```http
PUT /profile/ajax/resumeByBlock/BLOCK?vno=VERSION_NO
104-profile-ver: (current header value from prior API response)
Content-Type: application/json
```

The request body is **block-specific**, usually rooted at `blockValueList`.
The dispatcher itself does not imply that any raw GET response is a valid
write payload.

Supported block names in the frontend's enumeration include:

| Block | Source-observed operation categories | Notes |
|---|---|---|
| `info` | PUT | Multiple derived/presentational fields require mapping |
| `bio` | POST, PUT, DELETE | Chinese and English biography HTML strings |
| `education` | POST, PUT, DELETE | Repeating records and sort values |
| `experience` | POST, PUT, DELETE | Repeating jobs plus seniority metadata |
| `jobCondition` | PUT | Structured preference fields |
| `skill` | POST, PUT, DELETE | Repeating skills and sort values |
| `certificate` | PUT, DELETE | Certificates and free-form other text |
| `language` | POST, PUT, DELETE | Repeating language records |
| `project` | POST, PUT, DELETE | Repeating projects, attachments |
| `portfolio` | POST, DELETE | Upload flows can use multipart forms |
| `referrer` | POST, PUT, DELETE | Repeating referees |
| `layout` | PUT | Theme/display choices; also used by section-specific modules |
| `sidebar` | PUT | Ordering and visibility |
| `custom` | POST, PUT, DELETE | User-defined sections |
| `under18` | POST, PUT | Age-related identity metadata |

The table reflects **frontend source-code call sites**, not end-to-end
server acceptance for every operation. Other API endpoints (including media
uploads, portfolio links and record sort operations) also exist.

### BIO adapter

The current frontend's outgoing BODY for updating both languages is:

```json
{
  "blockValueList": {
    "bio": {
      "bio": {
        "chi": "<p>example Chinese biography</p>",
        "eng": "<p>example English biography</p>"
      }
    }
  }
}
```

The SDK's BIO adapter preserves the non-targeted sibling language if only
one is changed, writes both values once, and reads back to compare exactly.


**Live verification status:** A BIO PUT without `104-profile-ver` returned
HTTP 400. With this header, an identical-content PUT returned HTTP 200.
A later test performed a real punctuation modification, verified it by
reading the 104 API, then restored the exact original data and verified
the restoration. The BIO writer has now passed end-to-end validation.

### CERTIFICATE writer (experimental)

The official frontend uses:

```json
{"blockValueList":{"certificate":{"certificates":[],"others":"example"}}}
```

The SDK maps the existing native `certificate.formData.certificate` fields
`certificates` (array) and `others` (text). Changing either field preserves
the other. This is **source-mapped and unit-tested, not live-tested**.
The target resume's certificate formData was empty, so the SDK refuses
to guess a creation payload. Separate certification associations, array-item
CRUD and record ordering are still pending.

### SIDEBAR ordering (experimental; no live write verification)

The current 104 frontend maps the sidebar drag-order action to:

```http
PUT /profile/ajax/resumeByBlock/sidebar?vno=VERSION_NO
```

```json
{"blockValueList":{"sidebar":[{"id":"education"},{"id":"experience"}]}}
```

Those IDs are illustrative synthetic identifiers only. The actual payload must
contain **every existing entry in the intended order**, with each entry reduced
to `{"id": <original-id>}` by the frontend. The read response also contains
`completed` and potentially other metadata. The writer preserves these in
memory; it will **only reorder** the existing identical objects and reject
adding/removing entries, changing IDs, or changing any other metadata.

Expose this as a JSON Patch complete replacement of `/sidebar`, not arbitrary
changes to `/sidebar/0/id`. Verification compares only the ordered IDs (the
official PUT does not write completion metadata). This mapping has **six
synthetic regression tests**, but no real 104 write/read-back yet. Do not
conflate it with enabling/disabling a section, which may use other operations.

### JOB_CONDITION serialization (experimental; no live write verification)

The official frontend uses `PUT /profile/ajax/resumeByBlock/jobCondition?vno=...`
with a nested `blockValueList.jobCondition.jobCondition` object and a
`blockValueList.jobCondition.themeChoose.selectedTheme` value. Unlike a raw
GET, the outgoing payload converts:

- `jobTimeType`, `jobWillType`, `jobTimePeriod`: arrays of objects to
  arrays of their `value` members
- `preferArea`, `preferJobType`, `preferJobIndustry`: arrays of objects to
  arrays of their `no` members
- `onBoardDate`, `salary`, `salaryPeriod`, `remoteWork`: selector
  objects to scalar `value` values (with branch-specific defaults)
- `preferJobTitle`: `text` member only
- `workShift`: Boolean to 0/1
- Salary option values: `1` negotiable, `2` company-standard, `3` per-case, `4` custom. **Only value 4 activates custom salary serialization.**
- Conditional arrival-date and salary controls: inactive branches are
  converted to empty strings, matching the current frontend `postData()`
- `themeChoose.selectedTheme`: selector object to scalar `value`

The current SDK allows replacement of known native job-condition fields, and
selected nested field paths. No theme write is implied: section theme editing
uses a different `LAYOUT` request. Unknown fields, malformed selectors and
unexpected arrays fail before any remote write. The encoder preserves all
known unaffected sibling fields. This has synthetic contract/read-back tests,
**not a confirmed real 104 PUT**.

### EXPERIENCE seniority-only update (experimental)

The frontend exposes an independent action for the overall seniority value:

```json
{"blockValueList":{"experience":{"seniority":3}}}
```

The synthetic value `3` above illustrates the shape, not an actual user
value. This uses `PUT /profile/ajax/resumeByBlock/experience?vno=...`.
It is **not** an update to `experiences[]`, which is a separate array with
its own POST/PUT/DELETE/sort workflows. The SDK allows only a replacement of
`/experience/formData/seniority/value`, verifies that value on read-back, and
does not send the experiences array. This mapping is source-observed and
synthetic-tested, but not live write-tested.

### SKILL records: POST / PUT / DELETE (experimental)

The 104 frontend's skill store uses the following source-mapped requests
with a `vno` query parameter:

- Create: `POST /profile/ajax/resumeByBlock/skill`
- Update: `PUT /profile/ajax/resumeByBlock/skill`
- Delete: `DELETE /profile/ajax/resumeByBlock/skill`

Create/update body:

```json
{"blockValueList":{"skill":{"skills":[{"name":"Synthetic",
"desc":"Example","tag":[{"text":"Tag","value":"tag-id"}],"sort":1}],
"themeChoose":{"selectedTheme":1}}}}
```

For creation, **omit** `sort` (the frontend sends `undefined`, which
JSON.stringify omits). Update uses the existing 1-based `sort`.
Delete sends:

```json
{"blockValueList":{"skill":{"skills":{"sort":[1]}}}}
```

The `skill` and `themeChoose` objects are specific to 104. The SDK
validates the current native list, known record fields, and the caller's
`resumeTimestamp` before issuing a request. The returned list must match
the intended create/update/delete change with all unrelated skill records
intact (allowing sort reindexing after deletion). Never confuse this with
`PUT /profile/ajax/swapRecordBySort/skill`, which handles reordering.
These operations have **synthetic tests but no real 104 write verification**.

### EDUCATION records: native CRUD (experimental)

The official frontend uses separate 104 endpoints:

- `POST /profile/ajax/resumeByBlock/education` — create a record
- `PUT /profile/ajax/resumeByBlock/education` — update a record
- `DELETE /profile/ajax/resumeByBlock/education` — delete one 1-based
  position using `{"blockValueList":{"education":{"educations":{"sort":[1]}}}}`

The POST/PUT body includes
`blockValueList.education.educations` (a **single-item array**) and
`themeChoose.selectedTheme`. Each record includes school ID/name, departments,
degree, duration, status, optional in-school status and foreign/region selection.
The frontend converts:

- Selector objects `highest`, `status`, date months and theme to `value`
- Department category options and `foreign` to their `no` identifiers
- `inSchoolStatus` to `""` unless the student is still in school
- General education ("普通科") to a first department without category types
- Abroad region to its special region-ID array

Create omits `sort`, while update uses the existing 1-based position. The
SDK refuses unknown/missing native fields and compares unchanged sibling
records after the write. Sorting itself uses `swapRecordBySort` and is
not implemented. **Contract and HTTP tests are synthetic, not real 104
read-after-write verification**.

### Non-atomic multi-section edits

One patch can target multiple supported sections (BIO, CERTIFICATE, SIDEBAR, JOB_CONDITION or EXPERIENCE seniority),
but the server receives separate PUT requests. The SDK validates all mappings before the first write and
verifies each section after saving it. A later error after earlier confirmed
writes raises `PartialWriteError` containing only block names; the failed
block's remote status may be ambiguous. Callers must inspect before retrying.

## Safe implementation approach for remaining blocks

1. Observe the official UI's operation and record only the **structure** of
   requests, never actual personal values.
2. Implement an encoder for exactly that block's input shape, distinguishing
   list insert/update/delete/reorder where appropriate.
3. Verify a concurrent-change precondition (the read document's
   `resumeTimestamp` and the server's `104-profile-ver` handshake).
4. Submit a single write; on ambiguous failure **do not blindly retry**.
5. Read the same block back and compare every requested field.
6. Report per-block success/failure, and never claim an atomic
   multi-block transaction if the upstream API commits per section.

Private live-test scripts and any original personal-data backups remain in a
private Modal directory. They are never part of the public repository.


### New source-mapped 104 operations (synthetic only)

- EXPERIENCE record CRUD: `/profile/ajax/resumeByBlock/experience`,
  with POST/PUT/DELETE and the frontend's salaried/part-time payload branch.
  Unlike the independently mapped seniority PUT, a record CRUD request
  addresses only the selected experience row.
- LANGUAGE record CRUD: `/profile/ajax/resumeByBlock/language`,
  with distinct `languages.local` and `languages.foreign` payloads.
  Linked certificates remain unsupported.
- LAYOUT theme: `PUT /profile/ajax/resumeByBlock/layout`
  with `blockValueList.layout.themeChoose.block` and `selectedTheme`.
  Valid options are fetched from the current `/profile/ajax/options`.
- Adjacent SKILL/EDUCATION reorder:
  `PUT /profile/ajax/swapRecordBySort/{section}`,
  with `blockValueList.{section}.{records}.sort={from,to}`.
  Non-adjacent moves remain unsupported pending verified semantics.

**None of these operations has passed real 104 write/read-back/restore
validation.** Media uploads, record deletion, linked certifications,
account-level information and hidden conditional controls are still outstanding.


### Experimental INFO form adapter (synthetic only)

Frontend module `c40f` sends
`PUT /profile/ajax/resumeByBlock/info?vno=...`.
The outgoing PUT body differs materially from a GET:
`blockValueList.info.info` includes only selected resume fields,
`blockValueList.info.addon` uses lowercase `addon` (the read response
uses `addOn`), and theme/summary selectors are flattened.
Military separation dates are conditional on status values 1 or 2.
Identity/account and media/upload actions are not included.

The SDK maps selected known INFO JSON Patch paths to a complete frontend-
compatible native body. It rejects unknown or absent selector shapes
instead of silently emptying their values. No real 104 INFO write has
been performed; this is contract reconstruction with synthetic tests.


### Real EXPERIENCE GET shape (read-only verification)

The 104 editor returned four experience records in **descending**
`sort` order (values 4, 3, 2, 1). Salary monthly/yearly fields
appeared as either integer or string depending on the record; company
size appeared as either a selector or an empty string. The upstream
serializer preserves numeric salaries and flattens nonempty company
size selectors to their `value`.

This was **read-only** validation, with no experience mutation.
Record creation and deletion may renumber positions, so the SDK does
not infer an array index from a 104 record's 1-based `sort` number.


### REFERRER native record requests (source-mapped, not live verified)

The public frontend module f5d8 issues POST or PUT to
/profile/ajax/resumeByBlock/referrer?vno=VERSION, sending the object
blockValueList.referrer with a one-element referrers array and
themeChoose.selectedTheme. The company field is the UI company selector's
text value. For DELETE, the object is
blockValueList.referrer.referrers.sort=[POSITION].

An authenticated read-only GET found referrer.formData={} on the designated
test resume. The current /profile/ajax/options has two referrer themes;
the editor uses its first one for a first POST. The new native writer
supports this branch without hard-coding an option ID. Real writes and
restoration remain unverified.


### Native LANGUAGE adjacent sort (source-mapped only)

The frontend's local/foreign drag-end sends a swapRecordBySort
request with blockValueList.language.languages. One of the two
groups contains sort={from,to}, while the other contains sort=[].
The SDK maps only adjacent swaps and verifies the other group's
content is unchanged. The designated test resume contains only one
record per group; no real sorting or restore has been performed.


### Native BIO POST and DELETE (experimental)

BIO creation in module 8d88 uses POST to
/profile/ajax/resumeByBlock/bio with
blockValueList.bio.bio={chi:HTML,eng:HTML}.

Whole-block clearing uses DELETE to the same endpoint, with
blockValueList.bio={chi:"",eng:""}.

These operations differ from the previously live-tested BIO PUT.
The SDK requires an empty form for POST, existing nonempty content
for DELETE, and exact independent read-back. Real POST/DELETE/restore
validation has not yet been performed.


### PROJECT no-media CRUD and adjacent sort

Frontend module 1d22 submits POST and PUT to
/profile/ajax/resumeByBlock/project with blockValueList.project.projects
containing one record, plus themeChoose.selectedTheme. Its postData()
converts duration month selectors into values, maps a nonempty
isInProgress state to 1 (otherwise 0), and maps a cover object to
file={type,content,ext}. The new adapter supports **type=0 only**
(no cover), with empty content and no ext. POST omits sort; PUT
includes the current sort. A first POST into empty formData uses the
first live optionsProjectTheme value.

DELETE submits blockValueList.project.projects.sort=[POSITION].
Adjacent reordering submits
blockValueList.project.projects.sort={from:FROM,to:TO} to
/profile/ajax/swapRecordBySort/project. There is no verification yet
of real populated project GET fields or write/read-back/restore.

### PORTFOLIO deletion, ordering and missing multipart upload

Frontend module 44aa deletes via DELETE
/profile/ajax/resumeByBlock/portfolio with
blockValueList.portfolio.sort=[POSITION]. This differs from the
PROJECT structure. Adjacent reorder uses
blockValueList.portfolio.portfolios.sort={from:FROM,to:TO} on the
swapRecordBySort/portfolio endpoint.

The real read-only GET response includes portfolio.formData.portfolios
with name, attach, attachType and sort. The attachment contains
name, status, url, fileId, thumbnailFileId, src and crawler.

**Not yet implemented:** POST multipart/form-data of binary file attachment,
generation of file previews and website link thumbnails, attachment
replacement and full lifecycle, as well as real write/restore tests.


### PORTFOLIO LINK=2 multipart fields (source-mapped)

The public editor's module 44aa and constants module 401c define a
link-only POST using FormData (LINK value 2) to
/profile/ajax/resumeByBlock/portfolio:

    blockValueList[portfolio][themeChoose][selectedTheme] = N
    blockValueList[portfolio][name] = ITEM_NAME
    blockValueList[portfolio][attachType] = 2
    blockValueList[portfolio][attach][name] = LINK_NAME
    blockValueList[portfolio][attach][url] = HTTPS_URL

The same-origin browser constructs the multipart boundary; its
104-profile-ver header must have come from an authenticated GET.
No file bytes, src key, upload signature, preview request or thumbnail
conversion is sent through this link-only path. Existing PORTFOLIO
siblings must be preserved; async preview metadata for the new record
is not relied upon for confirmation.

Binary file uploads, replacement, and preview/thumbnail processing
are still unimplemented. No real 104 link was posted in this session.


### CERTIFICATE empty formData, initialize PUT and clear DELETE

The 104 editor module 779c implements CREATE as UPDATE:
  PUT /profile/ajax/resumeByBlock/certificate
  blockValueList.certificate={certificates:[],others:TEXT}

The independent CLEAR branch uses:
  DELETE /profile/ajax/resumeByBlock/certificate
  blockValueList.certificate={certificates:"",others:""}

These are resume-local section operations, distinct from the
certifications API (account-global records) and certificationConnect
(resume/record associations). The current adapter intentionally blocks
clearing any populated association list. Both lifecycle operations
are synthetic-tested only and were not executed on the live test resume.


### REFERRER sort is a hard-coded pair swap

The site's public module f5d8.SORT sends the literal payload:

    blockValueList.referrer.referrers.sort={from:2,to:1}

It does not use the passed drag position. The adapter consequently
enables only the exactly-two-record branch and verifies both full
records swapped, without modifying any other form data.

### CUSTOM theme and no-media TEXT request planning

Public frontend module 5255 lists CUSTOM theme constants:
1=CLASSIC, 2=BANNER, 3=TEXT, 4=IMAGE, 5=MAGAZINE.
Module 4228.postData() converts
{custom:{name,sort,content:[...]},themeChoose:{selectedTheme:{value:3}}}
into blockValueList.custom with the numeric selected theme.
The TEXT branch forcibly maps file to a single
{type:0,content:"",ext:""} object; normalizes month selectors and
removes UI-only duration fields. Module 6330 normalizes populated
formData to an editable view model, but no real populated CUSTOM
GET has been inspected.

The source-mapped serializer supports exactly one text-only content
and only the TEXT theme. Its separate DELETE operation uses
blockValueList.custom.custom.sort=[DYNAMIC_SLOT] for custom1..custom6.
No CUSTOM POST/PUT/DELETE network path is enabled in the SDK yet.
The offline planner is available through the Python module and CLI.

### Certificate association actions are separate from record CRUD

Public frontend module 779c dispatches:
- SET_CERTIFICATION_CONNECT: api/certificationConnect/put
  with data {certIds:IDS} and resume vno;
- DELETE_CERTIFICATION_CONNECT: api/certificationConnect/delete
  with a record id and resume vno;
- DELETE_CERTIFICATION_OTHER: api/certificationConnect/deleteOther
  with the resume vno.

Exact deployed URLs and real reference/ID shapes are not yet verified.
The SDK offers non-writing source-level planners for these actions,
with positive integer IDs, no duplicates, and no mutations.


### Authenticated response normalization: CERTIFICATE and PROJECT

After a successful 104 certificate PUT, an initialized empty-link
GET block contains formData.certificate={others:TEXT,certifications:[]}
but no certificates property. Only when certifications is exactly
empty and certificates is absent can an outgoing certificates:[]
be inferred for the native writer. The native DELETE cleared the
temporary test text and an independent GET returned formData={}.

After a successful PROJECT no-media POST, GET normalizes month values
to option objects with text and value, uses [] for false progress,
and supplies img fields type, fileId, url, thumbnailStatus,
thumbnailUrl, the latter four empty for NONE type 0.
PROJECT one-item DELETE returned the original empty formData.
See tw104-live-smoke-report.md.
