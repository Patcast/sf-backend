import base64
import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

from app.models import AddressType

# Photos travel inline as base64 data URLs because the database is in-memory —
# there is no file storage to point at.
PHOTO_MAX_BYTES = 1_000_000
_PHOTO_DATA_URL = re.compile(r"^data:image/(png|jpeg|webp|gif);base64,(?P<data>[A-Za-z0-9+/]+={0,2})$")


def _validate_photo(value: str | None) -> str | None:
    if value is None:
        return None
    match = _PHOTO_DATA_URL.match(value)
    if match is None:
        raise ValueError("photo must be a data URL with MIME type image/png, image/jpeg, image/webp, or image/gif")
    data = match.group("data")
    # 4 base64 chars encode 3 bytes — reject oversized payloads before decoding
    # so they never cost a second large allocation. The decoded check stays as
    # defence in depth.
    if len(data) > PHOTO_MAX_BYTES * 4 // 3 + 4:
        raise ValueError(f"photo must decode to at most {PHOTO_MAX_BYTES // 1_000_000} MB")
    try:
        decoded = base64.b64decode(data, validate=True)
    except ValueError as exc:
        raise ValueError("photo contains invalid base64 data") from exc
    if len(decoded) > PHOTO_MAX_BYTES:
        raise ValueError(f"photo must decode to at most {PHOTO_MAX_BYTES // 1_000_000} MB")
    return value


MAX_ADDRESSES = 20

_ADDRESS_EXAMPLE = {
    "type": "home",
    "street": "1 Market St, Suite 400",
    "city": "San Francisco",
    "state": "CA",
    "postal_code": "94105",
    "country": "USA",
}


class AddressBase(BaseModel):
    """One postal address belonging to a contact."""

    type: AddressType = Field(
        default=AddressType.HOME,
        description="What kind of address this is: `home`, `work`, or `other`.",
        examples=["home"],
    )
    street: str = Field(
        min_length=1,
        max_length=300,
        description="Street address, including unit or suite. Required, must not be blank.",
        examples=["1 Market St, Suite 400"],
    )
    city: str | None = Field(default=None, max_length=120, description="City or locality.", examples=["San Francisco"])
    state: str | None = Field(
        default=None,
        max_length=120,
        description="State, province, or region.",
        examples=["CA"],
    )
    postal_code: str | None = Field(
        default=None,
        max_length=20,
        description="Postal or ZIP code.",
        examples=["94105"],
    )
    country: str | None = Field(default=None, max_length=120, description="Country name.", examples=["USA"])

    @field_validator("street")
    @classmethod
    def _street_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("street must not be blank")
        return value


class AddressCreate(AddressBase):
    """An address as sent inside a contact's `addresses` list."""

    model_config = ConfigDict(json_schema_extra={"examples": [_ADDRESS_EXAMPLE]})


