# CLI Contract

Command-line interface for the CardDAV-to-FritzBox sync utility.

## Invocation

```
python src/main.py --config <path> [--log-level LEVEL] [--dry-run] [--validate-only]
```

| Flag | Required | Default | Description |
|---|---|---|---|
| `--config PATH` | Yes | — | Path to the INI configuration file. |
| `--log-level LEVEL` | No | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `--dry-run` | No | off | Validate config, fetch/process contacts, and print a summary without uploading to FritzBox. |
| `--validate-only` | No | off | Validate configuration and exit without fetching or syncing. |

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success (or dry-run completed) |
| 1 | Configuration error / validation failure |
| 2 | Connection error (CardDAV source or FritzBox unreachable) |
| 3 | Sync error (upload failed) |
| 4 | General/unexpected error |

## Streams

- **stdout**: informational progress and dry-run summaries.
- **stderr**: warnings (e.g., unnormalizable phone numbers per FR-019), human-readable errors per FR-009, and log records at the configured level.

## Config File Shape

INI format parsed with `configparser` (case-preserving keys). Sections:

```ini
[general]
name_order = first_name_first        # first_name_first | last_name_first

[fritzbox]
url = http://fritz.box
username = <user>
password = <password>
target_book = CardDAV Sync

[regional]
country_code = +49                   # REQUIRED (FR-017)
area_code = 30                       # REQUIRED (FR-017)
international_access_code = 00       # REQUIRED for normalization (FR-005)

[source_1]
url = https://nextcloud.example.com/remote.php/dav/addressbooks/users/<user>/
username = <user>
password = <password>
priority = 1                         # unique, 1-based, no gaps
```

Credentials must never be committed; the file is excluded from git. See `data-model.md` for the full config model and validation rules.