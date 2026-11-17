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
| PORTFOLIO link POST or DELETE | Aborted in preflight: existing attachment identity differed from first private snapshot | No write sent |
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
