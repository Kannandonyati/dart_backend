"""The catalog of UI components a platform admin can switch on and off.

Deliberately defined in code, not in a database table. The set of things
that *can* be toggled is a property of the frontend build — a sidebar
group exists because `sidebar-data.ts` declares it, and a tab exists
because a component renders it. A DB-held catalog would drift the moment
either side shipped without the other: rows for components that no
longer render, and new components invisible to the admin console until
someone remembered to INSERT them. Keeping the catalog here means the
registry ships with the code that honors it, and the database holds only
what an operator actually decided (see app/models/ui_component.py).

Keys are stable, hierarchical, and dotted. They are an API contract:
renaming one silently resurrects a component someone deliberately
disabled, because the stored override no longer matches anything. Add
new keys freely; don't rename existing ones.

Hierarchy is by `parent`, and disabling a parent disables everything
under it (`visible_component_keys` resolves this), which is what makes
"disable the Workflow Automation group" a single switch rather than six.

`api_prefixes` is what stops a toggle from being cosmetic. A component
that owns server routes lists them, and `require_component_enabled`
(app/core/component_access.py) rejects calls to them while it's off — so
hiding a page also closes the API behind it, and typing the URL by hand
or replaying a saved request gets 403 rather than data.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class ComponentKind(StrEnum):
    """Only used to group the admin console's tree — the resolver treats
    every kind identically."""

    SIDEBAR_GROUP = "sidebar_group"
    SIDEBAR_ITEM = "sidebar_item"
    PAGE_TAB = "page_tab"
    PIPELINE_STAGE = "pipeline_stage"
    SETTINGS_SECTION = "settings_section"


@dataclass(frozen=True)
class UiComponent:
    key: str
    label: str
    kind: ComponentKind
    parent: str | None = None
    description: str | None = None
    api_prefixes: tuple[str, ...] = field(default_factory=tuple)
    api_exempt_prefixes: tuple[str, ...] = field(default_factory=tuple)
    """Carved out of `api_prefixes`. Needed because a component's page
    and the application's own plumbing can share a URL prefix: Manage
    Users owns `/users`, but `/users/me` is what every client calls to
    learn who it is, so claiming it would mean switching off Manage Users
    logged everybody out."""
    locked: bool = False
    """Cannot be disabled by anyone. Reserved for the routes that would
    make the application unrecoverable if hidden — the admin console
    itself, and the Select stage every later pipeline stage depends on."""
    platform_only: bool = False
    """Hidden from everyone except a platform admin. Distinct from
    `locked`: locked means "cannot be switched off"; this means "is not
    part of anyone else's application at all." Without it, locking the
    console so it can't be disabled would also paint it onto every
    user's sidebar."""


