# 104 resume editor coverage inventory

This is a **104-only** implementation checklist, not a cross-platform resume
schema. Source: inspected 104 editor JavaScript modules and structural, value-
redacted GET responses (November 2026). The site can change at any time.

**Do not equate GET field presence, observed frontend calls, synthetic tests
and successful real 104 writes.** Each is a separate evidence level.

**Mainline implementation backlog:** [unimplemented-editor-fields.md](unimplemented-editor-fields.md).
This lists **only missing executable writers**, not existing but unverified
FOREIGN CREATE/DELETE, CLASSIC/BANNER, UNDER18 or other native actions.
Agents must choose the priority ID there instead of independent
infrastructure work. This inventory remains the separate real-site
verification record; local CI passes do not increase usable-field coverage.

| Native group | Frontend operation families seen | Implementation in this PR | Live 104 write/read-back |
|---|---|---|---|
| `info` | PUT; related identity and optional information | Source-mapped selected resume INFO fields (experimental); account/media excluded | **Motto PUT/read-back/exact restore**; remaining fields incomplete |
| `education` | POST, PUT, DELETE; ordering | Native record CRUD + adjacent swap sorting; domestic GET region normalization | **SDK CREATE/DELETE verified via two HTTP sessions and exact restore; UPDATE previously restored**; sorting unverified |
| `experience` | POST, PUT, DELETE; ordering, seniority | Native record CRUD accepts unordered contiguous GET sort keys; CREATE with companyVisibility=False fails before write | **SDK CREATE (companyVisibility=True), DELETE and exact restore independently verified on 2026-11-19**; prior UPDATE restored; hidden-company CREATE still unsupported |
| `jobCondition` | PUT; separate layout/theme PUT | Source-mapped full native form serializer, experimental | **preferJobContent PUT/read-back/exact restore**; other fields unverified |
| `skill` | POST, PUT, DELETE; ordering | Source-mapped record CRUD + adjacent swap sorting (experimental) | **CRUD restored**; sort/theme unverified |
| `certificate` | PUT, DELETE; certification connections | Existing text PUT/initialize/clear; **new browser-only official Vuex connect/disconnect writer**, no global certificate mutation | **Text SDK initialize + clear verified live**; association writer synthetic-only and live-blocked |
| `language` | POST, PUT, DELETE; local/foreign records | Native CRUD with duplicate IDs/type-changing UPDATE blocked, native per-kind count preflight, normalized contiguous sort identity; adjacent sort experimental; linked certificates blocked | **Local CREATE/DELETE exactly restored**; local/foreign UPDATE restored; a FOREIGN duplicate-type POST overwrote the original, then SDK UPDATE exactly restored it. Unique FOREIGN CREATE/DELETE unverified |
| `project` | POST, PUT, DELETE; reorder; attachments | No-media CRUD and adjacent reorder; media pending | **SDK create, update and delete verified live and restored**; sorting synthetic |
| `portfolio` | POST, DELETE; attachments/upload; reorder | LINK=2 POST, FILE=1 bounded binary POST, one-record DELETE, adjacent reorder; preview/conversion pending | **Browser and curl_cffi LINK/PDF CRUD restored; 2/3-entry insertion order verified**; preview/checksum/blob lifecycle unverified |
| `bio` | POST, PUT, DELETE | HTML PUT live-verified; first-create POST and clear DELETE experimental | **PUT only** |
| `referrer` | POST, PUT, DELETE; reorder | Native record CRUD, empty-form first-create, exactly-two-record hardcoded adjacent swap | **CRUD restored**; sort unverified |
| `sidebar` | PUT | Complete-list reorder only; metadata edits rejected | **One adjacent swap PUT and exact restore** |
| `layout` | PUT | Per-section themes using current 104 options; FILE token-safe verifier | **JOB_CONDITION theme PUT and restore via SDK verified**; other themes/sections unverified |
| `custom` | POST, PUT, DELETE | **SDK TEXT=3 CRUD live**; CLASSIC/BANNER raw native CRUD live and **new single no-media SDK/CLI/HTTP CRUD synthetic-tested**; IMAGE=4 synthetic PNG raw native create/delete live; MAGAZINE incomplete | TEXT SDK real; CLASSIC/BANNER new wrappers synthetic-only |
| `under18` | POST, PUT | **New guarded native create/update SDK, CLI and HTTP** with explicit identity acknowledgement; synthetic-tested only | **No real populated GET or live write** |

