"""Shared setup for the pipeline tests downstream of Dimension Linking
(Run Import, Bridge, Transformation, Run Report).

Creating a recon now also creates its two apps and YEAR/PERIOD/AMOUNT,
unmapped (see app/core/recon_bootstrap.py). So a test that wants a
dimension reading a real file column has to update the seeded row
rather than create one — `POST /dimensions` would be a 409 on any of
the mandatory three. `configure_dimensions` does whichever applies.

These setups all point every mandatory dimension at a real column,
including PERIOD. That isn't incidental: a dimension left "not in file"
contributes its default value to every parsed row (see
app/services/import_validation.py), so a PERIOD nobody configured would
otherwise show up as an empty-string column in imported data, bridge
mappings, and report output.
"""

from httpx import AsyncClient

RECONS_URL = "/api/v1/recons"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def configure_dimensions(
    client: AsyncClient,
    token: str,
    recon_id: str,
    columns: list[tuple[str, str]],
) -> dict[str, str]:
    """Points each named dimension at `column` in both apps' files,
    creating it if the recon doesn't already have it. Returns the
    dimension ids by name."""
    listed = await client.get(f"{RECONS_URL}/{recon_id}/dimensions", headers=auth(token))
    existing = {d["name"]: d["id"] for d in listed.json()}

    ids: dict[str, str] = {}
    for name, column in columns:
        mappings = [
            {"app_number": app_number, "in_file": True, "column_location": column}
            for app_number in (1, 2)
        ]
        dimension_id = existing.get(name.upper())
        if dimension_id is None:
            created = await client.post(
                f"{RECONS_URL}/{recon_id}/dimensions",
                headers=auth(token),
                json={"name": name, "mappings": mappings},
            )
            assert created.status_code == 201, created.text
            ids[name.upper()] = created.json()["id"]
        else:
            updated = await client.patch(
                f"{RECONS_URL}/{recon_id}/dimensions/{dimension_id}",
                headers=auth(token),
                json={"mappings": mappings},
            )
            assert updated.status_code == 200, updated.text
            ids[name.upper()] = dimension_id
    return ids
