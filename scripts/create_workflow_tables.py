import asyncio

from app.db.session import engine
from app.models.workflow import Workflow, WorkflowRun, WorkflowRunStep


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Workflow.__table__.create(c, checkfirst=True))
        await conn.run_sync(lambda c: WorkflowRun.__table__.create(c, checkfirst=True))
        await conn.run_sync(lambda c: WorkflowRunStep.__table__.create(c, checkfirst=True))
    await engine.dispose()
    print("workflow tables ready")


if __name__ == "__main__":
    asyncio.run(main())