For source details see [104 upstream contract](tw104-upstream-contract.md).
Some frontend functions call additional endpoints not in `resumeByBlock`, such
as certificate association, media uploads, and record sort operations.

### P0-07 certificate association via official browser Vuex — 2026-11-21

The deployed frontend module 779c dispatches
`form/certificate/setCertificationConnect` and
`form/certificate/deleteCertificationConnect` to its own
`api/certificationConnect/put` and `delete` actions.
A new *browser-only* `mutate_certificate_connections` uses those
**existing official UI actions**, not a guessed `/profile/ajax` URL.
It only operates on account-owned certificate IDs with source UI's
20-item import cap, checks the editor's active `vno`, and GET-verifies
`certifications[].items[].id` plus all existing certificate
metadata and unrelated resume sections. Separate CLI and authenticated,
opt-in HTTP PUT/DELETE actions exist. No account-global
`api/certifications/delete` is called.

**Evidence status:** frontend source mapping + synthetic tests only.
Earlier proxy #6 login failed, but on 2026-11-21 a fresh authorized
**proxy #1 login succeeded**, and independent real 104 resume GETs
succeeded. The user-selected test resume's `certificate.formData` is
currently **empty**, not an initialized grouped `certifications` list.
The inspected `/profile/`, `/profile/set/`, `/profile/intro` page views
did not expose `window.$nuxt?.$store`. Importantly, the current
`/profile/intro` redirected to `/resumes/`, which 104 identifies as a
**public resume template site** (not a personal resume editor); the
`/resumes/{vno}/about` URL constructed from the backend `versionNo`
landed on the site's not-found page. Do not operate on any public
example profile in that directory. The correct personal editor action
bridge, account-owned certificate option list and populated certificate
GET still need live identification. **No real certificate link/unlink
write was sent; no independent persistence/read-back/restore was
achieved; newly live-verified fields: 0.** P0-08 stays deferred until
P0-07 truly passes live CRUD. No cookies, titles, identifiers or
certificate values are recorded in this public evidence note.

## Latest evidence — 2026-11-18

The user-authorized test resume completed independently read-verified and
reversible proxy-bound HTTP writes for BIO PUT, PORTFOLIO LINK POST/DELETE,
generated PDF FILE POST/DELETE, JOB_CONDITION text PUT, INFO motto PUT, and
SIDEBAR adjacent reorder PUT. The original BIO/INFO/JOB_CONDITION forms,
SIDEBAR order and PORTFOLIO display identities were restored. Private
credentials, backups and real resume content remain outside the repository.
**A verified field does not imply an entire section is complete.**

The first detached HTTP LAYOUT attempt was inconclusive; a follow-up
authenticated GET confirmed its private backup was unchanged. A subsequent
browser PUT did change JOB_CONDITION's selected theme, but verification
initially failed because unrelated PORTFOLIO FILE access URLs rotate on every
GET. A **read-only double GET** identified only four volatile FILE fields:
fileId, thumbnailFileId, src and url. The verifier now masks exactly those
FILE access fields, never LINK destination URLs or user-editable names and
metadata. The live SDK then **switched and restored JOB_CONDITION's theme**,
verifying the exact original section after restoration. Other section themes
are unverified.

Subsequent EDUCATION testing revealed and fixed a normalization gap:
a successful POST may return an empty region selector for a domestic school
and schoolId=0. The SDK now accepts exactly that empty-region case if the
foreign flags are empty, while still refusing ambiguous foreign geography.
It successfully recreated, independently verified and deleted the uniquely
named synthetic row. A second HTTP session confirmed the original two
education rows and full formData were restored. Earlier UPDATE evidence
is independent.

### LANGUAGE foreign duplicate-type semantics — 2026-11-19

- An authorized real `FOREIGN` POST used valid 104 option selectors
  but the proposed type already existed in that branch. 104 **changed
  the existing first row** instead of appending another record. The
  SDK did not claim a successful CREATE (VerificationError).
