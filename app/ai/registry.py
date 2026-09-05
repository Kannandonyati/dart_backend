"""Name → Orchestrator registry, resolved as a FastAPI dependency.

Usage once a real orchestrator exists:

    # app/ai/langgraph_orchestrator.py
    from app.ai.base import Orchestrator
    from app.ai.registry import register

    class LangGraphOrchestrator:
        name = "recon_draft"
        async def run(self, *, input, context=None):
            ...

    register(LangGraphOrchestrator())

Then in a router:

    from app.ai.registry import get_orchestrator

    @router.post("/ai/recon-draft")
    async def start_draft(orchestrator = Depends(get_orchestrator("recon_draft"))):
        async for event in orchestrator.run(input=...):
            ...

No orchestrator is registered today — `get_orchestrator` raising
`OrchestratorNotConfigured` is the expected, correct behavior until one
is.
"""

from collections.abc import Callable

from fastapi import HTTPException, status

from app.ai.base import Orchestrator

_registry: dict[str, Orchestrator] = {}


class OrchestratorNotConfigured(Exception):
    pass


def register(orchestrator: Orchestrator) -> None:
    _registry[orchestrator.name] = orchestrator


def get_orchestrator(name: str) -> Callable[[], Orchestrator]:
    def _dependency() -> Orchestrator:
        try:
            return _registry[name]
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"AI orchestrator '{name}' is not configured yet.",
            ) from exc

    return _dependency
