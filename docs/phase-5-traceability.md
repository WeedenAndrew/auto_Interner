# Phase 5 traceability

Phase 5 uses only `fictional_base_resume.docx`, which contains reserved example domains,
a 555 telephone number, and invented education, employer, projects, and metrics. No
personal resume is read by tests or fixture builders.

| Contract | Implementation | Evidence |
|---|---|---|
| `F-RWR-001` PII separation | `ResumeDocument.model_payload` | contact-exclusion and request tests |
| `F-RWR-002` safe rephrase/reorder | `validate_rewrite` | valid rewrite test |
| `F-RWR-003` exact schema | `REWRITE_INPUT_SCHEMA` plus local checks | malformed-response tests |
| `F-RWR-004`–`006` structural truth | section and locator validation | omission, addition, duplicate, unknown tests |
| `F-RWR-007` protected paragraphs | reader flags PII/hyperlinks read-only | protected-paragraph tests |
| `F-RWR-008`–`010` metric truth | exact metric multisets | changed, removed, and added number tests |
| `F-RWR-011`–`012` technology truth | base-wide technology allow set | adjacent invention and existing-skill tests |
| `F-RWR-013` proficiency truth | escalation-term comparison | escalation test |
| `F-RWR-014` contact truth | contact-pattern rejection | introduced-contact test |
| `F-RWR-015` instruction containment | JSON data plus untrusted-data prompt | adversarial request test |
| `F-DOC-001` stable extraction | `read_resume` | required sections and stable-ID tests |
| `F-DOC-002`–`004` copied patch/reorder | `assemble_resume` | source-hash and section-order tests |
| `F-DOC-005` geometry/styles | pre/post document checks | geometry and formatting test |
| `F-DOC-006` hyperlinks | untouched OOXML relationships | hyperlink target test |
| `F-DOC-007` metadata privacy | namespace-preserving package scrub | metadata, rsid, timestamp test |
| `F-DOC-008` collision safety | no-replace publication | existing-artifact test |
| `F-DOC-009` shadow safety | early write-free result | missing-directory shadow test |
| `F-DOC-010`–`012` preconditions and failure cleanup | prepared path, source hash, temporary cleanup | fault tests |
| `F-DOC-013` usable artifact | reopen plus filename contract | Word-open and package tests |

The document visual gate inspected the one-page base and generated output in Microsoft
Word. LibreOffice was unavailable on the development machine, so the standard renderer
could not produce PNGs; direct Word opening provided the stronger compatibility check
and exposed an initial XML namespace defect that was corrected before completion.
