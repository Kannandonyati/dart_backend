import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import engine


async def main() -> None:
    statements = [
        """
        ALTER TABLE recon_apps
        ADD COLUMN IF NOT EXISTS global_variable_id UUID
        REFERENCES global_variables(id) ON DELETE SET NULL
        """,
        """
        ALTER TABLE import_runs
        ADD COLUMN IF NOT EXISTS je_flag BOOLEAN NOT NULL DEFAULT FALSE
        """,
    ]
    async with engine.begin() as conn:
        for sql in statements:
            await conn.execute(text(sql))
    await engine.dispose()
    print("pipeline gap columns ready")


if __name__ == "__main__":
    asyncio.run(main())