- Before writing, one browser login was passed to two independent
  original-proxy HTTP transports; the original LANGUAGE formData was
  backed up. After the unexpected overwrite, SDK FOREIGN UPDATE with
  the original selectors returned `verified=True`; independent GET
  confirmed **exact restoration of the entire LANGUAGE formData**.
- Important distinction: 104's `optionsLanguageType` dropdown chooses
  the **foreign/dialect category**, while `languages.foreign[].type` and
  `languages.local[].type` carry a **concrete language ID within the kind**.
  The frontend module `96e2` serializes these row selectors. A collision
  across the two different collections does not represent a duplicate.
- The deployed frontend's LANGUAGE INSERT first looks for a matching
  language ID **in the same kind**. A duplicate dispatches PUT against the
  existing `sort` instead of POST; a previously unseen ID dispatches POST.
  In the UI's type-changing edit flow, it can then DELETE the former record.
  These behaviors support separate SDK CREATE/UPDATE with explicit collision
  rejection; a create request must never be silently promoted to an edit.
  Because a type-changing frontend UPDATE can involve deleting the old row,
  the SDK blocks **every** language type-changing UPDATE for now, including
  changes to otherwise-unused IDs; proficiency-only UPDATE remains supported.
- The 104 editor uses `optionsForeignType`/`optionsLocalType`, and separate
  `optionsLanguageForeignLevel`/`optionsLanguageLocalLevel` proficiency lists.
  SDK CREATE/UPDATE now fetches the live option catalog, verifies the value
  and text for every submitted selector, and refuses bad/missing options
  before HTTP. For CREATE, it also fetches the previously read-only-verified
  `/profile/ajax/inputField` and checks `language.<kind>.count`; missing,
  non-integer and exhausted limits fail before POST. Native GET ordering is
  canonicalized by the unique contiguous `sort` identity, not raw array
  position; duplicates and unrelated metadata/certificate changes fail
  verification. This is **source-mapped and synthetic-tested**, not additional
  live-write evidence. Read-only SDK `get_language_editor_options()` now
  exposes current native selectors, occupied and unused type IDs, count and
  `resumeTimestamp`; `language-options` CLI and an authenticated HTTP GET
  expose the same result. These new read APIs have **synthetic parity tests
  only** and do not establish that unique FOREIGN CREATE is live supported.
- The source-mapped encoder now rejects same-kind LANGUAGE CREATE when
  the target type already exists, before HTTP. Existing types must be
  edited with UPDATE. This rejection applies to both local and foreign
  to avoid accidental overwrites. Type-changing UPDATE also rejects
  collision with another existing language ID, before sending HTTP.
  Synthetic upstream-overwrite tests reject supposed CREATE success and
  never resend an ambiguous mutation. This does **not** prove that a genuinely
  new FOREIGN type CREATE is accepted by 104. Certificate associations
  remain excluded.

### Continued read-only and guarded FOREIGN checks — 2026-11-20

Three private, single-login test attempts were made with no 104 mutation:

- Proxy index #4: browser login reached authenticated state, but the
  transferred HTTP reader could not establish authenticated resume GET.
- Proxy index #6: browser login and both independently derived HTTP sessions
  read the same resume successfully; the source-mapped BFF
  `api/resumes/input-validation?form=language` read was denied. The test
  stopped **before POST**. This does not prove login/session expiration or
  a Cloudflare challenge.
- Proxy index #6, last attempt: browser authentication did not complete.
  No additional proxy cycling was attempted.

The native legacy read-only `/profile/ajax/inputField` contract is documented
from previous 2026-11-17 site evidence, but it could not be rechecked online
in this continuation. No new live FOREIGN CREATE/DELETE result was obtained;
all private test logs and backups remain outside Git. There is no newly
created test item or pending write recovery from these attempts.

### Successful EXPERIENCE CRUD and cleanup — 2026-11-19

- One authorized browser login on a currently functional proxy transferred
  credentials to **two independent original-proxy HTTP transports**.
  A uniquely marked synthetic fifth EXPERIENCE row was **created by the
  SDK** with companyVisibility=True; the SDK returned
  `verified=True` and independent GET confirmed exactly one new row,
  all four originals unchanged and no metadata changes.
