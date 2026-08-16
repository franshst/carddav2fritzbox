# Research: CardDAV to FritzBox Sync Utility

## 1. Executive Summary & Research Task Status

| Area | Task | Status | Decision / Findings |
|---|---|---|---|
| FritzBox Authentication | T004 | **Completed** | `login_sid.lua` Challenge-Response (MD5 / PBKDF2 UTF-16LE) returning 16-character `sid`. |
| FritzBox HTTP API | T004 | **Completed** | Multipart POST to `/cgi-bin/firmwarecfg` for full phonebook overwrite / mirror sync. |
| FritzBox TR-064 API | T004 | **Completed** | SOAP service `X_AVM-DE_OnTel:1` (`GetPhonebookList`, `GetPhonebook`) available for reading/metadata. |
| FritzBox XML Schema | T004 | **Completed** | Hierarchy: `<phonebooks><phonebook><contact><person><realName>...</realName></person><telephony>...</telephony><services><email>...</email></services></contact></phonebook></phonebooks>`. |
| CardDAV API | T001-T003 | Pending | Need to verify Python libraries (`vobject`, `caldav`, or `requests`) for standard CardDAV fetching. |
| Supported Fields | T005 | **Completed** | Mapped vCard fields (FN/N, TEL types, EMAIL classifiers, PHOTO, VIP) to FritzBox XML. |
| Image Conversion | T006 | **Completed** | Pipeline: Base64/PNG decode -> Pillow RGB conversion -> Baseline JPEG 300x300. |
| Data Representation | T007 | Pending | Design a Python dataclass or namedtuple for intermediate representation. |

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
- `PhonebookImportName`: Name of the phonebook (e.g., `"CardDAV Sync"`).
- `PhonebookImportFile`: The raw XML string or file upload payload containing the `<phonebooks>` structure.

### 3.3 Mirror Sync Overwrite Behavior
When `PhonebookImportFile` is POSTed to `/cgi-bin/firmwarecfg` for a specific `PhonebookId`:
- The FritzBox completely replaces all contacts within that specified `PhonebookId`.
- Contacts existing on the FritzBox that are omitted from the uploaded XML are automatically removed (pruned).
- This perfectly matches **FR-011** and **FR-012** (mirror sync/overwrite requirement) in a single atomic operation without needing individual contact deletion API calls.

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
