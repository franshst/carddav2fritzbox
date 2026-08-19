# Tasks: CardDAV to FritzBox Sync

**Input**: Design documents from `/specs/001-carddav-fritzbox-sync/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Included below. The existing pytest suite (36 tests) and the spec's acceptance scenarios require tests for the reworked components. Write/update them to verify each redo.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions
- `REDO` prefix = existing implementation must be reworked (see audit notes in each phase)

## Task Audit Summary (2026-08-19)

The spec was clarified (Session 2026-08-19: canonical number normalization/shortening, mandatory `country_code`/`area_code`, skip-unnormalizable) and the tech stack was adapted in `/speckit.plan` (dropped `caldav`, use `requests`+`vobject`, config schema change). Consequences for the current task list:

- **REDO (built against pre-clarification spec / old stack)**: config loader schema + validation (FR-017), `PhoneNumberNormalizer` algorithm (FR-005/006/019), CardDAV fetcher (currently mocked), Contact identity comparison (FR-018), FritzBox uploader (missing PBKDF2 auth), CLI `main.py` (contains an `IndentationError` at line 156 and wires old config fields).
- **ADD**: real RFC 6352 CardDAV fetch, PBKDF2 auth, User Story 2 (credential handling) phase, focused tests for reworked components, venv cleanup (`caldav` no longer needed).
- **OK (no change)**: setup, research/foundational, Contact/Config/uploader scaffolding structure, image conversion pipeline (Pillow).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Create project structure per implementation plan
- [x] T002 Initialize Python project with dependencies in requirements.txt
- [x] T003 [P] Configure linting (flake8/black/isort) in pyproject.toml

**Note**: `requirements.txt` was adapted during `/speckit.plan` — `caldav` removed (CalDAV-only, no RFC 6352 support), `isort` added. T015 below verifies the cleanup.

---

## Phase 2: Foundational (Research & Prerequisites)

**Purpose**: Core research and infrastructure that MUST be complete before user story implementation

- [x] T004 Research FritzBox XML API for address book upload (authentication, endpoints, schema) - research.md
- [x] T005 Identify supported address book fields for FritzBox import - research.md
- [x] T006 Analyze vCard fields to determine necessary conversions (image Base64 -> JPG) - research.md
- [x] T007 Define intermediate Python data structure for contact representation - data-model.md
- [x] T008 Configure environment variables and logging for CLI in src/utils/logger.py

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Sync Contacts (Priority: P1) 🎯 MVP

**Goal**: Copy and merge contacts from multiple CardDAV sources, normalize phone numbers (canonical form for comparison, shortened for FritzBox), and overwrite the target FritzBox address book.

**Independent Test**:
1. `pytest tests/unit/test_converter.py tests/unit/test_config.py tests/integration/test_sync_workflow.py` passes.
2. `python src/main.py --config config.ini --validate-only` exits 0 with a valid config; exits 1 with a clear stderr error when `country_code` or `area_code` is missing (FR-017).
3. `python src/main.py --config config.ini --dry-run` fetches, merges, and normalizes contacts without uploading.

**Why REDO**: The US1 components were scaffolded against the pre-clarification spec: the normalizer used a contradictory heuristic, the CardDAV fetcher returns mock data instead of connecting, and `main.py` has an `IndentationError` at line 156 (empty `for` loop) so the CLI cannot run.

### Rework of User Story 1 (REDO)

- [x] T009 [P] [US1] REDO Contact model: make identity/deduplication compare the canonical normalized phone form (FR-018) in src/models/contact.py
- [x] T010 [P] [US1] REDO Config loader: rename `region_code` -> `area_code`, add `international_access_code`, make `country_code` and `area_code` mandatory with a clear, human-readable error when missing (FR-017) in src/config/loader.py and sample-config.ini
- [x] T011 [P] [US1] REDO CardDAV fetcher: replace the mock `_fetch_source_contacts` with a real RFC 6352 fetch using `requests` — resolve `addressbook-home-set` (`.well-known/carddav` / PROPFIND), then `REPORT addressbook-query` for `address-data`; parse returned vCards with `vobject` (see contracts/carddav-api.md) in src/services/carddav_fetcher.py
- [x] T012 [P] [US1] REDO PhoneNumberNormalizer: implement the canonical normalization algorithm (FR-005: leading `+` passthrough, international-access-code replacement, leading `0` -> `+`+country code, else prepend `+`+country+area code) and FritzBox shortening (FR-006: keep canonical if foreign country; else drop `+`+CC, add leading `0`, remove area code when equal) in src/services/converter.py
- [x] T013 [P] [US1] REDO FritzBox uploader: add PBKDF2-HMAC-SHA256 challenge-response for FRITZ!OS 7.24+ (challenge prefix `2$`), keeping the legacy MD5 path (research.md section 2.1) in src/services/fritzbox_uploader.py
- [x] T014 [US1] REDO CLI main: fix the empty `for` loop causing `IndentationError` at src/main.py:156 and wire the new config fields (`area_code`, `international_access_code`) into the normalizer in src/main.py
- [x] T015 [P] [US1] Remove `caldav` from the venv and confirm no `import caldav` remains in src/; verify runtime imports `requests`, `vobject`, `PIL` from .venv

### Tests for User Story 1

- [x] T016 [P] [US1] Unit tests for canonical normalization, FritzBox shortening, and skip-unnormalizable-with-warning (FR-005/006/019) in tests/unit/test_converter.py
- [x] T017 [P] [US1] Unit tests for config validation: missing `country_code`/`area_code` raises a clear error (FR-017) in tests/unit/test_config.py
- [x] T018 [P] [US1] Unit tests for PBKDF2 and MD5 challenge-response calculation in tests/unit/test_fritzbox_auth.py
- [x] T019 [US1] Integration test: fetch from a mocked DAV server, merge by priority, normalize, and produce the FritzBox XML phonebook in tests/integration/test_sync_workflow.py

**Checkpoint**: At this point, User Story 1 is fully functional and testable independently.

---

## Phase 4: User Story 2 - Automated Credential Handling (Priority: P2)

**Goal**: Securely handle credentials for CardDAV sources and FritzBox without manual input or plaintext storage (FR-002, FR-007, spec User Story 2).

**Independent Test**: Run `--validate-only` with NO credentials in the config file but with credentials set via environment variables — it validates successfully without prompting for input.

**Why ADD**: This user story is missing entirely from the task list. The current loader only reads credentials from the INI file.

### Implementation for User Story 2

- [x] T020 [US2] Implement environment-variable credential resolution in src/config/loader.py (e.g. `FRITZBOX_USERNAME`/`FRITZBOX_PASSWORD`, `CARDDAV_<n>_USERNAME`/`CARDDAV_<n>_PASSWORD`) with precedence: environment variable over config file value
- [x] T021 [P] [US2] Document env-var credential override usage in README.md (config.ini is already excluded from git via .gitignore)

### Tests for User Story 2

- [x] T022 [P] [US2] Unit tests for env-var credential resolution and precedence in tests/unit/test_config.py

**Checkpoint**: User Stories 1 and 2 both work independently.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and cleanup affecting all user stories

- [x] T023 Run quickstart.md end-to-end validation against a test config (dry-run, then upload if a FritzBox is available)
- [ ] T026 Real-device end-to-end test: ask the user to confirm config.ini is correctly filled with test credentials (real CardDAV sources and FritzBox, NOT production data), then run `python src/main.py --config config.ini --validate-only` and `--dry-run` against the real services; run a real upload only after explicit user confirmation (mirror sync completely overwrites the target phonebook)
- [ ] T024 [P] Full quality gate: `pytest`, `flake8`, `black --check`, `isort --check` all pass
- [x] T025 Documentation updates in docs/ and README.md

### User-Reported Fixes (real-device validation round, 2026-08-19)

Fixes for issues found in the T023 real upload: the phonebook kept its stock
name, numbers were uploaded in full length, and an ANWB number (`31703141414`,
E.164 without `+`) was mangled to `+312031703141414`.

- [x] T027 Fix `canonicalize_phone`: recognize E.164-without-`+` (country code present, 8-12 digit remainder) before the area-code fallback in src/models/contact.py; tests in tests/unit/test_contact.py + tests/unit/test_converter.py
- [x] T028 Wire FR-006 export shortening: pass the `PhoneNumberNormalizer` into `FritzBoxUploader` and apply `format_for_fritzbox` in `_convert_contact_to_xml`; tests in tests/unit/test_fritzbox_auth.py
- [x] T029 Resolve the target phonebook by name via TR-064 (`X_AVM-DE_OnTel:1`, Digest auth): add src/services/tr064.py, resolve/create `target_book` in the uploader, fall back to book 0 when TR-064 is unreachable; tests in tests/unit/test_tr064.py + test_fritzbox_auth.py
- [x] T030 Re-verify on the real device: `--validate-only` + `--dry-run` exit 0; real upload goes into the book named `target_book` with shortened numbers and the ANWB number intact. Verified: book "Test" (index 1, real id 2) holds the contacts, ANWB `0703141414` + `0882692888` present, numbers shortened. Also confirmed the box silently drops numberless contacts on import (probe book test); uploader now skips them with a warning so the reported count matches the box (see T031)
- [x] T031 Skip contacts without a phone number in `FritzBoxUploader.upload_phonebook` with a warning (the FritzBox import silently drops them); test in tests/unit/test_fritzbox_auth.py

Bugs found in the T030 re-verification: shortening stripped the area code from
local numbers (Amsta `020-448-6970` became the non-dialable `04486970`), the
fetcher dropped roughly a third of the contacts (vCard line folding was
destroyed, so cards with photos/base64 were rejected), and cross-source
duplicates were not merged.

- [x] T032 Fix FR-006 shortening: `PhoneNumberNormalizer.shorten` keeps the area code for foreign-area local numbers but removes it together with the trunk `0` when it equals the configured area code (the area code is not dialed within the same area, e.g. in the Netherlands), leaving the bare subscriber number; amend spec.md FR-006 + data-model.md; regression test `020-448-6970` -> `4486970` in tests/unit/test_converter.py
- [x] T033 Fix vCard line folding: `CardDAVFetcher._split_vcards` preserves line endings and continuation whitespace so vobject can unfold folded lines (RFC 6350 §3.2); tests in tests/unit/test_fetcher.py
- [x] T034 Wire FR-004 merging: `CardDAVFetcher.merge_contacts` collapses cross-source duplicates by identity (priority-1 wins, multi-value fields appended) and `src/main.py` calls it after fetch; tests in tests/unit/test_fetcher.py

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Complete (no dependencies)
- **Foundational (Phase 2)**: Complete (depends on Setup)
- **User Story 1 (Phase 3)**: Depends on Foundational; redo tasks can proceed in parallel
- **User Story 2 (Phase 4)**: Depends on T010 (config loader) — env-var resolution extends it
- **Polish (Phase 5)**: Depends on US1 and US2 completion; T026 (real-device test) requires user-confirmed test credentials in config.ini and runs after T014/T023

### User Story Dependencies

- **User Story 1 (P1)**: No dependencies on other stories; this is the MVP.
- **User Story 2 (P2)**: Depends on US1's config loader (T010); otherwise independently testable.

### Within User Story 1

- REDO tasks T009-T013 touch different files and can run in parallel
- T014 (main.py) depends on T010, T011, T012, T013 — do it last
- Tests T016-T019 verify the reworked components

### Parallel Opportunities

- T009-T013 (REDO tasks) can run in parallel (distinct files)
- T016-T018 (unit tests) can run in parallel
- T020 (US2) can start as soon as T010 is complete

---

## Parallel Example: User Story 1

```bash
# Launch all REDO tasks together (different files, no interdependencies):
Task: "REDO Contact model in src/models/contact.py (T009)"
Task: "REDO Config loader in src/config/loader.py (T010)"
Task: "REDO CardDAV fetcher in src/services/carddav_fetcher.py (T011)"
Task: "REDO PhoneNumberNormalizer in src/services/converter.py (T012)"
Task: "REDO FritzBox uploader PBKDF2 in src/services/fritzbox_uploader.py (T013)"

# Then wire them together (depends on T010-T013):
Task: "REDO CLI main in src/main.py (T014)"

# Launch unit tests in parallel:
Task: "Tests for converter in tests/unit/test_converter.py (T016)"
Task: "Tests for config validation in tests/unit/test_config.py (T017)"
Task: "Tests for PBKDF2 in tests/unit/test_fritzbox_auth.py (T018)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete REDO tasks T009-T014 (US1)
2. Add/update tests T016-T019
3. **STOP and VALIDATE**: run the US1 Independent Test above
4. Optionally deploy/demo the working sync

### Incremental Delivery

1. Finish US1 (MVP) -> test independently -> deploy/demo
2. Add US2 (credential handling) -> test independently
3. Run Polish phase (full quality gate)

### Parallel Team Strategy

- Developer A: US1 REDO tasks T009-T013
- Developer B: US1 tests T016-T019 + venv cleanup T015
- Developer C: US2 (T020-T022) once T010 lands

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- REDO tasks replace the corresponding scaffolded implementations; do not layer new logic on top of the old contradictory behavior
- Verify tests fail before implementing each rework (where tests exist)
- Commit after each task or logical group
- Avoid: vague tasks, same-file conflicts, cross-story dependencies that break independence
