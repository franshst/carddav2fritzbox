# Tasks: CardDAV to FritzBox Sync

**Input**: Design documents from `/specs/001-carddav-fritzbox-sync/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Phase 1: Setup

- [x] T001 Create project structure per implementation plan
- [x] T002 Initialize Python project with dependencies in requirements.txt
- [x] T003 [P] Configure linting (flake8/black) in .flake8 and pyproject.toml

---

## Phase 2: Foundational (Research & Prerequisites)

**Purpose**: Core research and infrastructure that MUST be complete before user story implementation.

- [x] T004 Research FritzBox XML API for address book upload (authentication, endpoints, schema) - research.md
- [x] T005 Identify supported address book fields for FritzBox import - research.md
- [x] T006 Analyze vCard fields to determine necessary conversions (image Base64 -> JPG) - research.md
- [x] T007 Define intermediate Python data structure for contact representation - data-model.md
- [x] T008 Configure environment variables and logging for CLI in src/utils/logger.py

---

## Phase 3: User Story 1 - Sync Contacts (Priority: P1) 🎯 MVP

**Goal**: Copy and merge contacts from multiple CardDAV sources, normalize phone numbers, and overwrite FritzBox address book.

**Independent Test**: Verify that running the utility with a valid configuration merges contacts, normalizes phones, and updates the specified FritzBox address book.

### Implementation for User Story 1

- [x] T009 [P] [US1] Create Contact model in src/models/contact.py
- [x] T010 [P] [US1] Create Config loader for INI file in src/config/loader.py
- [x] T011 [US1] Implement CardDAV fetcher module in src/services/carddav_fetcher.py
- [ ] T012 [US1] Implement normalization/conversion module (phone/image) in src/services/converter.py
- [ ] T013 [US1] Implement FritzBox uploader module in src/services/fritzbox_uploader.py
- [x] T014 [US1] Implement CLI main entry point in src/main.py

---

## Phase 4: Validation & Polish

**Purpose**: Final testing and polish.

- [ ] T015 Write unit tests for data transformation and API mocking in tests/
- [ ] T016 Validate end-to-end sync with test config using quickstart.md
- [ ] T017 Documentation updates in docs/ and README.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: Can start immediately
- **Phase 2 (Foundational)**: Depends on Setup completion - BLOCKS US1
- **Phase 3 (User Story 1)**: Depends on Foundational completion
- **Phase 4 (Validation & Polish)**: Depends on US1 completion

### Parallel Opportunities

- T003, T009, T010 can be run in parallel where applicable.
