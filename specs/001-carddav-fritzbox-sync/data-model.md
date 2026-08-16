# Data Model: CardDAV to FritzBox

## Contact & Sub-Entities (Intermediate Representation)

```python
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class PhoneNumber:
    number: str           # Cleaned / normalized telephone number string
    type: str = "home"    # "home", "mobile", "work", "fax"
    prio: int = 0         # 1 for primary number, 0 for secondary numbers
    quickdial: str = ""   # 2-digit quickdial string (e.g. "01")
    vanity: str = ""      # Vanity string

@dataclass
class EmailAddress:
    email: str
    classifier: str = "private"  # "private" or "work"

@dataclass
class Contact:
    # Identity & Display
    name: str
    
    # Contact Details
    phone_numbers: List[PhoneNumber] = field(default_factory=list)
    emails: List[EmailAddress] = field(default_factory=list)
    
    # Single-occurrence fields (from highest priority source)
    picture_data: Optional[bytes] = None
    picture_url: Optional[str] = None
    is_vip: bool = False
    unique_id: Optional[int] = None
```

## Mapping & Validation Rules

- **Identity**: `(name, normalized_phone_or_email)` uniquely identifies a contact for merging.
- **Name Formatting**:
  - Structured vCard `N` property (`FamilyName;GivenName;...`) and `FN` are parsed.
  - Reconstructed according to `Config.name_order`:
    - `first_name_first` (Default): `"GivenName FamilyName"` (e.g. *"John Doe"*)
    - `last_name_first`: `"FamilyName, GivenName"` (e.g. *"Doe, John"*)
- **Normalization**: Strip non-numeric chars from phones, add country/region codes if international.
- **Merge**:
  - Name: Taken from first source (canonical).
  - Multi-fields (phones, emails): Appended.
  - Single-fields (picture, address): Taken from highest-priority source.
- **FritzBox Export**:
  - Write formatted name string to `<person>/<realName>`.
  - Convert `picture_base64` to binary (JPG).
  - Construct XML according to FritzBox API spec.

