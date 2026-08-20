# FritzBox Phonebook Import Interface

Contract for authenticating and uploading contacts to a FritzBox device. Details in research.md §2–§4.

## Authentication (`login_sid.lua`)

1. `GET http://<host>/login_sid.lua` → XML with `<Challenge>` and `<SID>`.
2. If `<SID>` is non-zero, reuse it.
3. Else compute `response = challenge + "-" + md5_utf16le(challenge + "-" + password)` and
   `GET /login_sid.lua?username=<user>&response=<response>`.
4. Use the returned `<SID>` as `sid` in the upload request.

Support the legacy MD5 scheme and the PBKDF2 scheme (FRITZ!OS 7.24+, challenge prefix `2$`).

## Upload (`/cgi-bin/firmwarecfg`)

`POST http://<host>/cgi-bin/firmwarecfg` with `multipart/form-data` fields:

| Field | Value |
|---|---|
| `sid` | session id from login (must be the first field) |
| `PhonebookId` | `0` (default) or configured id |
| `PhonebookImportFile` | `updatepb.xml`, content type `text/xml` |

Verified against real hardware (FRITZ!OS 7.x, Aug 2026): a `PhonebookImportName`
form field is **rejected** with `Invalid variable name.` and must be omitted.
The phonebook name in the uploaded `<phonebook name="...">` element is used.

This **replaces the entire target phonebook** (mirror sync, FR-011/FR-012); omitted contacts are pruned. The response is an HTML page in the UI language, **not XML** — success is detected by text markers:

- German: `Das Telefonbuch der FRITZ!Box wurde wiederhergestellt.`
- Dutch: `Het telefoonboek van de FRITZ!Box is hersteld.`
- English: `FRITZ!Box telephone book restored.`

Error responses carry markers such as `Invalid variable name.` / `mislukt` / `failed`; any unrecognized body is treated as failure (logged).

## Phonebook resolution (TR-064 `X_AVM-DE_OnTel:1`)

`POST http://<host>:49000/upnp/control/x_contact` with SOAP + **HTTP Digest auth**
(credentials identical to the web UI; Basic auth is rejected). The firmwarecfg
`PhonebookId` field expects the **real** book id (`pbid` from `NewPhonebookURL`).
The main phonebook (0) can be neither renamed nor deleted; secondary books adopt
the uploaded XML `<phonebook name="...">` on import. See research.md §3.4.

| Action | In args | Purpose |
|---|---|---|
| `GetPhonebookList` | – | comma-separated book **indexes** |
| `GetPhonebook` | `NewPhonebookID` (index) | name + URL with real id `pbid=` |
| `AddPhonebook` | `NewPhonebookExtraID` (""), `NewPhonebookName` | create book (error 820 if name exists) |
| `DeletePhonebook` | `NewPhonebookID` (index), `NewPhonebookExtraID` ("") | delete book at index |

Resolution flow: enumerate indexes → read names → pick the book named
`target_book` (create it via `AddPhonebook` when missing) → upload into its real id.
If TR-064 is unreachable, fall back to the main book (0) with a warning.

## Phonebook XML Schema

```xml
<phonebooks>
  <phonebook name="CardDAV Sync" owner="0">
    <contact>
      <category>0|1</category>
      <person>
        <realName>John Doe</realName>
        <imageURL>file:///var/InternerSpeicher/FRITZ/fonpix/5_1700000000.jpg</imageURL>
      </person>
      <telephony nid="2">
        <number type="home" prio="1" id="0" quickdial="" vanity="">0301234567</number>
        <number type="mobile" prio="0" id="1" quickdial="" vanity="">+491701234567</number>
      </telephony>
      <services>
        <email classifier="private" id="0">john@example.com</email>
      </services>
      <setup/>
      <features doorphone="0"/>
      <mod_time>1723460000</mod_time>
      <uniqueid>1</uniqueid>
    </contact>
  </phonebook>
</phonebooks>
```

### Constraints

- Max 9 phone numbers per contact (`id` 0–8); excess dropped with a warning.
- Max 2 email addresses per contact (`private`, `work`).
- Exactly one `prio="1"` number per contact.
- Image must be baseline JPEG ≤300×300 (see data-model.md / research.md §7).

## Contact Pictures (`<imageURL>`)

The `<imageURL>` element is a **reference to a picture file stored on the box's
own storage** (internal or USB), not embedded image data. AVM's own phonebook
exports use e.g. `file:///var/InternerSpeicher/FRITZ/fonpix/1564409969-0.jpg`
and pictures are not carried in the phonebook backup/restore XML.

Sync therefore delivers pictures out-of-band over FTP (the mechanism of the
reference tool andig/carddav2fb):

| Aspect | Value |
|---|---|
| Transport | plain FTP (`ftp_plain = true`, default) or explicit FTPS (`FTP_TLS` + `PROT P`) |
| Host/credentials | `fritzbox.ftp_host`/`ftp_user`/`ftp_pass`, defaulting to the box host and web-UI credentials |
| Target dir | `fritzbox.fonpix_dir` (e.g. `/FRITZ/fonpix` on internal storage or the path on a USB stick) |
| URL prefix | `fritzbox.imagepath`, e.g. `file:///var/InternerSpeicher/FRITZ/fonpix` |
| Filename | `<key>_<epoch>.jpg` where the key is the vCard UID (or a stable identity digest) |
| Reuse | a managed file whose size matches the current picture is kept (no re-upload) |
| Cleanup | stale files per key and orphaned managed files are deleted; the underscore separator keeps files created by the box (`<timestamp>-<n>.jpg`) untouched |

**Pre-flight check (FR-021)**: before anything is uploaded, the FTP picture
directory is verified to exist (created when possible). When it is
unavailable, the sync aborts with a clear error and a non-zero exit code;
neither pictures nor the phonebook are uploaded, so the existing phonebook
stays intact.

Inline pictures are only synced when both `fonpix_dir` and `imagepath` are
configured; otherwise they are skipped with a warning (embedded data URIs are
not resolved by the box). External HTTP(S) photo URIs are written as-is.