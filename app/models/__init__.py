"""Import every model module here so app.db.base.Base.metadata is fully
populated for Alembic autogenerate, and so SQLAlchemy's mapper registry
can resolve the string-quoted relationship() references between modules
(e.g. User.memberships -> "Membership") regardless of import order
elsewhere in the app."""

from app.models.audit import AuditLog
from app.models.audit_mode import AuditMode
from app.models.bridge import BridgeMapping, BridgeRun, BridgeRunStatus
from app.models.global_variable import GlobalVariable, group_global_variables
from app.models.sso import SsoAuditLog, SsoProvider
from app.models.system_log import SystemLog
from app.models.dimension import Dimension, DimensionMapping, ReconApp
from app.models.import_run import ImportedRow, ImportRun, ImportStatus
from app.models.recon import Recon, recon_group_xref
from app.models.report import ReportFilter, ReportSignoff
from app.models.security import (
    Group,
    Lob,
    Membership,
    Privilege,
    Role,
    ScopeType,
    Team,
    group_lobs,
    group_roles,
    group_teams,
)
from app.models.sync import SyncMapping
from app.models.ui_component import UiComponentSetting
from app.models.user import User

__all__ = [
    "AuditLog",
    "AuditMode",
    "BridgeMapping",
    "BridgeRun",
    "BridgeRunStatus",
    "Dimension",
    "DimensionMapping",
    "GlobalVariable",
    "Group",
    "ImportRun",
    "ImportStatus",
    "ImportedRow",
    "Lob",
    "Membership",
    "Privilege",
    "Recon",
    "ReconApp",
    "ReportFilter",
    "ReportSignoff",
    "Role",
    "ScopeType",
    "SsoAuditLog",
    "SsoProvider",
    "SyncMapping",
    "SystemLog",
    "Team",
    "UiComponentSetting",
    "User",
    "group_global_variables",
    "group_lobs",
    "group_roles",
    "group_teams",
    "recon_group_xref",
]
