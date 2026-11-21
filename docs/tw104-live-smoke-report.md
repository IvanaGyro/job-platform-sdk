# 104 test resume: authenticated integration results, 2026-11-17

The user explicitly authorized modification of the designated test resume.
Credentials, the selected resume identifier, real resume values and full
remote responses were held in a private Modal directory, not in Git.

## Preflight

- Fresh browser sign-in and same-origin API requests.
- Independent original BIO backup matched exactly.
- The entire native resume was separately backed up in a private 0600 file.
- PROJECT and CERTIFICATE started with empty formData.
- No account-global certifications or preexisting portfolio attachments
  were changed by these tests.

## Real write/read-back/restore

| Operation | Real server result | Original state restored? |
|---|---|---|
| CERTIFICATE initial PUT | Test-only text visible in an independent GET | Yes, by subsequent native DELETE |
| CERTIFICATE DELETE | HTTP 200; GET returned empty formData | Yes |
| PROJECT no-media first POST | HTTP 200; newly created record verified | Yes, by subsequent DELETE |
| PROJECT one-item DELETE | HTTP 200; GET returned empty formData | Yes |
| PROJECT record update (native SDK) | Real PUT changed a temporary record; read-back verified | Yes, by subsequent DELETE |
| PROJECT reorder | Not tested live | Not applicable |
| PORTFOLIO LINK=2 create and targeted DELETE | Live SDK POST, independent GET, native DELETE, GET | Original displayed item restored |
| PORTFOLIO PDF FILE=1 create and targeted DELETE | Live SDK binary POST, GET addressable file, DELETE, GET | Original displayed item restored |
| PORTFOLIO preview/conversion/download/sort | Not tested live | Not applicable |
| CUSTOM and certificate associations | Offline source mapping only | No write sent |

The initial CERTIFICATE write **succeeded**, but its pre-fix SDK
read-back validator raised VerificationError. The native GET returned
formData.certificate with fields others and certifications, not
certificates. The first native DELETE restored the exact empty formData,
and the original BIO and PROJECT remained unchanged. The SDK has since
been fixed and tested against a synthetic version of this real shape,
but the corrected wrapper **was subsequently rerun live** in a second
single-session integration cycle: initialize, independent GET, native
clear, independent GET all passed; the empty section was restored.

PROJECT first-created GET had month selectors containing text and value,
an empty array for isInProgress=false, and a NONE image object with
empty fileId, url, thumbnailStatus and thumbnailUrl. The SDK normalized
the GET shape and verified the new record, then removed it. Subsequent
GET confirmed the initial empty PROJECT block.

Full PORTFOLIO formData differed across sessions. A more conservative
link test compared the existing attachment display name, file ID and
type; that check failed, so no POST or DELETE was sent. Investigate
before permitting portfolio attachment modifications.

## Remaining verification

- CERTIFICATE whole-block field PUT beyond initialized text; account links.
- PROJECT adjacent or arbitrary record sorting.
- PORTFOLIO identity reconciliation, then reversible link create/delete.
- CUSTOM populated GET, remaining theme variants and media workflow.
- Account-global certificate CRUD and resume association lifecycle.
- Full 104 media, INFO, CUSTOM and UNDER18 editor coverage.

These results do not establish complete 104 editor parity.


## Second authenticated SDK-wrapper test (2026-11-17)

A later fresh browser session successfully executed these SDK methods
against the same initially empty test-resume sections:

1. Resume104Client.mutate_certificate_block initialize:
   returned persisted=true, verified=true.
2. Resume104Client.mutate_certificate_block clear:
   returned persisted=true, verified=true; GET confirmed empty formData.
3. Resume104Client.mutate_project create:
   returned persisted=true, verified=true.
4. Resume104Client.mutate_project update:
   changed only the temporary record name; returned verified=true.
5. Resume104Client.mutate_project delete:
   removed the temporary record; returned verified=true.

Final independent GET confirmed CERTIFICATE and PROJECT were both
empty, and the original BIO matched its private backup. The session
did not edit existing portfolio attachments, account-global
certifications, or personal information. This is the first completed
**real SDK-level create/update/delete** test for PROJECT, and the first
completed **real corrected SDK-level** certificate lifecycle test.


