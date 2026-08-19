# Research: CardDAV to FritzBox Sync Utility

## 1. Executive Summary & Research Task Status

| Area | Task | Status | Decision / Findings |
|---|---|---|---|
| FritzBox Authentication | T004 | **Completed** | `login_sid.lua` Challenge-Response (MD5 / PBKDF2 UTF-16LE) returning 16-character `sid`. |
| FritzBox HTTP API | T004 | **Completed** | Multipart POST to `/cgi-bin/firmwarecfg` for full phonebook overwrite / mirror sync. |
| FritzBox TR-064 API | T004 | **Completed** | SOAP `X_AVM-DE_OnTel:1` (Digest auth): `GetPhonebookList`, `GetPhonebook`, `AddPhonebook`, `DeletePhonebook`; resolves/creates the `target_book` by name (main book 0 can't be renamed). |
| FritzBox XML Schema | T004 | **Completed** | Hierarchy: `<phonebooks><phonebook><contact><person><realName>...</realName></person><telephony>...</telephony><services><email>...</email></services></contact></phonebook></phonebooks>`. |
| CardDAV API | T001-T003 | **Completed** | **Use `requests` + `vobject`.** The `caldav` library is CalDAV-only (no `AddressBook`/`AddressObject` support) and was removed. RFC 6352 PROPFIND/REPORT implemented directly over `requests`. |
| Supported Fields | T005 | **Completed** | Mapped vCard fields (FN/N, TEL types, EMAIL classifiers, PHOTO, VIP) to FritzBox XML. |
| Image Conversion | T006 | **Completed** | Pipeline: Base64/PNG decode -> Pillow RGB conversion -> Baseline JPEG 300x300. |
| Data Representation | T007 | **Completed** | Python dataclasses (`Contact`, `PhoneNumber`, `EmailAddress`) in `src/models/contact.py`. |
| Tech Stack Assessment | T008 | **Completed** | Verified all dependencies against the constitution. Stack is sufficient with two adaptations: drop `caldav`, add `isort`. |

---

## 2. FritzBox Authentication Protocol Details (`login_sid.lua`)

FRITZ!OS uses a Challenge-Response authentication mechanism over HTTP/HTTPS via `http://<fritz.box>/login_sid.lua`.

### 2.1 Authentication Flow
1. **Initial Challenge Request**: `GET http://<fritz.box>/login_sid.lua`
   - Returns XML containing `<SessionInfo><Challenge>314159265</Challenge><SID>0000000000000000</SID></SessionInfo>`.
2. **Challenge-Response Calculation**:
   - MD5 (Standard/Legacy): `MD5(Challenge + "-" + Password)` encoded as UTF-16LE.
   - Response string format: `<Challenge>-<md5_hex_hash>`
   - PBKDF2 (FRITZ!OS 7.24+ when challenge starts with `2$`): PBKDF2-HMAC-SHA256 iteration.
3. **Login Verification**: `GET http://<fritz.box>/login_sid.lua?username=<user>&response=<challenge_response>`
   - Returns XML with a valid `<SID>1234567890abcdef</SID>`.
4. **Session Maintenance**: The `sid` parameter must be included in all subsequent HTTP requests (`sid=<sid>`).

### 2.2 Python Reference Implementation
```python
import hashlib
import xml.etree.ElementTree as ET
import requests

def get_fritzbox_sid(host: str, username: str, password: str) -> str:
    url = f"http://{host}/login_sid.lua"
    resp = requests.get(url)
    tree = ET.fromstring(resp.content)
    challenge = tree.findtext("Challenge")
    sid = tree.findtext("SID")

    if sid != "0000000000000000":
        return sid  # Already authenticated session

    # MD5 Challenge Response Calculation (UTF-16LE)
    hash_input = f"{challenge}-{password}".encode("utf-16le")
    md5_hash = hashlib.md5(hash_input).hexdigest()
    response_str = f"{challenge}-{md5_hash}"

    # Submit response
    login_resp = requests.get(url, params={"username": username, "response": response_str})
    login_tree = ET.fromstring(login_resp.content)
    new_sid = login_tree.findtext("SID")

    if new_sid == "0000000000000000":
        raise PermissionError("FritzBox authentication failed. Check credentials.")

    return new_sid
```

---

## 3. FritzBox Address Book Upload Endpoints & Methods

For mirroring contacts (overwriting a target address book cleanly), FRITZ!OS provides an HTTP POST CGI endpoint.

### 3.1 Endpoint Specification
- **URL**: `http://<fritz.box>/cgi-bin/firmwarecfg`
- **HTTP Method**: `POST`
- **Content-Type**: `multipart/form-data`

### 3.2 Form Parameters
- `sid`: The valid 16-character Session ID.
- `PhonebookId`: Numeric ID of the target address book (e.g., `0` for default, `1`, `2` for secondary address books).
- `PhonebookImportFile`: The raw XML string or file upload payload containing the `<phonebooks>` structure (filename `updatepb.xml`, content type `text/xml`).

> **Verified against real hardware (FRITZ!OS 7.x, Aug 2026):** a `PhonebookImportName`
> form field is rejected with `Invalid variable name.` and must be omitted. The phonebook
> name comes from the uploaded `<phonebook name="...">` element. The response is an HTML
> page in the UI language (German/Dutch/English success phrases such as
> "Das Telefonbuch der FRITZ!Box wurde wiederhergestellt." / "is hersteld."), **not XML**;
> success is detected via text markers.

### 3.3 Mirror Sync Overwrite Behavior
When `PhonebookImportFile` is POSTed to `/cgi-bin/firmwarecfg` for a specific `PhonebookId`:
- The FritzBox completely replaces all contacts within that specified `PhonebookId`.
- Contacts existing on the FritzBox that are omitted from the uploaded XML are automatically removed (pruned).
- This perfectly matches **FR-011** and **FR-012** (mirror sync/overwrite requirement) in a single atomic operation without needing individual contact deletion API calls.

### 3.4 TR-064 Phonebook Management (`X_AVM-DE_OnTel:1`)

> **Verified against real hardware (FRITZ!Box 7581, FRITZ!OS 07.18, Aug 2026).**
> Used to honor the configured `target_book` name, because the **main phonebook
> (id 0) can be neither renamed nor deleted** (AVM documentation); the firmwarecfg
> import keeps its name ("Telefoonboek") no matter what the uploaded XML says.

Service discovery: `GET http://<fritz.box>:49000/tr64desc.xml`; the OnTel control
URL is `/upnp/control/x_contact`. Authentication is **HTTP Digest auth** with the
regular FRITZ!Box credentials (Basic auth is rejected with 401; the
`X_AVM-DE_Auth:1` `SetConfig` flow is not required on this firmware).

Actions used (`src/services/tr064.py`):

| Action | Arguments | Return |
|---|---|---|
| `GetPhonebookList` | – | `NewPhonebookList`: comma-separated **indexes** |
| `GetPhonebook` | `NewPhonebookID` (index) | `NewPhonebookName`, `NewPhonebookExtraID`, `NewPhonebookURL` (carries the **real** id as `pbid=<id>`) |
| `AddPhonebook` | `NewPhonebookExtraID` (""), `NewPhonebookName` | creates a book; error **820** when the name already exists |
| `DeletePhonebook` | `NewPhonebookID` (index), `NewPhonebookExtraID` ("" ) | deletes the book at the given **index** |

Key semantics (empirically confirmed):
- `GetPhonebookList` returns **indexes** `0,1,2,...`; the *real* book id is the
  `pbid` in `NewPhonebookURL` (real ids can be sparse, e.g. `0,1,2,40,41`).
- The firmwarecfg `PhonebookId` form field expects the **real** id, not the index.
- `DeletePhonebook` takes the **index**, not the real id (passing a real id that
  is not a valid index returns UPnP error 402).
- Importing into a **secondary** (non-0) book **creates** the book when it does
  not exist and applies the XML `<phonebook name="...">`; re-importing renames an
  existing secondary book to the XML name.
- The **main book (0) is exempt**: it is never renamed by an import.

This enables resolving `target_book` by name: enumerate `GetPhonebookList` →
`GetPhonebook` per index; on a name match use the real id for the firmwarecfg
import; when absent, `AddPhonebook(target_book)` then re-enumerate. When TR-064
is unreachable (port 49000 closed) the uploader falls back to the main book (0)
with a warning.

---

## 4. FritzBox Phonebook XML Schema Specifications

### 4.1 Complete XML Document Structure
```xml
<?xml version="1.0" encoding="utf-8"?>
<phonebooks>
  <phonebook name="CardDAV Sync" owner="0">
    <contact>
      <category>0</category>
      <person>
        <realName>John Doe</realName>
        <imageURL></imageURL>
      </person>
      <telephony nid="2">
        <number type="home" prio="1" id="0" quickdial="" vanity="">0301234567</number>
        <number type="mobile" prio="0" id="1" quickdial="" vanity="">+491701234567</number>
      </telephony>
      <services>
        <email classifier="private" id="0">john.doe@example.com</email>
        <email classifier="work" id="1">j.doe@company.com</email>
      </services>
      <setup />
      <features doorphone="0" />
      <mod_time>1723460000</mod_time>
      <uniqueid>1</uniqueid>
    </contact>
  </phonebook>
</phonebooks>
```

### 4.2 XML Element Field Specifications

| Tag Path | Allowed Values / Format | Description / Notes |
|---|---|---|
| `<phonebooks>` | Root element | Must wrap all phonebook definitions. |
| `<phonebook>` | `name="..." owner="0"` | Represents an address book instance. `name` matches target name. |
| `<contact>` | Child of `<phonebook>` | Container for one contact entry. |
| `<category>` | `0` (Standard), `1` (VIP) | Category classification. Default to `0`. |
| `<person>/<realName>` | String (UTF-8) | Display name of contact. Required. |
| `<person>/<imageURL>` | String / HTTP URL | URL or local path to contact avatar. Optional. |
| `<telephony>` | Attr: `nid="<count>"` | Container for phone numbers. `nid` is number of child `<number>` tags. |
| `<telephony>/<number>` | Attrs: `type`, `prio`, `id`, `quickdial`, `vanity` | `type` can be `home`, `mobile`, `work`, `fax`. `prio` is `1` (primary) or `0`. |
| `<services>/<email>` | Attrs: `classifier`, `id` | `classifier` can be `private` or `work`. `id` is 0-indexed. |
| `<uniqueid>` | Integer | Unique identifier per contact within the phonebook. |

---

## 5. Architectural Decision: HTTP POST (`firmwarecfg`) vs. TR-064 SOAP

| Feature / Criteria | HTTP POST (`/cgi-bin/firmwarecfg`) | TR-064 SOAP (`X_AVM-DE_OnTel:1`) |
|---|---|---|
| **Full Phonebook Overwrite** | Native (Single POST request replaces target book) | Requires downloading XML, modifying, or using `AddPhonebookEntry` |
| **Authentication** | `login_sid.lua` (SID parameter) | HTTP Digest Auth / TR-064 credentials |
| **Mirror Sync Complexity** | Low (Generate full XML -> Upload) | Medium/High (Manual Diff & Deletion loops required) |
| **Performance** | High (< 2 seconds for 100 contacts) | Medium (Multiple SOAP roundtrips for diff sync) |
| **Decision** | **SELECTED FOR IMPLEMENTATION** | Secondary / Fallback |

---

## 6. Supported Address Book Fields & Mapping Matrix (T005)

### 6.1 CardDAV vCard to FritzBox XML Mapping Table

| vCard (CardDAV) Field | FritzBox XML Target | Supported Values / Format | Handling / Conversion Notes |
|---|---|---|---|
| `FN` (Formatted Name) or `N` | `<person>/<realName>` | UTF-8 String (Max ~60 chars) | Formatted based on `name_order` config (`first_name_first`: "First Last" vs `last_name_first`: "Last, First"). |
| `TEL;TYPE=home`, `VOICE` | `<telephony>/<number type="home">` | Normalized phone string | Map to `type="home"`. Set `prio="1"` for primary number. |
| `TEL;TYPE=cell`, `mobile` | `<telephony>/<number type="mobile">` | Normalized phone string | Map to `type="mobile"`. |
| `TEL;TYPE=work` | `<telephony>/<number type="work">` | Normalized phone string | Map to `type="work"`. |
| `TEL;TYPE=fax` | `<telephony>/<number type="fax">` | Normalized phone string | Map to `type="fax"`. |
| `EMAIL;TYPE=home`, `internet` | `<services>/<email classifier="private">` | Email address string | Map to `classifier="private"`, assign `id="0"`, `id="1"`, etc. |
| `EMAIL;TYPE=work` | `<services>/<email classifier="work">` | Email address string | Map to `classifier="work"`. |
| `PHOTO` | `<person>/<imageURL>` | File path / URL | Converted JPG image path or HTTP URL (see T006). |
| `CATEGORIES` | `<category>` | `0` (Standard) or `1` (VIP) | Set to `1` if `CATEGORIES` contains `"VIP"`, otherwise `0`. |

### 6.2 FritzBox Field Capacity & Constraints
- **Max Numbers per Contact**: FritzBox supports up to **9 phone numbers** (`id="0"` through `id="8"`). Excess numbers are omitted with a log warning.
- **Max Email Addresses per Contact**: FritzBox supports up to **2 email addresses** (`classifier="private"` and `classifier="work"`).
- **Primary Number (`prio="1"`)**: Exactly one `<number>` tag per contact should have `prio="1"`. The first encountered phone number defaults to `prio="1"`.

### 6.3 Unsupported vCard Fields Handling Policy
The following standard vCard fields are **not supported** by the FritzBox phonebook XML schema:
- `ADR` (Postal Addresses)
- `BDAY` (Birthdays)
- `ORG` (Company / Organization)
- `TITLE` (Job Title)
- `NOTE` (Freeform Notes)
- `URL` (Websites)
- `IMPP` (Instant Messaging)

**Handling Policy**: These properties are intentionally stripped during normalization/conversion into the intermediate model. Omitting them ensures clean XML syntax and prevents FritzBox import parsing errors.

---

## 7. vCard Image Processing & FritzBox Conversion Pipeline (T006)

### 7.1 CardDAV vCard `PHOTO` Formats
CardDAV vCards deliver contact images in two primary formats:
1. **Inline Base64 Data**: `PHOTO;ENCODING=b;TYPE=JPEG:...` or `PHOTO;ENCODING=BASE64;TYPE=PNG:...`
2. **External URI**: `PHOTO;VALUE=uri:http://example.com/avatar.png`

### 7.2 FritzBox Contact Image Specifications
- **Container Format**: **JPEG / JPG** (Baseline encoding strictly required; progressive JPEGs or PNGs are rejected by FRITZ!Fon firmware).
- **Aspect Ratio**: **1:1** (Square aspect ratio recommended for DECT handset caller displays).
- **Target Dimensions**: Max **300x300 pixels** (or 240x320).
- **Phonebook Capacity**: FritzBox hardware allows up to 150–256 contact pictures per phonebook.

### 7.3 Python Image Conversion Pipeline
```python
import base64
import io
from PIL import Image

def convert_vcard_photo_to_jpg(photo_data: str, is_base64: bool = True) -> bytes:
    """
    Decodes vCard PHOTO data, crops to square, resizes to 300x300, and encodes to baseline JPEG.
    """
    if is_base64:
        image_bytes = base64.b64decode(photo_data)
    else:
        image_bytes = photo_data  # Raw binary bytes

    # Open image with Pillow
    img = Image.open(io.BytesIO(image_bytes))

    # Convert to RGB (strips alpha transparent channels from PNG/GIF)
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    # Center-crop to 1:1 square
    width, height = img.size
    min_dim = min(width, height)
    left = (width - min_dim) / 2
    top = (height - min_dim) / 2
    right = (width + min_dim) / 2
    bottom = (height + min_dim) / 2
    img = img.crop((left, top, right, bottom))

    # Resize to 300x300 max
    img = img.resize((300, 300), Image.Resampling.LANCZOS)

    # Save as baseline JPEG
    output = io.BytesIO()
    img.save(output, format="JPEG", quality=85, progressive=False)
    return output.getvalue()
```

### 7.4 Fallback Strategy & Exception Handling
- **Missing or Corrupted Images**: If `PHOTO` parsing, Base64 decoding, or `Pillow` processing encounters an error, log a warning to `stderr` and omit `<imageURL>` (leave as empty string `<imageURL></imageURL>`).
- **Graceful Failure**: Non-interactive execution must never fail due to an invalid avatar image format.

---

## 8. Tech Stack Assessment & CardDAV Fetching Decision (T008)

### 8.1 Assessment Result
The current stack is **sufficient with two adaptations**. Full inventory of what is already in the project venv (Python 3.13):

| Component | Tool | Verdict | Justification |
|---|---|---|---|
| Language | Python 3.13 | **Keep** | Modern syntax, stdlib-first, matches constitution VI. |
| HTTP client | `requests` | **Keep** | Minimal, battle-tested; used by both CardDAV fetch and FritzBox upload. |
| vCard parsing | `vobject` | **Keep** | Handles RFC 6350 parsing; avoids hand-rolling fragile line-fold parsing. |
| CardDAV protocol | `caldav` | **REMOVE** | Verified in installed 3.2.1: API exposes `Calendar`/`Event`/`Todo` only. There is no `AddressBook`/`AddressObject`/`addressbook-home-set` support (RFC 6352). It is a CalDAV library, not a CardDAV one. |
| Image conversion | `Pillow` | **Keep** | Required for baseline-JPEG + 300x300 resizing; stdlib cannot encode JPEG. |
| Config parsing | stdlib `configparser` | **Keep** | Constitution I/III; INI format already established. |
| XML | stdlib `xml.etree.ElementTree` + `minidom` | **Keep** | FritzBox XML schema is simple; stdlib suffices. |
| Logging | stdlib `logging` | **Keep** | stderr-based, cron-friendly. |
| Testing | `pytest` + `flake8` + `black` | **Keep** | Already configured in `pyproject.toml`; `isort` added for consistency with its config block. |

### 8.2 Decision: Replace `caldav` with direct `requests` + `vobject`

- **Decision**: Fetch CardDAV address books directly over RFC 6352 using `requests` (Basic Auth) and parse the returned vCards with `vobject`. Remove the `caldav` dependency.
- **Rationale**:
  - `caldav` does not implement CardDAV address-book resources; relying on it would require undocumented internal APIs (constitution IV violation).
  - The CardDAV protocol surface needed is small and stable: `PROPFIND` for discovery (`addressbook-home-set`, `resourcetype` = `addressbook`) plus one `REPORT` (`addressbook-query` or `sync-collection`) returning `text/vcard`. This is exactly "Public APIs Only" (RFC 6352 is an open IETF standard).
  - Removing a non-functional dependency is the minimal-dependency outcome (constitution III).
- **Alternatives considered**:
  - `caldav` library: rejected — CalDAV-only, no RFC 6352 support.
  - Dedicated CardDAV packages (e.g., `vcards`, `pycarddav`): rejected — unmaintained or thin wrappers over `requests` with extra API surface for no benefit.
  - Hand-rolled vCard parsing with `requests` only: rejected — `vobject` already provides correct, tested RFC 6350 parsing.

### 8.3 CardDAV Fetch Flow (reference implementation pattern)
```python
import requests
from vobject import vCard

def discover_addressbooks(base_url: str, user: str, password: str) -> list[str]:
    # 1. Resolve home set: GET /.well-known/carddav (RFC 6764) or PROPFIND on base
    # 2. PROPFIND home set for resourcetype: addressbook
    # 3. Return list of addressbook collection hrefs

def fetch_vcards(addrbook_url: str, user: str, password: str) -> list[vCard]:
    # REPORT with <addressbook-query> / <sync-collection>, body asks for address-data
    # Parse each vCard 3.0/4.0 response body with vobject
```

Notes: Nextcloud exposes CardDAV under `/remote.php/dav/addressbooks/users/<user>/` and supports Basic Auth; `requests` handles auth, redirects, and TLS automatically (FritzBox uses plain HTTP on the LAN, so no cert handling is needed there).

### 8.4 Configuration Schema Adaptation
The clarified spec (Session 2026-08-19) requires `country_code` and `area_code` to be mandatory and adds the international access code. Config changes:
- Rename `region_code` → `area_code` (no hardcoded `+49`/`30` defaults; validation must fail if missing — FR-017).
- Add `international_access_code` (e.g., `00` Europe, `09` US) used during normalization (FR-005 step 3).