- The same authenticated writer then **SDK-deleted** that fifth row;
  the SDK returned `verified=True` and an independent GET confirmed
  the **exact original EXPERIENCE formData** plus unchanged BIO.
  Both steps used fresh resume timestamps and one submission per mutation.
- A prior synthetic fifth row from the earlier failed cycle was also
  successfully **SDK-deleted** after guarded preflight verification,
  independently GET-confirming exact original restoration.
- An earlier POST with companyVisibility=False was stored as True.
  The SDK now rejects this unsafe CREATE choice **before submitting
  HTTP**, rather than creating a record with unexpected company-name
  visibility. Hidden-company CREATE is not verified/supported.
- Real sign-in checks found PDA entry HTTP 403 can coexist with working
  official sign-in. The adapter now records 403 and attempts
  signin.104.com.tw for *non-challenge* PDA entry 403.
  Explicit Cloudflare challenges continue to stop authentication.

### Live test continuation — 2026-11-18

- LANGUAGE local: one browser login was transferred to two independently
  created, original-proxy-bound curl_cffi sessions. A unique, site-option-
  sourced second local-language record was created, independently GET-verified
  and SDK-deleted. An independent GET confirmed the exact original LANGUAGE
  formData; both SDK calls reported verified=true.
- EXPERIENCE: a synthetic fifth record **did persist** after a POST,
  but the server returned companyVisibility=true for a request containing
  false. SDK deliberately raised VerificationError instead of treating the
  mismatch as successful. A subsequent GET placed sort=5 in the *second*
  array position, yielding [4,5,3,2,1] instead of descending order. The
  original four rows and section metadata were unchanged. The record
  reader now accepts **any permutation** of unique, contiguous sort IDs,
  rather than using array order as record identity.
- **Historical cleanup blocker (resolved 2026-11-19):** the SDK
  initially rejected the unexpected GET sort permutation and could
  not delete the temporary row; subsequent proxy failures postponed
  cleanup. Later a guarded SDK DELETE, with independent second-session
  read-back, exactly restored the original full section.
- Treat the server's companyVisibility coercion as a **real mismatch**,
  not an accepted normalization. Future tests must not silently replace
  false with true or claim this field is verified. Only the test record
  is eligible for the future guarded deletion; unrelated user records
  must remain untouched.

HTTP 409/412 conflict and ambiguous-write handling have synthetic tests.
Local `Set-Cookie` rotation passed a loopback wire test. Server-side
104 stale-version rejection and real cookie rotation remain unverified.

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

### Revision safety across all native 104 writers — 2026-11-20

A cross-provider-layer code audit found that direct native actions previously
compared Python `str()` representations without first checking that the 104
`resumeTimestamp` was present and valid. It was theoretically possible for a
GET missing the timestamp and a caller providing `None`/`"None"` to match.
All SDK native writes and API preflights now use a shared typed revision
validator that rejects these invalid cases before sending or reserving a
write. Synthetic tests exercise every native writer against absent/invalid
revisions and representative HTTP DELETE/PATCH routes, checking that no
network write or Idempotency-Key reservation occurs. This is client-side
safety only: server-side revision enforcement is still unverified.

### Read-only editor field limits — 2026-11-20

The SDK/CLI/local authenticated HTTP API now expose `get_editor_limits()`
through the official read-only `GET /profile/ajax/inputField` metadata route.
The source-to-section names are mapped from the deployed frontend's
`inputField.data`/`jsonInputField` bindings, including plural `projects`,
`portfolios`, `referrers` and `customs`. The returned JSON is strictly
filtered to recognized numeric/bool metadata (`count`, `maxLength`,
`minLength`, `htmlMaxLength`, `min`/`max`, `required` and related bounds).
No raw text, regex, arrays or private resume fields are returned. The
result explicitly distinguishes an empty known group from a missing group,
rejects unknown sections and size/depth anomalies, and reports
`limits_available` without inventing constraints. This is **synthetic-tested
and source-mapped only**; no new 104 login, server read or write was made.
`inputField` limits do not prove that the SDK can write every named field.

### JSON Patch preflight and supported-path discovery — 2026-11-20

