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
| `sid` | session id from login |
| `PhonebookId` | `0` (default) or configured id |
| `PhonebookImportName` | target phonebook name |
| `PhonebookImportFile` | `phonebook.xml`, content type `text/xml` |

This **replaces the entire target phonebook** (mirror sync, FR-011/FR-012); omitted contacts are pruned. Success is indicated by `<success>1</success>` in the response.

## Phonebook XML Schema

```xml
<phonebooks>
  <phonebook name="CardDAV Sync" owner="0">
    <contact>
      <category>0|1</category>
      <person>
        <realName>John Doe</realName>
        <imageURL>...</imageURL>
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