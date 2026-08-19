# CardDAV Interface (RFC 6352)

Contract for fetching contacts from CardDAV sources. Implemented directly over `requests` (the `caldav` package is CalDAV-only and was removed; see research.md §8).

## Authentication

- HTTP Basic Auth (`requests` `auth=(user, password)`).
- Supported by Nextcloud and most CardDAV servers.

## Discovery

1. Resolve the address-book home set:
   - Preferred: `GET https://host/.well-known/carddav` (RFC 6764) and follow the returned URL.
   - Fallback: `PROPFIND` on the configured source URL.
2. `PROPFIND` the home set with body requesting `resourcetype`. Collections whose `resourcetype` contains `<addressbook xmlns="urn:ietf:params:xml:ns:carddav"/>` are address books.

## Fetching

Send a `REPORT` to an address-book collection URL with an `addressbook-query` (or `sync-collection`) request body asking for `address-data`. Response bodies are `text/vcard` (vCard 3.0/4.0).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<card:addressbook-query xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">
  <d:prop><d:getetag/><card:address-data/></d:prop>
  <card:filter><card:prop-filter name="FN"/></card:filter>
</card:addressbook-query>
```

## Parsing

Each returned vCard is parsed with `vobject` into the intermediate model:

| vCard property | Model field | Notes |
|---|---|---|
| `FN` / `N` | `Contact.name` | `N` fallback if `FN` absent |
| `TEL` | `PhoneNumber` (`type`, `prio`) | First TEL defaults to `prio=1` |
| `EMAIL` | `EmailAddress` (`classifier`) | `home`→`private`, `work`→`work` |
| `PHOTO` | `Contact.picture_data` / `picture_url` | Base64 inline or URI |
| `CATEGORIES` | `Contact.is_vip` | `VIP`/`important` → True |
| `UID` | `Contact.unique_id` | Numeric value extracted if present |

## Error Handling

- Per-source failure must not abort the run: log to stderr and continue with the remaining sources (FR-009).
- Unparseable vCards are logged and skipped without failing the run.