# Feature Specification: CardDAV to FritzBox Sync Utility

**Feature Branch**: `001-carddav-fritzbox-sync`

**Created**: 2026-08-11

**Status**: Draft

**Input**: User description: "I want a commandline utility to copy and merge several carddav contact lists from a nextcloud instance, and write them to a fritz box address book. The utility must normalize telephone numbers into a canonical intermediate form (`+` country code + number), then shorten them for the local FritzBox region/country (specified in a configuration file) or keep them international when their country code differs from the book's."

## Clarifications
### Session 2026-08-11
- Q: Clarify operational context (cron) → A: Tool is a non-interactive CLI utility designed for periodic execution via cron (daily/few times a day).
- Q: Clarify error handling and state management → A: On failure, output human-readable errors to stderr. The tool is stateless and always starts from the beginning.
- Q: How is contact identity defined for duplicate checking/merging? → A: A contact is considered identical when the name and either a telephone number or email address matches.
- Q: Should the utility delete contacts from the FritzBox address book that are no longer present in any of the CardDAV sources? → A: Yes, perform a mirror sync (pruning contacts not present in CardDAV sources).
- Q: Which FritzBox address book should be used, and should existing entries be preserved or overwritten? → A: The utility must sync to a specified address book in FritzBox (defined in config) and completely overwrite all entries within it (mirroring the CardDAV sources).
- Q: How should the priority of CardDAV sources be determined when resolving conflicting single-occurrence fields? → A: Based on the sequential order of CardDAV sources defined in the configuration file (first defined has highest priority).
- Q: Should the telephone number normalization process sanitize non-numeric characters (such as spaces, hyphens, and parentheses) before processing and comparison? → A: Yes, sanitize numbers by stripping all non-numeric characters (preserving leading '+' for country/international detection).
- Q: How should contact display names be formatted when exporting to FritzBox? → A: The utility must support a configurable name ordering parameter (`name_order = first_name_first` | `last_name_first`) in the configuration file to determine whether contacts are formatted as "First Last" (e.g., *John Doe*) or "Last, First" (e.g., *Doe, John*) in the FritzBox `<realName>` field.

### Session 2026-08-19
- Q: What should the tool do with a source telephone number that cannot be normalized (e.g., no digits remain after sanitization, or an unparseable string)? → A: Skip the number, keep the contact with its remaining valid numbers, and log a warning to stderr.
- Q: Should the configured area code always be required, or may it be absent for regions without area codes? → A: Mandatory — the config always defines `country_code` and `area_code`; missing values cause a clear validation error.
- Q: After contacts are merged, should duplicate identical telephone numbers (and email addresses) within a contact be removed? → A: Yes — multi-occurrence fields are appended only when unique; identical values are kept once (first occurrence wins), telephone numbers compared in canonical normalized form and email addresses case-insensitively.

## User Scenarios & Testing

### User Story 1 - Sync Contacts to FritzBox (Priority: P1)

A user wants to synchronize their contacts from multiple CardDAV-compliant sources (like a Nextcloud instance) into a single address book on their FritzBox device, with telephone numbers automatically normalized into a canonical form for comparison and deduplication, then shortened for FritzBox storage. The utility is designed for non-interactive, scheduled execution via cron. It is stateless and handles errors by outputting messages to stderr.

**Why this priority**: Core functionality required to achieve the user goal.

**Independent Test**: The tool can be run with configuration pointing to valid CardDAV sources and a target FritzBox address book in a non-interactive environment. Upon failure (e.g., disconnected CardDAV source), it outputs a readable error to stderr and exits with a non-zero status.

**Acceptance Scenarios**:

