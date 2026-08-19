# Implementation Plan: CardDAV to FritzBox Sync Utility

**Branch**: `001-carddav-fritzbox-sync` | **Date**: 2026-08-19 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-carddav-fritzbox-sync/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command; its definition describes the execution workflow.

## Summary

Build a stateless, cron-friendly CLI that merges contacts from multiple CardDAV sources (Nextcloud) into a single FritzBox address book via mirror sync. Telephone numbers are normalized to a canonical `+CC…` form for comparison/deduplication, then shortened for FritzBox per the clarified 3-stage model (FR-005/006/018/019). Stack: Python 3.13, `requests` + `vobject` for CardDAV (the `caldav` package is CalDAV-only and is removed), `Pillow` for JPEG conversion, stdlib XML/configparser/logging. FritzBox upload uses the `login_sid.lua` challenge-response auth and multipart POST to `/cgi-bin/firmwarecfg` (research.md §2–3).

## Technical Context

**Language/Version**: Python 3.13 (venv at `.venv`, targets py310+ per pyproject)

**Primary Dependencies**: `requests` (HTTP for CardDAV + FritzBox), `vobject` (vCard parsing), `Pillow` (baseline-JPEG image conversion). Dev: `pytest`, `flake8`, `black`, `isort`. The `caldav` dependency is **removed** (no RFC 6352 address-book support; see research.md §8.2).

**Storage**: Configuration files (INI, `configparser`; excluded from git)

**Testing**: pytest (unit/integration), flake8/black/isort for style

**Target Platform**: Linux server (cron)

**Project Type**: CLI utility

**Performance Goals**: <5 mins for 100 contacts

**Constraints**: Stateless, non-interactive, mirror sync (pruning), secure credentials

**Scale/Scope**: Manageable contact lists

**API/Integration Research Areas**:
- CardDAV API (RFC 6352): direct `requests` PROPFIND/REPORT, `vobject` parsing — resolved in research.md §8
- FritzBox `login_sid.lua` auth + `/cgi-bin/firmwarecfg` upload — resolved in research.md §2–4
- Data Mapping: CardDAV fields → Intermediate Py representation → FritzBox XML fields — research.md §6, data-model.md
- Image conversion: Base64 (from CardDAV) → Binary/JPG (for FritzBox) — research.md §7
- Phone-number normalization/shortening algorithm — resolved in spec.md FR-005/006/017/018/019 (Session 2026-08-19)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Clean Code (PEP 8)**: PASSED — existing code is PEP 8; black/isort configured.
- **Simple CLI Interface**: PASSED — single `main.py` entry with `--config/--log-level/--dry-run/--validate-only`, exit codes 0–4.
- **Minimal Dependencies**: PASSED — removed non-functional `caldav`; runtime deps reduced to 3 (`requests`, `vobject`, `Pillow`), all justified.
- **Public APIs Only**: PASSED — RFC 6352 (CardDAV) and the FritzBox phonebook XML import endpoint are documented, public interfaces.
- **Secure Credential Management**: PASSED — credentials from local INI excluded from git / env vars.
- **Modern Python Standards**: PASSED — Python 3.13, dataclasses, type hints, stdlib `logging`.

## Project Structure

### Documentation (this feature)

```text
specs/001-carddav-fritzbox-sync/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
│   ├── cli.md           # CLI command schema
│   ├── carddav-api.md   # CardDAV RFC 6352 interface
│   └── fritzbox-api.md  # FritzBox phonebook import interface
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
carddav2fritzbox/
├── requirements.txt     # requests, vobject, Pillow (runtime); pytest, flake8, black, isort (dev)
├── pyproject.toml       # black/isort/pytest config
├── sample-config.ini    # documented example (no real credentials)
├── src/
│   ├── main.py          # CLI entry point (argparse, orchestration, exit codes)
│   ├── config/
│   │   ├── loader.py    # INI parsing, validation (mandatory country_code/area_code), dataclasses
│   ├── models/
│   │   └── contact.py   # Contact, PhoneNumber, EmailAddress dataclasses
│   ├── services/
│   │   ├── carddav_fetcher.py   # RFC 6352 discovery + REPORT fetch, vobject parsing, merge
│   │   ├── converter.py         # PhoneNumberNormalizer (FR-005/006), ImageConverter, validate_and_normalize
│   │   └── fritzbox_uploader.py # login_sid.lua auth, phonebook XML gen, multipart upload
│   └── utils/
│       └── logger.py    # stderr logging setup
└── tests/
    ├── contract/        # contract tests (empty placeholder)
    ├── integration/     # end-to-end sync workflow tests (mocked DAV/FritzBox)
    └── unit/            # converter/logger unit tests
```

**Structure Decision**: Single flat project (Option 1). The codebase already follows this layout; no restructuring needed. A `src/` package layout is used so tests import `src.*` without path hacks.

## Complexity Tracking

> No constitution violations — nothing to justify. All requirements fit the single-project layout with the minimal dependency set.