class AddressRead(AddressBase):
    """A stored address, as returned inside every contact response."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Server-assigned identifier.", examples=[1])


class ContactBase(BaseModel):
    """Fields shared by every contact request and response."""

    first_name: str = Field(
        min_length=1,
        max_length=100,
        description="Given name. Required, must not be blank.",
        examples=["Ada"],
    )
    last_name: str = Field(
        min_length=1,
        max_length=100,
        description="Family name. Required, must not be blank.",
        examples=["Lovelace"],
    )
    email: EmailStr = Field(
        max_length=320,
        description=(
            "Primary email address. Required and unique across all contacts; "
            "compared case-insensitively and stored lowercased."
        ),
        examples=["ada@example.com"],
    )
    phone: str | None = Field(
        default=None,
        max_length=40,
        description="Phone number. Stored verbatim — any format is accepted.",
        examples=["+1-415-555-0101"],
    )
    company: str | None = Field(
        default=None,
        max_length=200,
        description="Employer or organisation name.",
        examples=["Analytical Engines"],
    )
    job_title: str | None = Field(
        default=None,
        max_length=200,
        description="Role held at the company.",
        examples=["Mathematician"],
    )
    addresses: list[AddressCreate] = Field(
        default_factory=list,
        max_length=MAX_ADDRESSES,
        description=(
            "Postal addresses for the contact, each typed `home`, `work`, or `other`. "
            f"A contact can have up to {MAX_ADDRESSES}."
        ),
        examples=[[_ADDRESS_EXAMPLE]],
    )
    notes: str | None = Field(
        default=None,
        description="Free-form notes about the contact. No length limit.",
        examples=["Met at the SF hackathon."],
    )
    photo: str | None = Field(
        default=None,
        description=(
            "Profile photo as a base64 `data:image/...` URL. Accepted MIME types are "
            "png, jpeg, webp, and gif; the decoded image is capped at 1 MB."
        ),
        examples=["data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="],
    )

    @field_validator("photo")
    @classmethod
    def _photo_is_a_small_image(cls, value: str | None) -> str | None:
        return _validate_photo(value)


_FULL_EXAMPLE = {
    "first_name": "Ada",
    "last_name": "Lovelace",
    "email": "ada@example.com",
    "phone": "+1-415-555-0101",
    "company": "Analytical Engines",
    "job_title": "Mathematician",
    "addresses": [_ADDRESS_EXAMPLE],
    "notes": "Met at the SF hackathon.",
}
_MINIMAL_EXAMPLE = {"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"}


class ContactCreate(ContactBase):
    """Body of `POST /api/v1/contacts`. Only the two names and email are required."""

    model_config = ConfigDict(json_schema_extra={"examples": [_FULL_EXAMPLE, _MINIMAL_EXAMPLE]})


class ContactReplace(ContactBase):
    """
    Body of `PUT /api/v1/contacts/{contact_id}`.

    This is a full replacement: any optional field you omit is set back to `null`.
    Use `PATCH` if you only want to change some fields.
    """

    model_config = ConfigDict(json_schema_extra={"examples": [_FULL_EXAMPLE]})


class ContactUpdate(BaseModel):
    """
    Body of `PATCH /api/v1/contacts/{contact_id}`.

    Every field is optional. Only the fields actually present in the request are
    written; omitted fields keep their current value. Sending an explicit `null`
    clears that field.
    """

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"phone": "+1-415-555-0199", "job_title": "Chief Engineer"}]}
    )

    first_name: str | None = Field(default=None, min_length=1, max_length=100, description="New given name.")
    last_name: str | None = Field(default=None, min_length=1, max_length=100, description="New family name.")
    email: EmailStr | None = Field(
        default=None,
        max_length=320,
        description="New email address. Must not belong to another contact.",
    )
    phone: str | None = Field(default=None, max_length=40, description="New phone number.")
    company: str | None = Field(default=None, max_length=200, description="New company.")
    job_title: str | None = Field(default=None, max_length=200, description="New job title.")
    addresses: list[AddressCreate] | None = Field(
        default=None,
        max_length=MAX_ADDRESSES,
        description="New address list; replaces every existing address. Omit to keep the current ones.",
    )
    notes: str | None = Field(default=None, description="New notes; replaces the existing text.")
    photo: str | None = Field(
        default=None,
        description="New profile photo as a base64 `data:image/...` URL; `null` removes the photo.",
    )

    @field_validator("photo")
    @classmethod
    def _photo_is_a_small_image(cls, value: str | None) -> str | None:
        return _validate_photo(value)


class ContactRead(ContactBase):
    """A stored contact, as returned by every contact endpoint."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    **_FULL_EXAMPLE,
                    "id": 1,
                    "full_name": "Ada Lovelace",
                    "created_at": "2026-08-19T16:22:58.189507Z",
                    "updated_at": "2026-08-19T16:22:58.189511Z",
                }
            ]
        },
    )

    id: int = Field(description="Server-assigned identifier.", examples=[1])
    addresses: list[AddressRead] = Field(
        default_factory=list,
        description="The contact's stored addresses, in insertion order.",
    )
    created_at: datetime = Field(
        description="UTC timestamp of when the contact was created.",
        examples=["2026-08-19T16:22:58.189507Z"],
    )
    updated_at: datetime = Field(
        description="UTC timestamp of the last modification.",
        examples=["2026-08-19T16:22:58.189511Z"],
    )

    @field_validator("created_at", "updated_at")
    @classmethod
    def _as_utc(cls, value: datetime) -> datetime:
        # SQLite discards tzinfo on write; the stored values are UTC, so label
        # them as such rather than emitting an ambiguous naive timestamp.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    @computed_field(description="Convenience concatenation of first and last name.", examples=["Ada Lovelace"])
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class ContactPage(BaseModel):
    """One page of contacts plus the totals a client needs to paginate."""

    items: list[ContactRead] = Field(description="Contacts on this page, ordered by the requested sort.")
    total: int = Field(
        description="Total contacts matching the query, ignoring `limit` and `offset`.",
        examples=[42],
    )
    limit: int = Field(description="Page size that was applied.", examples=[50])
    offset: int = Field(description="Number of records skipped.", examples=[0])


class HealthResponse(BaseModel):
    """Result of the liveness probe."""

    status: str = Field(description="Always `ok` when the service can serve traffic.", examples=["ok"])
    database: str = Field(description="Active SQLAlchemy dialect.", examples=["sqlite"])
    contacts: int = Field(description="Number of contacts currently stored.", examples=[3])


class RootResponse(BaseModel):
    """Discovery document listing the API's entry points."""

    name: str = Field(description="Human-readable service name.", examples=["Contacts API"])
    version: str = Field(description="Service version.", examples=["0.1.0"])
    docs: str = Field(description="Path to the Swagger UI.", examples=["/docs"])
    redoc: str = Field(description="Path to the ReDoc UI.", examples=["/redoc"])
    openapi: str = Field(description="Path to the OpenAPI 3.1 document.", examples=["/openapi.json"])
    contacts: str = Field(description="Base path of the contacts collection.", examples=["/api/v1/contacts"])
    health: str = Field(description="Path to the liveness probe.", examples=["/health"])


class ErrorResponse(BaseModel):
    """Shape of every non-validation error returned by the API."""

    detail: str = Field(
        description="Human-readable explanation of the failure.",
        examples=["Contact 42 not found"],
    )