The previously permissive `plan_edit` preview now validates the real writer
whitelist and serializes each changed block before returning a plan. It rejects
missing/invalid `resumeTimestamp`, unsupported account/media fields,
non-replace mutations, invalid INFO selectors and SIDEBAR metadata changes
*without* making any upstream write. Read-only `test` conditions can reference
other native fields without granting those fields write permission. The CLI
`writable-paths`, SDK `supported_patch_paths` and token-protected HTTP
`GET /v1/tw104/writable-paths` list the exact locally mapped `replace` paths;
these are **not** universal edit permissions, and custom/media/record CRUD
have separate operations. The plan endpoint returns affected block names and
`atomic:false`. All evidence for this continuation is synthetic.

## Canonical next work and evidence standards (2026-11-21)

**Use [the missing executable writer backlog](unimplemented-editor-fields.md)
for all new field implementation tasks.** It lists the specific known
unimplemented 104 fields/operations with binding P0/P1 IDs and separately
identifies Cake, Yourator and Greenhouse provider gaps. Do not start from
the historical milestones below: they predate the newer source-mapped SDK,
media-conversion, batch and idempotency features.

Existing but unverified features (especially FOREIGN CREATE/DELETE) remain
**live-validation tasks**, not missing implementations. Only authorized
website writes plus independent GET and exact restoration count as a new
usable-field result. If site authentication/API calls fail, state the
blocker and **zero new live-verified fields** instead of reporting code
coverage, mock tests or CI as user-facing product progress.

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
unmapped custom fields and generic PATCH to UNDER18 remain unsupported.
A separate guarded UNDER18 POST/PUT SDK/CLI/HTTP writer was later added,
but its exact native populated GET contract is still synthetic-tested only.
The authorized test resume has no UNDER18 key in its authenticated GET;
real identity GET/write/restore evidence is unavailable.


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


### PORTFOLIO two-entry sort live test (2026-11-17)

With one original file and one temporary synthetic LINK item,
Resume104Client.sort_records(..., portfolio, 1, 2) executed
the official swapRecordBySort/portfolio PUT. Its native GET
showed the expected exact reversal of displayed identities,
and the SDK returned verified=true. A second adjacent
swap reversed the order again; then the unique synthetic LINK
was deleted, restoring the original single displayed file.

This is an authenticated live test of **one two-entry adjacent
swap and its reverse**, not a proof of non-adjacent or arbitrary
multi-record ordering. Signed file tokens and previews are not
part of the stable displayed identity comparison.


### Batch preflight for workflow safety — 2026-11-21

Added a separate read-only `plan_batch` SDK method, CLI `batch-plan`,
and bearer-authenticated local HTTP `POST /v1/tw104/resumes/{id}/batch/plan`.
This API validates the *whole* batch's structural allowlist, then checks
only the **first** native step against current GET data and relevant source-
mapped backend options/capacity, without sending any upstream write.
Later steps are explicitly deferred because previous mutations can change
native sort IDs, available options or form structure. Response fields
include `network_write_sent:false`, `persisted:false`, and
`current_site_write_success_verified:false`. No personal field values,
raw serialization bodies or selectable option labels are included.
The new tests cover SKILL, LANGUAGE, LAYOUT theme, BIO PATCH, bearer,
If-Match, CLI dispatch and strict failure before write; all synthetic.
A preview cannot guarantee actual persistence or detect a subsequent
concurrent change. No live account was accessed to develop this.

### Non-atomic ordered batch of already-supported writers — 2026-11-21

New `batch_edit.py` statically validates ordered 104 native record CRUD,
JSON Patch, section theme and record sort steps before starting. The batch
is explicitly limited to 12 steps and does not widen the source-mapped
record/field coverage or introduce remote endpoints. It excludes UNDER18,
media uploads, guessed certificate association endpoints, and anything
without a separately implemented safe native writer. Each step calls the
existing SDK write method and checks its verified persistence; current
`resumeTimestamp` and all known non-target blocks are re-read before
continuing. If a writer could have partially succeeded or the site was
edited concurrently, it stops without retry/rollback, returning safe step
labels through the existing `PartialWriteError` interface. The CLI and
local HTTP routes share the contract and the HTTP route supports durable
SQLite idempotency. Synthetic tests validate the real skill SDK call path,
preflight, revision changes, partial outcome, HMAC request fingerprint,
HTTP bearer and persistent replay; no live 104 authentication was needed.