## Later PORTFOLIO live test cycles (2026-11-17)

The LINK=2 create successfully persisted a uniquely titled synthetic
test URL. A first cleanup guard blocked deletion because its
comparison wrongly considered changes to the original file's
opaque CDN/fileId/thumbnail access tokens to be evidence of a
different attachment. Private record-level comparison showed
that display name, attachment name and type were identical while
the opaque access fields rotated. A subsequent isolated SDK DELETE
identified only the synthetic link, removed it, and independently
verified that the original one displayed item remained.

A second session tested the new binary FILE=1 transport with a
generated 621-byte single-page synthetic PDF, containing no
personal information. The 104 service returned a persisted,
addressable file entry. SDK DELETE removed that unique test item,
and an independent GET confirmed the original single displayed
portfolio attachment identity remained. BIO, PROJECT and
CERTIFICATE were unchanged.

No new PDF thumbnailFileId was observed. The result does not
prove preview availability, downloaded file content, deletion of
underlying server blobs, or original attachment byte checksum.
Those items remain unverified.


## Authenticated PORTFOLIO adjacent sort verification

A subsequent live integration cycle inserted a temporary
synthetic link alongside the original file entry. The
source-mapped adjacent native PUT swapped their displayed
order; the independent GET and SDK verification succeeded.
The same two positions were swapped back, and a separate
GET confirmed the original order. Finally the synthetic
link was deleted by its current sort ID; exactly the
original single displayed file remained, while BIO,
CERTIFICATE and PROJECT were unchanged.

The test proves the adjacent two-item swap/reverse behavior
only. It does not establish non-adjacent moves for three
or more entries, file checksums, or preview generation.


## Subsequent CUSTOM, PORTFOLIO 3-item sort, REFERRER and SKILL tests

A private authenticated test-resume run established:
- CUSTOM TEXT=3 native POST→GET→PUT→GET→DELETE→GET with
  a synthetic short title; the native GET under custom1 contains
  formData.custom.{name,sort,content} and
  formData.themeChoose.selectedTheme. The NONE-media field in
  content includes empty fileId, url, thumbnailStatus and
  thumbnailUrl; duration months are empty objects and
  isInProgress is an empty array. The client adapter now
  recognizes and validates this exact native representation.
  A second live run of the actual Python SDK's text-only
  create/update/delete confirmed the same behavior and restored
  the original empty CUSTOM section.
- CUSTOM CLASSIC=1 and BANNER=2 source-defined native POST,
  PUT and DELETE completed successfully with a single synthetic
  no-media content item and exact restore. These themes are
  **not yet** enabled through the verified SDK writer.
- CUSTOM IMAGE=4 native POST accepted a generated 69-byte
  synthetic PNG with no personal content. The returned
  custom1 image theme used a single content entry whose file
  array contained two elements, not one (the site adds a
  placeholder). Native DELETE removed the temporary CUSTOM
  block; original empty state was independently confirmed.
- CUSTOM MAGAZINE=5 did **not** accept a no-media content
  POST, nor a POST with one synthetic PNG image. Both
  returned an upstream failure; no item was created and the
  original empty state was confirmed. Its missing mandatory
  content/media rule still needs discovery.
- PORTFOLIO native source action 1→3 on a three-item list
  produced [B,C,A], proving **insertion**, not endpoint swap.
  A second run using the actual SDK sort_records call
  returned verified=true, and both temporary links were
  subsequently deleted, restoring the original single
  displayed attachment.
- REFERRER SDK create/update/delete completed using a
  synthetic reference at example.invalid; independent GET
  confirmed each change and the original empty REFERRER form
  was restored. No real person or address was used.
- SKILL SDK create/update/delete completed using one
  temporary synthetic skill. The original two real skill
  records were preserved through read-back and final restore.

A separate read-only conversion-status probe used the exact
frontend BFF route but its authentication failed before any
request, so this route is **not** live validated. Conversion,
preview bytes, thumbnail generation and signed URL contents
remain outside the completed set.

All full native responses and test scripts remain in private
Modal files, outside the public repository. No actual
personal contact, skill content, private resume version or
credentials are committed.
