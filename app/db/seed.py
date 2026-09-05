"""Idempotent bootstrap seed: creates the baseline Privilege/Role catalog
and the initial break-glass admin user, if they don't already exist.

Run once per environment:

    uv run python -m app.db.seed

Requires BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD to be set in
the environment — deliberately not defaulted anywhere, so a real
password is never silently generated, guessed, or checked into a repo.
Safe to re-run: every write here is an existence check first.
"""

import asyncio
import sys
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.core.usernames import derive_unique_username
from app.db.session import session_scope
from app.models.security import Privilege, Role
from app.models.user import User

configure_logging()
logger = structlog.get_logger(__name__)

# Each phase seeds the privileges its own endpoints actually check. Add
# the name here and to the role mapping below, then re-run (idempotent).
#
# The ten `*_recon` names are the old backend's real, closed privilege
# catalog (confirmed against the reference frontend's
# src/features/recon-security/data.ts, which hardcodes exactly this
# list for its role-creation multi-select — not admin-definable free
# text). `user:manage`/`recon:manage_all`/`security:manage` are this
# rebuild's own coarse, endpoint-level gates (Phase 1/2/3 respectively)
# and deliberately coexist with the old catalog rather than replace it:
# the *_recon names exist so Role CRUD (Phase 3) has real values to
# assign, they are not yet wired into any require_privilege() check —
# see KT_PHASE3.md's "Known gaps."
_RECON_PRIVILEGE_CATALOG = [
    "create_recon",
    "read_recon",
    "update_recon",
    "delete_recon",
    "execute_recon",
    "sign_off_recon",
    "import_recon",
    "export_recon",
    "replicate_recon",
    "archive_recon",
    "create_global_variable",
    "read_global_variable",
    "assign_global_variable",
    "update_global_variable",
    "delete_global_variable",
    "import_global_variable",
    "export_global_variable",
    "replicate_global_variable",
    "archive_global_variable",
]
_BASELINE_PRIVILEGES = [
    "user:manage",  # Phase 1
    "recon:manage_all",  # Phase 2 — act on a recon you don't own
    "security:manage",  # Phase 3 — LOB/Team/Group/Role CRUD and linking
    *_RECON_PRIVILEGE_CATALOG,
]
_BASELINE_ROLES: dict[str, list[str]] = {
    "Account Admin": _BASELINE_PRIVILEGES,
    # Label-only role (see Membership's docstring, app/models/security.py):
    # a membership row with this role attached means "admin of this
    # scope," independent of security:manage's actual authorization gate.
    "Admin": [],
}


