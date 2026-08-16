<!-- Sync Impact Report:
Version change: 0.2.0 → 0.2.1
Modified principles: Added copyright notice.
Added sections: None.
Removed sections: None.
Follow-up TODOs: Populate [SECTION_2_NAME], [SECTION_2_CONTENT], [SECTION_3_NAME], [SECTION_3_CONTENT], [GOVERNANCE_RULES].
-->

# carddav2fritzbox Constitution

## Core Principles

### I. Clean Code (Pythonic)
Adhere to PEP 8 standards and idiomatic Python practices. Prioritize code readability, maintainability, and simplicity in all implementations.

### II. Simple CLI Interface
Expose all core functionality through a simple, intuitive command-line interface. Use standard streams (stdin/stdout/stderr) and follow predictable command-line conventions.

### III. Minimal Dependencies
Favor the Python standard library for all implementations. Introduce external dependencies ONLY when absolutely necessary, and keep them to the absolute minimum required.

### IV. Public APIs Only
Interact exclusively with stable, well-documented, public-facing APIs. Avoid undocumented, internal, or non-public interfaces.

### V. Secure Credential Management
NEVER commit passwords, API keys, or other sensitive credentials to source control. Use secure mechanisms such as environment variables, local configuration files excluded from git, or secure system-level secret storage.

### VI. Modern Python Standards
Utilize modern, supported Python syntax and language features. Do not use deprecated modules, functions, or language constructs.

## TODO(SECTION_2_NAME): Define Section 2
[SECTION_2_CONTENT]

## TODO(SECTION_3_NAME): Define Section 3
[SECTION_3_CONTENT]

## Governance
<!-- Constitution supersedes all other practices; Amendments require documentation, approval, migration plan -->

TODO(GOVERNANCE_RULES): Define governance rules (e.g., All PRs/reviews must verify compliance; Complexity must be justified; Use [GUIDANCE_FILE] for runtime development guidance)

**Version**: 0.2.0 | **Ratified**: 2026-08-11 | **Last Amended**: 2026-08-11
