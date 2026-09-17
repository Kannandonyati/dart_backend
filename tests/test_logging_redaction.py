from app.core.logging import _REDACTED, _redact_sensitive


def test_redacts_email_and_token_shaped_keys() -> None:
    out = dict(
        _redact_sensitive(
            None,
            "info",
            {
                "email": "a@dart.com",
                "invite_token": "abc",
                "hashed_password": "argon2...",
                "recon_id": "keep-me",
            },
        )
    )
    assert out["email"] == _REDACTED
    assert out["invite_token"] == _REDACTED
    assert out["hashed_password"] == _REDACTED
    assert out["recon_id"] == "keep-me"