### Optional durable HTTP Idempotency-Key journal — 2026-11-21

All earlier entries describing HTTP idempotency as *in-memory only*
represent the previous default implementation. A new opt-in SQLite journal
is now available via `JOB_PLATFORM_IDEMPOTENCY_DB` or
`create_app(idempotency_db_path=...)`. The default remains in-memory.
The journal is validated before authenticating a browser session; it
requires an absolute owner-private POSIX local file and records opaque
HMAC-hashed route/key identities, request fingerprints, result state and
successful response metadata, not original request bodies. A potentially
committed remote operation is reserved as `indeterminate` before network
I/O; only confirmed success updates it. A crash, timeout or failure to
commit the success status leaves the reservation persisted, and after a
service restart repeating that key returns HTTP 409 rather than sending
another request. Synthetic restart tests cover resume creation, SKILL
update, UNDER18 sensitive-field privacy, collisions and ambiguous results.
The file must remain outside the repository and on a persistent private
volume; an ephemeral GitHub-hosted runner's SQLite file is **not** durable
across jobs. The HTTP service remains single-worker only; this journal is
neither a server-side 104 transaction nor globally shared account locking.
No real account, resume edit or remote write was used to test this.

### Cross-section preservation for direct native CRUD — 2026-11-20

The earlier `save_edit()` hardening checked collateral block changes during
JSON Patch. Direct SKILL, EDUCATION, EXPERIENCE, LANGUAGE, PROJECT, REFERRER,
BIO, CERTIFICATE, CUSTOM, PORTFOLIO LINK/FILE, sorting and layout writes
now apply the same guard to their own successful target read-back. In
particular, a modified value can no longer be considered verified if
another native block or numbered CUSTOM slot was destroyed by the same
request. The four existing FILE-only volatile URL/token exceptions are
retained; LINK destinations and all other saved metadata remain strict.

Synthetic regressions deliberately corrupt another block after 14
otherwise successful native mutations and confirm **one submitted request,
no retry and verification failure**. Separate tests show unrelated FILE
access-token rotation remains acceptable, whereas unexpected LINK URL
changes are rejected. This is read-back detection, not server-side
transaction isolation, repair, legal-account-state verification or proof
of new 104 live compatibility. No new live login or mutation was made.

### Guarded UNDER18 age/identity POST/PUT — 2026-11-20

The retained official Vuex source dispatches `api/resumeByBlock/post` or
`api/resumeByBlock/put` with `block=UNDER18`, and exactly
`blockValueList.under18={birthdayDocument,idType,selfIdentityConfirmed}`.
The new standalone `under18_records.py` and
`Resume104Client.mutate_under18()` map these two native requests, requiring
all three correctly typed fields, strict `resumeTimestamp` matching,
non-replacement of a populated CREATE, an existing UPDATE target, and an
**additional explicit acknowledgement** of sensitive age/identity writing.
Each submitted action must read back exactly those fields while preserving
all other known resume sections. New CLI `under18` and HTTP POST/PUT
`/v1/tw104/resumes/{resume_id}/under18` are experimental and require opt-in;
HTTP additionally requires bearer authentication, Idempotency-Key and
`X-Identity-Write-Acknowledgement:true`. No ambiguous response is retried;
SDK/HTTP result objects omit all identity fields.

The authorized real test resume did not include UNDER18, so populated GET
and all integrated create/update/restore behavior remain **synthetic-only**.
No real age/identity data was collected, read, submitted or committed. This
is an experimental separate native action, **not** a general-purpose JSON
Patch write path, nor a validated legal-identity verification workflow.

### Multi-section PATCH preservation and revision race checks — 2026-11-20

