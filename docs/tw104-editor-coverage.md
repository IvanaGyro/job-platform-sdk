# 104 resume editor coverage inventory

This is a **104-only** implementation checklist, not a cross-platform resume
schema. Source: inspected 104 editor JavaScript modules and structural, value-
redacted GET responses (November 2026). The site can change at any time.

**Do not equate GET field presence, observed frontend calls, synthetic tests
and successful real 104 writes.** Each is a separate evidence level.

| Native group | Frontend operation families seen | Implementation in this PR | Live 104 write/read-back |
|---|---|---|---|
| `info` | PUT; related identity and optional information | Read/plan only | No |
| `education` | POST, PUT, DELETE; ordering | Read/plan only | No |
| `experience` | POST, PUT, DELETE; ordering, seniority | Seniority-only PUT source-mapped; records read/plan only | **No** |
| `jobCondition` | PUT; separate layout/theme PUT | Source-mapped full native form serializer, experimental | **No** |
| `skill` | POST, PUT, DELETE; ordering | Source-mapped record CRUD (experimental); sorting remains unavailable | **No** |
| `certificate` | PUT, DELETE; separate certification connections | Existing certificates/others PUT only, experimental | **No** (test formData empty) |
| `language` | POST, PUT, DELETE; local/foreign records | Read/plan only | No |
| `project` | POST, PUT, DELETE; reorder; attachments | Read/plan only | No |
| `portfolio` | POST, DELETE; attachments/upload | Read/plan only | No |
| `bio` | POST, PUT, DELETE | Chinese and English content replacement | **Yes**, including restore |
| `referrer` | POST, PUT, DELETE | Read/plan only | No |
| `sidebar` | PUT | Complete-list reorder only; metadata edits rejected | **No** |
| `layout` | PUT | Not implemented | No |
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
2. Implement separate 104 encoders for `info`, repeating record groups, media
   and layout; validate every supported JSON Patch path before network I/O.
3. Live-test each source-mapped operation on the designated test resume,
   using private backups and exact read-back/restore where reversible.
4. Add a test matrix for HTTP API, Python SDK and CLI; harden durable
   idempotency, remote-conflict reconciliation and login recovery.

Current definitions:

- **Verified:** Real 104 mutation submitted, exact changed-value read-back,
  then original restored and independently read back.
- **Experimental:** Upstream source-mapped serializer plus synthetic tests,
  with no successful real 104 write/read-back yet.
- **Unavailable:** No safe writer; PATCH is rejected rather than guessed.

The scope is **only 104**. No common data schema or adapter behavior is being
designed for other job platforms.
