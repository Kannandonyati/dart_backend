"""Aggregates every v1 endpoint module under one router, included once in
main.py with the api_v1_prefix. Add new endpoint modules here as the
reconciliation API is built — nothing in main.py needs to change."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    audit_logs,
    audit_mode,
    auth,
    bridge_data,
    bridge_kickouts,
    bridge_mappings,
    bridge_runs,
    dimensions,
    global_variables,
    groups,
    health,
    imports,
    lobs,
    recon_apps,
    recons,
    report_data,
    report_filters,
    roles,
    sso,
    sync_data,
    sync_mappings,
    system_logs,
    teams,
    ui_components,
    user_maintenance,
    users,
)
from app.api.v1.endpoints.ui_components import COMPONENT_GUARD

api_router = APIRouter()

# Routers whose page can be switched off in the platform admin console.
# Listing them here rather than decorating each module keeps the "which
# APIs does this component own" answer in one place — the catalog's
# api_prefixes (app/core/ui_components.py) — with this as the single
# opt-in. Deliberately excluded: health and auth (a disabled component
# must never stop anyone logging in), and ui_components itself (it
# guards its own access, and routing it through the guard it configures
# would be circular).
_GUARDED = [COMPONENT_GUARD]
api_router.include_router(health.router)
api_router.include_router(auth.router)
# user_maintenance before users: its literal "/users/invited" must be
# matched before users.py's parameterized "/users/{user_id}", same
# literal-before-parameterized rule every prior phase has needed.
api_router.include_router(ui_components.router)
api_router.include_router(user_maintenance.router, dependencies=_GUARDED)
api_router.include_router(users.router, dependencies=_GUARDED)
api_router.include_router(recons.router, dependencies=_GUARDED)
api_router.include_router(lobs.router, dependencies=_GUARDED)
api_router.include_router(teams.router, dependencies=_GUARDED)
api_router.include_router(groups.router, dependencies=_GUARDED)
api_router.include_router(roles.router, dependencies=_GUARDED)
api_router.include_router(sso.router)
api_router.include_router(audit_mode.router)
api_router.include_router(global_variables.router)
api_router.include_router(recon_apps.router, dependencies=_GUARDED)
api_router.include_router(dimensions.router, dependencies=_GUARDED)
api_router.include_router(imports.router, dependencies=_GUARDED)
api_router.include_router(bridge_mappings.router, dependencies=_GUARDED)
api_router.include_router(bridge_kickouts.router, dependencies=_GUARDED)
api_router.include_router(bridge_runs.router, dependencies=_GUARDED)
api_router.include_router(bridge_data.router, dependencies=_GUARDED)
api_router.include_router(sync_mappings.router, dependencies=_GUARDED)
api_router.include_router(sync_data.router, dependencies=_GUARDED)
api_router.include_router(report_filters.router, dependencies=_GUARDED)
api_router.include_router(report_data.router, dependencies=_GUARDED)
api_router.include_router(audit_logs.router, dependencies=_GUARDED)
api_router.include_router(audit_logs.recon_router, dependencies=_GUARDED)
api_router.include_router(system_logs.router, dependencies=_GUARDED)