async def seed() -> None:
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        logger.error(
            "seed_failed",
            reason="BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD must both be set",
        )
        sys.exit(1)

    async with session_scope() as db:
        privilege_by_name: dict[str, Privilege] = {}
        for name in _BASELINE_PRIVILEGES:
            existing_priv = (
                await db.execute(select(Privilege).where(Privilege.name == name))
            ).scalar_one_or_none()
            if existing_priv is None:
                existing_priv = Privilege(name=name)
                db.add(existing_priv)
                await db.flush()
                logger.info("privilege_created", name=name)
            privilege_by_name[name] = existing_priv

        for role_name, priv_names in _BASELINE_ROLES.items():
            existing_role = (
                await db.execute(
                    select(Role)
                    .options(selectinload(Role.privileges))
                    .where(Role.name == role_name)
                )
            ).scalar_one_or_none()
            wanted = [privilege_by_name[p] for p in priv_names]
            if existing_role is None:
                db.add(Role(name=role_name, privileges=wanted))
                logger.info("role_created", name=role_name, privileges=priv_names)
            else:
                # A role created by an earlier phase's seed run must still
                # pick up privileges a *later* phase adds to its baseline —
                # re-running this script is how that sync happens, so this
                # can't be a create-only path. Missed exactly this the
                # first time: recon:manage_all was created as an orphan
                # Privilege row, never linked to "Account Admin", because
                # only the "role doesn't exist yet" branch ever touched
                # the association.
                missing = [p for p in wanted if p not in existing_role.privileges]
                if missing:
                    existing_role.privileges.extend(missing)
                    logger.info(
                        "role_privileges_synced",
                        name=role_name,
                        added=[p.name for p in missing],
                    )

        existing_user = (
            await db.execute(select(User).where(User.email == settings.bootstrap_admin_email))
        ).scalar_one_or_none()
        if existing_user is None:
            db.add(
                User(
                    email=settings.bootstrap_admin_email,
                    username=await derive_unique_username(db, settings.bootstrap_admin_email),
                    hashed_password=hash_password(settings.bootstrap_admin_password),
                    is_superuser=True,
                    # Matches the reference system's "Admin" (recon@admin.com)
                    # row exactly — see bug.md's screenshot of the live
                    # Manage Users screen.
                    user_types=["Account Admin", "Recon User"],
                    # Created directly, not via an invite that needs
                    # redeeming — see User.invite_accepted_at's docstring.
                    invite_accepted_at=datetime.now(UTC),
                )
            )
            logger.info("bootstrap_admin_created", email=settings.bootstrap_admin_email)
        else:
            # Backfills user_types on a row created before that column
            # existed — same idempotent-resync reasoning as the default
            # account below.
            bootstrap_user_types = ["Account Admin", "Recon User"]
            if existing_user.user_types != bootstrap_user_types:
                existing_user.user_types = bootstrap_user_types
                logger.info("bootstrap_admin_synced", email=settings.bootstrap_admin_email)
            else:
                logger.info("bootstrap_admin_already_exists", email=settings.bootstrap_admin_email)

        # Optional second bootstrap account (old backend's default@dart.com
        # convention). Also a full break-glass superuser, not an ordinary
        # account: confirmed against the live reference system's own
        # Manage Users screen (demo-dart.donyati.com/manageuser, see
        # bug.md at the repo root) — "Default Admin" (default@dart.com)
        # is shown holding every role (Account Admin, Group Owner,
        # Department Admin, Recon User, Team Admin), i.e. full privileges,
        # same as the bootstrap admin. An earlier version of this comment
        # called it "ordinary privileges, not a bypass" — that was wrong,
        # fixed here. Opt-in: skipped entirely, not an error, if either
        # value is unset.
        default_user_types = [
            "Account Admin",
            "Group Owner",
            "Department Admin",
            "Recon User",
            "Team Admin",
        ]
        if settings.default_user_email and settings.default_user_password:
            existing_default = (
                await db.execute(select(User).where(User.email == settings.default_user_email))
            ).scalar_one_or_none()
            if existing_default is None:
                db.add(
                    User(
                        email=settings.default_user_email,
                        username=await derive_unique_username(db, settings.default_user_email),
                        hashed_password=hash_password(settings.default_user_password),
                        is_superuser=True,
                        user_types=default_user_types,
                        invite_accepted_at=datetime.now(UTC),
                    )
                )
                logger.info("default_user_created", email=settings.default_user_email)
            else:
                # Re-running must still sync a row created before this fix
                # (wrong is_superuser, or the user_types column not set
                # yet) — same requirement the role/privilege loop above
                # already documents.
                changed = False
                if not existing_default.is_superuser:
                    existing_default.is_superuser = True
                    changed = True
                if existing_default.user_types != default_user_types:
                    existing_default.user_types = default_user_types
                    changed = True
                if changed:
                    logger.info("default_user_synced", email=settings.default_user_email)
                else:
                    logger.info("default_user_already_exists", email=settings.default_user_email)

        # The platform admin — the tier above both accounts above. This
        # script is the *only* way into it: `is_platform_admin` is absent
        # from every request schema, so conferring the tier requires
        # server access, and revoking it means editing the row directly.
        #
        # Also `is_superuser=True`, because the codebase has ad-hoc
        # `is_superuser` checks outside require_privilege (audit_logs.py,
        # recon_access.py, system_log.py). Setting both means the tier is
        # genuinely "above all" without having to find and widen each of
        # those, and without is_platform_admin quietly meaning less than
        # it says.
        if settings.platform_admin_email and settings.platform_admin_password:
            existing_platform = (
                await db.execute(select(User).where(User.email == settings.platform_admin_email))
            ).scalar_one_or_none()
            if existing_platform is None:
                db.add(
                    User(
                        email=settings.platform_admin_email,
                        username=await derive_unique_username(
                            db, settings.platform_admin_email
                        ),
                        hashed_password=hash_password(settings.platform_admin_password),
                        is_superuser=True,
                        is_platform_admin=True,
                        user_types=default_user_types,
                        invite_accepted_at=datetime.now(UTC),
                    )
                )
                logger.info("platform_admin_created", email=settings.platform_admin_email)
            else:
                # Promotes an account that already existed at this email
                # (e.g. seeded before this tier existed) rather than
                # failing on the unique-email constraint.
                changed = False
                if not existing_platform.is_platform_admin:
                    existing_platform.is_platform_admin = True
                    changed = True
                if not existing_platform.is_superuser:
                    existing_platform.is_superuser = True
                    changed = True
                if existing_platform.user_types != default_user_types:
                    existing_platform.user_types = default_user_types
                    changed = True
                if changed:
                    logger.info("platform_admin_synced", email=settings.platform_admin_email)
                else:
                    logger.info(
                        "platform_admin_already_exists", email=settings.platform_admin_email
                    )


if __name__ == "__main__":
    asyncio.run(seed())