_COMPONENTS: tuple[UiComponent, ...] = (
    # --- General ------------------------------------------------------
    UiComponent(
        key="sidebar.general",
        label="General",
        kind=ComponentKind.SIDEBAR_GROUP,
        description="Whole 'General' sidebar group.",
    ),
    UiComponent(
        key="sidebar.general.recon-pipeline",
        label="Recon Pipeline",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.general",
        api_prefixes=("/recons",),
    ),
    UiComponent(
        key="sidebar.general.manage-users",
        label="Manage Users",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.general",
        api_prefixes=("/users",),
        # /users/me is session hydration and /users/directory backs the
        # admin/member pickers on Manage Recon Security — neither belongs
        # to this page, and blocking them would break unrelated screens.
        # /users/accept-invite and /users/reset-password are public
        # token-redemption endpoints: hiding Manage Users must not stop
        # an invited user finishing signup or a reset completing.
        api_exempt_prefixes=(
            "/users/me",
            "/users/directory",
            "/users/accept-invite",
            "/users/reset-password",
        ),
    ),
    UiComponent(
        key="sidebar.general.maintenance",
        label="Maintenance",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.general",
        api_prefixes=("/system-logs",),
    ),
    UiComponent(
        key="sidebar.general.recon-security",
        label="Manage Recon Security",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.general",
        api_prefixes=("/lobs", "/teams", "/groups", "/roles"),
    ),
    UiComponent(
        key="sidebar.general.audit-logs",
        label="Audit Logs",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.general",
        api_prefixes=("/audit-logs",),
    ),
    # --- Workflow Automation ------------------------------------------
    UiComponent(
        key="sidebar.workflow-automation",
        label="Workflow Automation",
        kind=ComponentKind.SIDEBAR_GROUP,
        description="Whole 'Workflow Automation' sidebar group.",
    ),
    UiComponent(
        key="sidebar.workflow-automation.ai-auto-draft",
        label="AI Auto Draft",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.workflow-automation",
    ),
    UiComponent(
        key="sidebar.workflow-automation.ai-auto-draft.run-overview",
        label="Run Overview",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.workflow-automation.ai-auto-draft",
    ),
    UiComponent(
        key="sidebar.workflow-automation.ai-auto-draft.job-management",
        label="Job Management",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.workflow-automation.ai-auto-draft",
    ),
    UiComponent(
        key="sidebar.workflow-automation.ai-auto-draft.monitoring",
        label="Monitoring",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.workflow-automation.ai-auto-draft",
    ),
    UiComponent(
        key="sidebar.workflow-automation.scheduler",
        label="Workflow Scheduler",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.workflow-automation",
    ),
    UiComponent(
        key="sidebar.workflow-automation.scheduler.builder",
        label="Builder",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.workflow-automation.scheduler",
    ),
    UiComponent(
        key="sidebar.workflow-automation.scheduler.workflows",
        label="Workflows",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.workflow-automation.scheduler",
    ),
    UiComponent(
        key="sidebar.workflow-automation.scheduler.monitoring",
        label="Monitoring",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.workflow-automation.scheduler",
    ),
    UiComponent(
        key="sidebar.workflow-automation.scheduler.settings",
        label="Settings",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.workflow-automation.scheduler",
    ),
    # --- Other --------------------------------------------------------
    UiComponent(
        key="sidebar.other",
        label="Other",
        kind=ComponentKind.SIDEBAR_GROUP,
    ),
    UiComponent(
        key="sidebar.other.ask-dart",
        label="Ask DART",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.other",
    ),
    # --- Platform admin console ---------------------------------------
    UiComponent(
        key="sidebar.platform",
        label="Platform",
        kind=ComponentKind.SIDEBAR_GROUP,
        description="Platform-admin-only group. Always visible to a platform admin.",
        locked=True,
        platform_only=True,
    ),
    UiComponent(
        key="sidebar.platform.ui-components",
        label="UI Components",
        kind=ComponentKind.SIDEBAR_ITEM,
        parent="sidebar.platform",
        description="The console that manages this list. Cannot be switched off.",
        locked=True,
        platform_only=True,
    ),
    # --- Tabs: Manage Users -------------------------------------------
    UiComponent(
        key="manage-users.tabs.registered",
        label="Manage Users → Registered Users",
        kind=ComponentKind.PAGE_TAB,
        parent="sidebar.general.manage-users",
    ),
    UiComponent(
        key="manage-users.tabs.invited",
        label="Manage Users → Invited Users",
        kind=ComponentKind.PAGE_TAB,
        parent="sidebar.general.manage-users",
    ),
    UiComponent(
        key="manage-users.tabs.activity",
        label="Manage Users → User Activity",
        kind=ComponentKind.PAGE_TAB,
        parent="sidebar.general.manage-users",
    ),
    # --- Tabs: Audit Logs ---------------------------------------------
    UiComponent(
        key="audit-logs.tabs.history",
        label="Audit Logs → Audit Logs",
        kind=ComponentKind.PAGE_TAB,
        parent="sidebar.general.audit-logs",
    ),
    UiComponent(
        key="audit-logs.tabs.admin",
        label="Audit Logs → Admin Audit Logs",
        kind=ComponentKind.PAGE_TAB,
        parent="sidebar.general.audit-logs",
    ),
    UiComponent(
        key="audit-logs.tabs.recon",
        label="Audit Logs → Recon Audit Logs",
        kind=ComponentKind.PAGE_TAB,
        parent="sidebar.general.audit-logs",
    ),
    # --- Tabs: Manage Recon Security ----------------------------------
    UiComponent(
        key="recon-security.tabs.departments",
        label="Recon Security → Departments",
        kind=ComponentKind.PAGE_TAB,
        parent="sidebar.general.recon-security",
    ),
    UiComponent(
        key="recon-security.tabs.teams",
        label="Recon Security → Teams",
        kind=ComponentKind.PAGE_TAB,
        parent="sidebar.general.recon-security",
    ),
    UiComponent(
        key="recon-security.tabs.groups",
        label="Recon Security → Groups",
        kind=ComponentKind.PAGE_TAB,
        parent="sidebar.general.recon-security",
    ),
    UiComponent(
        key="recon-security.tabs.sso",
        label="Recon Security → SSO Dashboard",
        kind=ComponentKind.PAGE_TAB,
        parent="sidebar.general.recon-security",
    ),
    UiComponent(
        key="recon-security.groups.tabs.list",
        label="Recon Security → Groups → Group List",
        kind=ComponentKind.PAGE_TAB,
        parent="recon-security.tabs.groups",
    ),
    UiComponent(
        key="recon-security.groups.tabs.roles",
        label="Recon Security → Groups → Roles & Privileges",
        kind=ComponentKind.PAGE_TAB,
        parent="recon-security.tabs.groups",
    ),
    # --- Recon Pipeline stages ----------------------------------------
    UiComponent(
        key="recon-pipeline.stages.select",
        label="Recon Pipeline → Select",
        kind=ComponentKind.PIPELINE_STAGE,
        parent="sidebar.general.recon-pipeline",
        description="Entry stage — every later stage needs a selected recon.",
        locked=True,
    ),
    UiComponent(
        key="recon-pipeline.stages.dimension-linking",
        label="Recon Pipeline → Dimension Linking",
        kind=ComponentKind.PIPELINE_STAGE,
        parent="sidebar.general.recon-pipeline",
    ),
    UiComponent(
        key="recon-pipeline.stages.run-import",
        label="Recon Pipeline → Run Import",
        kind=ComponentKind.PIPELINE_STAGE,
        parent="sidebar.general.recon-pipeline",
    ),
    UiComponent(
        key="recon-pipeline.stages.bridge-members",
        label="Recon Pipeline → Bridge Members",
        kind=ComponentKind.PIPELINE_STAGE,
        parent="sidebar.general.recon-pipeline",
    ),
    UiComponent(
        key="recon-pipeline.stages.transformation",
        label="Recon Pipeline → Transformation",
        kind=ComponentKind.PIPELINE_STAGE,
        parent="sidebar.general.recon-pipeline",
    ),
    UiComponent(
        key="recon-pipeline.stages.run-report",
        label="Recon Pipeline → Run Report",
        kind=ComponentKind.PIPELINE_STAGE,
        parent="sidebar.general.recon-pipeline",
    ),
    # --- Settings sections --------------------------------------------
    UiComponent(
        key="settings.profile",
        label="Settings → Profile",
        kind=ComponentKind.SETTINGS_SECTION,
    ),
    UiComponent(
        key="settings.account",
        label="Settings → Account",
        kind=ComponentKind.SETTINGS_SECTION,
    ),
    UiComponent(
        key="settings.appearance",
        label="Settings → Appearance",
        kind=ComponentKind.SETTINGS_SECTION,
    ),
    UiComponent(
        key="settings.notifications",
        label="Settings → Notifications",
        kind=ComponentKind.SETTINGS_SECTION,
    ),
    UiComponent(
        key="settings.display",
        label="Settings → Display",
        kind=ComponentKind.SETTINGS_SECTION,
    ),
)