Target-only read-back could previously accept seniority changes that
destroyed the `experience.formData.experiences` array, or BIO/CERTIFICATE
text updates whose collateral effect modified unrelated metadata.
`patch_verification.py` now verifies the full stable sibling blocks,
non-target fields of BIO/CERTIFICATE/EXPERIENCE, and all SIDEBAR record
metadata; not merely target values or reordered IDs. The existing
narrow four-field exception for rotating PORTFOLIO **FILE** URLs/tokens
is reused, but LINK URLs remain strict. Multi-section saves perform a
fresh GET and global revision check **between** sequential PUTs, detecting
an external update that arrived after the previous read-back.
Synthetic tests include clobbered work history, certification links,
BIO metadata, sidebar row metadata, changed LINK URLs, rotating FILE
tokens, metadata-only revision races and failed later PUT preservation.
These guards remain best-effort and **not a 104 server-side atomic write**.
No website login or mutation was involved in this refactor.

### CUSTOM theme content slot limits and offline capabilities (2026-11-20)

The deployed production Vue bundle module `5255` exports a per-theme
`contentNumber` mapping: **CLASSIC=1, BANNER=1, TEXT=1, IMAGE=2,
MAGAZINE=2**. An older generic source-mapped encoder allowed up to six
content items even for CLASSIC/BANNER; that did not match the official
editor and was corrected. The offline IMAGE planner allows one or two
images because a one-PNG raw POST was accepted on 2026-11-17, with native
GET showing two file positions afterward. The MAGAZINE planner now only
constructs a complete two-content candidate; earlier native MAGAZINE POSTs
failed, and a two-content candidate is **not yet live-tested or accepted**.
No new real-site mutations were performed for this update.

New static discovery: Python `Resume104Client.supported_custom_themes()`,
CLI `job-platform custom-themes`, and bearer-authenticated local HTTP
`GET /v1/tw104/custom-themes`. They return non-personal, read-only
frontend content limits and explicit evidence/available writer scopes,
without opening a browser, logging in, or reading a resume. The response
sets `current_site_availability_verified:false`; source mapping alone is
not proof that the live site accepts the request.

### Guarded CLASSIC/BANNER no-media SDK/CLI/HTTP (2026-11-20)

Earlier private live raw 104 POST, PUT and DELETE succeeded for CUSTOM
CLASSIC=1 and BANNER=2 and restored the original test slot. The new
`mutate_custom_layout()` wraps these native actions with a checked
`resumeTimestamp`, known empty-slot CREATE, current official theme option
on CREATE, exact non-media GET shape on UPDATE/DELETE, one content item,
limited markup/URL/date/progress serialization, fresh read-back of the full
expected content, and equality checks for every other CUSTOM slot. The
API and CLI require explicit experimental opt-in; HTTP also requires bearer
and an Idempotency-Key and refuses ambiguous request replay. These new
**SDK/CLI/HTTP wrappers have synthetic tests only** and did not initiate
new website writes during this development. Unrecognized media metadata,
IMAGE/MAGAZINE, multi-content layouts and theme conversions fail closed.
Do not count earlier raw endpoint successes as a live verification of the
new integrated wrapper, and do not infer blob/preview deletion guarantees.

### Latest CUSTOM, REFERRER, SKILL, and PORTFOLIO 3+ sorting

An authenticated CUSTOM TEXT=3 SDK POST/PUT/DELETE roundtrip
was completed and restored. Its native GET is now modeled in
custom_text_contract.py and exposed through SDK, CLI and local
bearer-only HTTP. CLASSIC=1 and BANNER=2 native POST/PUT/DELETE
succeeded with no-media content; IMAGE=4 accepted a synthetic
69-byte PNG and was deleted. IMAGE GET has a two-entry file
array even for one submitted image. MAGAZINE=5 POST failed
both with no media and with one PNG; not yet supported.

The official PORTFOLIO 3-item 1→3 operation is insertion
([A,B,C] becomes [B,C,A]), not swapping endpoints. An actual
SDK sort_records test verified this operation with independent
GET, then safely deleted two synthetic links and preserved
the existing original portfolio entry. Other sections still
restrict sorting to adjacent positions unless separately tested.

REFERRER create/update/delete and SKILL create/update/delete
also passed real SDK tests and exact logical restore. This
does not establish their advanced theme/sort behavior or
other conditional editor options.

The official read-only convert-status BFF route is now
source-mapped through SDK, CLI and HTTP; a live probe
failed authentication before the request, so conversion
status/preview is **not** real verified.
