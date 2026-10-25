"""Independent synthetic identity cases builders; never sample answers."""

from ghost_audit.domain.models import Identity, IdentityChange

T1 = "2026-01-01T00:00:00Z"


T2 = "2026-01-02T00:00:00Z"


T3 = "2026-01-03T00:00:00Z"


T4 = "2026-01-04T00:00:00Z"


def snapshot(user="user_one", email="new@example.invalid", at=T3, **kwargs):
    return Identity(
        user_id=user,
        name="Fictional Person",
        email=email,
        phone=kwargs.get("phone", "+1 (202) 555-0100"),
        email_hash=kwargs.get("email_hash", "HASH_SUPPLIED"),
        updated_at=at,
    )


def change(audit, old, new, field="email", at=T2, user="user_one"):
    return IdentityChange(
        audit_id=audit, user_id=user, event_time=at, field_name=field, old_value=old, new_value=new
    )
