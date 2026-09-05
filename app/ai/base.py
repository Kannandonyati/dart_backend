"""The contract every future AI orchestrator (LangGraph or otherwise) must
implement, and nothing else.

Nothing in the rest of the app imports LangGraph, or any other
orchestration library, directly. Routes and services depend on this
`Orchestrator` protocol; `app.ai.registry` resolves the configured
implementation by name. That indirection is the whole point of this
module existing before there's any AI code to run — it's what lets the
orchestration layer get dropped in later as a new file implementing this
protocol plus one registry entry, instead of a rewrite touching routers,
services, and websocket plumbing that were built without it in mind.

`run()` is async-generator-shaped (streams events) rather than
request/response, because the two real use cases already anticipated —
a long-running agentic reconciliation-draft workflow, and token/progress
streaming back to the frontend over the WebSocket layer in app.ws — are
both inherently streaming. An implementation that only ever has one
final result can still conform by yielding exactly once.
"""

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Orchestrator(Protocol):
    """Structural interface — a LangGraph-backed implementation, a plain
    LangChain chain, or a hand-rolled agent loop are all valid as long as
    they satisfy this shape. No implementation of this protocol exists in
    this codebase yet; that's intentional."""

    name: str

    async def run(
        self, *, input: dict[str, Any], context: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield one or more event dicts as the orchestration progresses.
        Each event should be JSON-serializable as-is — callers (an SSE
        endpoint, or app.ws's broadcast()) forward these without
        transformation."""
        ...