1. **Given** valid configuration for one or more CardDAV sources and FritzBox, **When** the tool is executed (non-interactively), **Then** all contacts from the CardDAV sources are merged, normalized, and visible in the FritzBox address book.
2. **Given** a contact with a local telephone number (same country as the FritzBox book), **When** the tool is executed (non-interactively), **Then** the number is normalized to the canonical form (`+` country code + number) and then shortened for FritzBox by removing the `+` and country code, prepending a leading `0`, and removing the area code when it equals the configured area code (the trunk `0` and area code are not dialed within the same area, leaving the bare subscriber number).
3. **Given** a contact with an international telephone number (country code different from the FritzBox book's country), **When** the tool is executed (non-interactively), **Then** the number is normalized to the canonical form (`+` country code + number) and stored in that canonical form without shortening.
4. **Given** a connectivity failure to a CardDAV source, or FritzBox target **When** the tool is executed, **Then** it outputs a human-readable error message to stderr and exits with a non-zero status.
5. **Given** a contact exists in the target FritzBox address book but is NOT in any CardDAV source, **When** the tool is executed, **Then** the contact is deleted from the FritzBox address book.

---

### User Story 2 - Automated Credential Handling (Priority: P2)

The user wants the utility to securely handle credentials for both the CardDAV sources and the FritzBox without requiring manual input or storing them in plain text.

**Why this priority**: Essential for security and non-interactive (cron) usability.

**Independent Test**: The tool can be executed securely (e.g., via cron) using environment variables or a configuration file that is not committed to source control, without any interactive prompts.

**Acceptance Scenarios**:

1. **Given** credentials defined in secure environment variables, **When** the tool is executed non-interactively, **Then** it authenticates successfully without prompting for manual input.

---

### Edge Cases

- What happens when a source telephone number cannot be normalized (e.g., no digits remain after sanitization)? → The number is skipped, the contact is kept with its remaining valid numbers, and a warning is logged to stderr.
- What happens when the configuration is missing `country_code` or `area_code`? → The tool exits with a clear, human-readable error to stderr and a non-zero status.
- What happens when a source number already starts with `+`? → It is treated as already normalized and used as-is for comparison and shortening.
- What happens when a merged contact contains the same telephone number (or email address) from multiple sources? → The value is stored once (first occurrence wins); telephone numbers are compared in canonical normalized form and email addresses case-insensitively.

## Requirements

### Functional Requirements

- **FR-001**: System MUST be able to fetch contact data from multiple CardDAV-compliant sources.
- **FR-002**: System MUST be able to authenticate securely with the FritzBox to manage its address book without user interaction.
- **FR-003**: System MUST provide a command-line interface suitable for non-interactive execution (e.g., via cron) for triggering a sync process.
- **FR-004**: System MUST merge contact data from multiple sources:
    - A contact is identified as identical if the name and either a (normalized) telephone number or an email address matches.
    - Fields representable only once (e.g., picture, home address) MUST be taken from the first encountered contact based on the sequential order of sources defined in the configuration file.
    - Fields allowing multiple occurrences (e.g., telephone numbers, email addresses) MUST be merged by appending them, but only when unique: duplicate identical values MUST be dropped (keeping the first occurrence). Telephone numbers are compared in canonical normalized form (FR-018); email addresses are compared case-insensitively.
- **FR-005**: System MUST normalize telephone numbers into a canonical intermediate form containing only digits and a leading `+` (international access) sign: if the number starts with `+`, it is already normalized; if it starts with the numeric international access code from config (e.g., `00` in Europe, `09` in the US), replace that code with `+`; if it starts with `0`, replace the leading `0` with `+` followed by the configured country code; otherwise prepend `+`, the configured country code, and the configured area code without its leading zero.
- **FR-006**: System MUST shorten telephone numbers for the FritzBox telephone book: keep numbers whose country code differs from the book's configured country in canonical form; otherwise remove the `+` and country code, prepend a leading `0`, and remove the area code when it equals the book's configured area code (the trunk `0` and area code are not dialed within the same area, leaving the bare subscriber number, e.g. in the Netherlands).
- **FR-007**: System MUST ensure no sensitive credentials are stored in plaintext.
- **FR-008**: System MUST provide informative, non-interactive logging to stderr/stdout for monitoring cron job success or failures.
- **FR-009**: System MUST output human-readable error messages to stderr upon failure.
- **FR-010**: System MUST remain stateless (no memory of previous jobs) and start from the beginning on each execution.
- **FR-011**: System MUST perform a mirror sync, deleting any contacts in the target FritzBox address book that do not exist in the source CardDAV contact lists.
- **FR-012**: System MUST sync contacts to a specified address book in FritzBox (provided via config) and completely overwrite all its entries (via mirror sync).
- **FR-013**: System MUST determine CardDAV source priority using the sequential order of sources defined in the configuration file (first defined has highest priority).
- **FR-014**: System MUST sanitize telephone numbers by stripping all non-numeric characters (such as spaces, hyphens, parentheses, or dots) while preserving any leading `+` character prior to performing normalization and comparison.
- **FR-015**: System MUST format contact display names (`<realName>`) according to a user-configured name order preference (`name_order = first_name_first` for "First Last" vs `name_order = last_name_first` for "Last, First").
- **FR-016**: System MUST setup and use Python virtual environments with required dependencies before executing any Python testing operations, ensuring test isolation and consistent environments.
- **FR-017**: System MUST require `country_code` and `area_code` in the configuration and fail with a clear, human-readable error if either is missing.
- **FR-018**: System MUST compare telephone numbers (for contact identity and deduplication) always using the normalized canonical form.
- **FR-019**: System MUST skip a source telephone number that cannot be normalized (e.g., no digits remain after sanitization), keep the contact with its remaining valid numbers, and log a warning to stderr.

### Key Entities

- **Contact**: Contact information whose telephone numbers are stored internally in canonical normalized form (for comparison/deduplication) and shortened only at FritzBox export time.
- **Address Book**: Target container on FritzBox.
- **Config**: Configuration file containing FritzBox credentials, regional settings (`country_code`, `area_code`, international access code), target address book name, and name ordering preference (`name_order`).

## Success Criteria

### Measurable Outcomes

- **SC-001**: Sync process completes for 100 contacts in under 5 minutes.
- **SC-002**: 100% of valid telephone numbers are correctly normalized to the canonical form and shortened for FritzBox according to the config settings.
- **SC-003**: No security incidents related to credential leakage are reported.

## Assumptions

- FritzBox device is accessible on the network.
- CardDAV sources are standard-compliant.
- Credentials are provided securely.
- Telephone numbers stored without a country/area code in a source are assumed to belong to the configured local region.
