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
- Conditional arrival-date and salary controls: inactive branches are
  converted to empty strings, matching the current frontend `postData()`
- `themeChoose.selectedTheme`: selector object to scalar `value`

The current SDK allows replacement of known native job-condition fields, and
selected nested field paths. No theme write is implied: section theme editing
uses a different `LAYOUT` request. Unknown fields, malformed selectors and
unexpected arrays fail before any remote write. The encoder preserves all
known unaffected sibling fields. This has synthetic contract/read-back tests,
**not a confirmed real 104 PUT**.

### Non-atomic multi-section edits

One patch can target multiple supported sections (BIO, CERTIFICATE, SIDEBAR or JOB_CONDITION),
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