COMPONENTS_BY_KEY: dict[str, UiComponent] = {c.key: c for c in _COMPONENTS}
ALL_COMPONENTS: tuple[UiComponent, ...] = _COMPONENTS


def _validate_catalog() -> None:
    """Import-time guard against the two mistakes that would make the
    resolver silently wrong: a duplicate key (one entry shadowing
    another) and a `parent` that doesn't exist (a subtree that can never
    be reached, so disabling the parent wouldn't cascade)."""
    seen: set[str] = set()
    for component in _COMPONENTS:
        if component.key in seen:
            raise RuntimeError(f"Duplicate UI component key: {component.key}")
        seen.add(component.key)
    for component in _COMPONENTS:
        if component.parent is not None and component.parent not in seen:
            raise RuntimeError(
                f"UI component {component.key!r} has unknown parent {component.parent!r}"
            )


_validate_catalog()


def ancestors_of(key: str) -> list[str]:
    """The chain from a component's parent up to its root, nearest first.
    Empty for a root, and for an unknown key — callers treat unknown keys
    as visible, so an override left behind by a renamed component can
    never hide something."""
    chain: list[str] = []
    current = COMPONENTS_BY_KEY.get(key)
    while current is not None and current.parent is not None:
        chain.append(current.parent)
        current = COMPONENTS_BY_KEY.get(current.parent)
    return chain


def components_for_api_path(path: str) -> list[UiComponent]:
    """Every component that claims ownership of this request path.

    Matching is prefix-based on the path *after* the API version prefix,
    and boundary-aware: `/users` owns `/users` and `/users/x` but not
    `/users-elsewhere`. A path owned by nothing is unguarded, which is
    the right default — auth, health and the admin console itself must
    keep working no matter what is switched off.
    """
    def claims(prefixes: tuple[str, ...]) -> bool:
        return any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)

    return [
        component
        for component in _COMPONENTS
        if claims(component.api_prefixes) and not claims(component.api_exempt_prefixes)
    ]
