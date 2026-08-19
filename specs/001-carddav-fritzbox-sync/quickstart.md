# Quickstart Validation Guide

## 1. Prerequisites
- Python 3.x installed
- Access to a CardDAV-compliant server (e.g., Nextcloud)
- Access to a FritzBox device

## 2. Setup
1. Create a `config.conf` in INI format with:
   - CardDAV source URLs and credentials
   - FritzBox URL, credentials, and target address book name
   - Regional settings (country_code, area_code, international access code)
2. Ensure the configuration file is excluded from git.

## 3. Execution
Run the sync command:
```bash
python3 src/main.py --config config.conf
```

## 4. Expected Outcome
- The utility should fetch all contacts from CardDAV sources.
- Normalize telephone numbers to the canonical form and shorten them for the FritzBox based on regional settings.
- Merge contacts based on identity (name + phone/email).
- Upload the merged list to the specified FritzBox address book, overwriting existing entries.
- Informative progress logging to stderr.
- Exit with code 0 on success, non-zero on error.
