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
| `certificate` | PUT, DELETE; separate certification connections | Existing certificates/others PUT only, experimental | **No** (test formData empty) |
| `language` | POST, PUT, DELETE; local/foreign records | Native local/foreign record CRUD + adjacent local/foreign sorting (experimental); linked certificates blocked | **No** |
| `project` | POST, PUT, DELETE; reorder; attachments | Read/plan only | No |
| `portfolio` | POST, DELETE; attachments/upload | Read/plan only | No |
| `bio` | POST, PUT, DELETE | HTML PUT live-verified; first-create POST and clear DELETE experimental | **PUT only** |
| `referrer` | POST, PUT, DELETE; reorder | Native record create/update/delete with empty-form initialization (experimental); sorting pending | **No** |
| `sidebar` | PUT | Complete-list reorder only; metadata edits rejected | **No** |
| `layout` | PUT | Theme selection for 11 native sections using current 104 option values (experimental) | **No** |
| `custom` | POST, PUT, DELETE | Not implemented | No |
| `under18` | POST, PUT | Not implemented | No |

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
4. Extend the synthetic Python SDK, HTTP API and CLI test matrix; harden durable
   idempotency, remote-conflict reconciliation and login recovery.

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
- This revision uses **synthetic tests only** for all new operations.
  **BIO remains the only real 104 edit/write/restore-verified operation.**


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
- This revision uses **synthetic tests only** for all new operations.
  **BIO remains the only real 104 edit/write/restore-verified operation.**


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


### Optional durable at-most-once HTTP ledger (2026-11-17)

An opt-in SQLite file reserves SHA-256 hashed request identities and
fingerprints before the FastAPI server sends 104 mutations. It stores
neither raw resume content, contact values, credentials nor responses.
Atomic uniqueness prevents duplicate reservations, including across
service workers. After restart a known key returns 409 rather than a
replayed 200, whether the earlier write succeeded or not. This is
duplicate-prevention, not remote state reconciliation.
The private database and its directory must be retained securely.
