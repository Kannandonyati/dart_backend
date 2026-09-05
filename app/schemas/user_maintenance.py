"""Invite / password-reset request-response shapes.

Password rules mirror `UserCreate`'s (app/schemas/user.py) — duplicated
rather than imported, since the two schemas' fields don't otherwise
overlap enough to share a base class without adding indirection for a
four-line validator.
"""

from pydantic import BaseModel, EmailStr, Field, field_validator


def _validate_password_strength(v: str) -> str:
    if v.isdigit() or v.isalpha():
        raise ValueError("Password must contain a mix of letters and digits/symbols.")
    return v


class UserInviteCreate(BaseModel):
    email: EmailStr
    # Optional — the reference frontend's invite form only ever collects an
    # email (matches the old backend's own `user_invite` view, which derives
    # `username = email.split('@')[0]` itself). Omit it and the endpoint
    # derives the same way; supply it to override.
    username: str | None = Field(
        default=None, min_length=3, max_length=150, pattern=r"^[a-zA-Z0-9_.-]+$"
    )
    # Regenerates a fresh token for an existing, still-pending invite
    # instead of creating a new account — matches the reference frontend's
    # "Resend invite" action (`invite_type: 'reinvite'`). Only valid
    # against a row that hasn't redeemed its invite yet; see invite_user's
    # docstring in the endpoint for the exact rules.
    resend: bool = False

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.lower()


class UserInviteRead(BaseModel):
    user_id: str
    email: str
    username: str
    invite_token: str


class InviteAccept(BaseModel):
    invite_token: str
    password: str = Field(min_length=12, max_length=128)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class PasswordResetTokenRead(BaseModel):
    user_id: str
    reset_token: str


class PasswordResetSubmit(BaseModel):
    reset_token: str
    new_password: str = Field(min_length=12, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)
