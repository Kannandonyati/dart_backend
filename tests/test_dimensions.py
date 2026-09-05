"""Dimension CRUD, reorder, mandatory-dimension seeding, and CSV
export/import tests."""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.models.user import User

LOGIN_URL = "/api/v1/auth/login"
RECONS_URL = "/api/v1/recons"

MANDATORY_COUNT = 3
"""Creating a recon already seeds YEAR/PERIOD/AMOUNT at positions 0-2
(app/core/recon_bootstrap.py), so anything added afterwards lands at
position `MANDATORY_COUNT` and up."""


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post(LOGIN_URL, json={"email": email, "password": password})
    token: str = response.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _owner_token_and_recon(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> tuple[str, str]:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")
    recon_id = (await client.post(RECONS_URL, headers=_auth(token), json={"name": "R1"})).json()[
        "id"
    ]
    return token, recon_id


def _dim_body(name: str, in_file: bool = True) -> dict:
    if in_file:
        mappings = [
            {"app_number": 1, "in_file": True, "column_location": "A"},
            {"app_number": 2, "in_file": True, "column_location": "B"},
        ]
    else:
        mappings = [
            {"app_number": 1, "in_file": False, "default_value": ""},
            {"app_number": 2, "in_file": False, "default_value": ""},
        ]
    return {"name": name, "mappings": mappings}


async def test_create_dimension_lowercases_input_uppercased_and_positioned(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_token_and_recon(client, make_user)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions", headers=_auth(token), json=_dim_body("account")
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "ACCOUNT"
    assert body["position"] == MANDATORY_COUNT
    assert body["is_mandatory"] is False
    assert len(body["mappings"]) == 2


async def test_create_dimension_missing_column_location_when_in_file_is_422(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_token_and_recon(client, make_user)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions",
        headers=_auth(token),
        json={
            "name": "BROKEN",
            "mappings": [
                {"app_number": 1, "in_file": True},
                {"app_number": 2, "in_file": False, "default_value": ""},
            ],
        },
    )
    assert response.status_code == 422


async def test_create_dimension_requires_both_app_numbers(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_token_and_recon(client, make_user)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions",
        headers=_auth(token),
        json={
            "name": "ONE_APP",
            "mappings": [{"app_number": 1, "in_file": True, "column_location": "A"}],
        },
    )
    assert response.status_code == 422


async def test_duplicate_dimension_name_is_conflict(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_token_and_recon(client, make_user)
    await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions", headers=_auth(token), json=_dim_body("Dup")
    )
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions", headers=_auth(token), json=_dim_body("dup")
    )
    assert response.status_code == 409


async def test_new_recon_starts_with_mandatory_dimensions(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Old-backend parity: `recon/create` left the recon without
    dimensions and the reference frontend seeded YEAR/PERIOD/AMOUNT
    itself, right after create returned. Both now happen in one
    transaction — see app/core/recon_bootstrap.py."""
    token, recon_id = await _owner_token_and_recon(client, make_user)

    listed = await client.get(f"{RECONS_URL}/{recon_id}/dimensions", headers=_auth(token))
    assert listed.status_code == 200
    body = listed.json()
    assert [d["name"] for d in body] == ["YEAR", "PERIOD", "AMOUNT"]
    assert [d["position"] for d in body] == [0, 1, 2]
    assert all(d["is_mandatory"] for d in body)
    # Seeded unmapped, so the user still points each at a real column.
    for dimension in body:
        assert [m["app_number"] for m in dimension["mappings"]] == [1, 2]
        assert all(m["in_file"] is False for m in dimension["mappings"])


async def test_seed_mandatory_dimensions_is_idempotent(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """A no-op on any recon created through this API, since create
    already seeded all three. Kept as a repair path for recons that
    predate that seeding."""
    token, recon_id = await _owner_token_and_recon(client, make_user)

    first = await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions/seed-mandatory", headers=_auth(token)
    )
    assert first.status_code == 200
    names = [d["name"] for d in first.json()]
    assert names == ["YEAR", "PERIOD", "AMOUNT"]
    assert all(d["is_mandatory"] for d in first.json())

    second = await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions/seed-mandatory", headers=_auth(token)
    )
    assert second.status_code == 200
    assert [d["name"] for d in second.json()] == ["YEAR", "PERIOD", "AMOUNT"]


async def test_mandatory_dimension_cannot_be_deleted(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_token_and_recon(client, make_user)
    seeded = await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions/seed-mandatory", headers=_auth(token)
    )
    year_id = next(d["id"] for d in seeded.json() if d["name"] == "YEAR")

    response = await client.delete(
        f"{RECONS_URL}/{recon_id}/dimensions/{year_id}", headers=_auth(token)
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "mandatory_dimension"


async def test_non_mandatory_dimension_can_be_deleted(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_token_and_recon(client, make_user)
    created = await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions", headers=_auth(token), json=_dim_body("TEMP")
    )
    dim_id = created.json()["id"]

    deleted = await client.delete(
        f"{RECONS_URL}/{recon_id}/dimensions/{dim_id}", headers=_auth(token)
    )
    assert deleted.status_code == 204

    fetched = await client.get(f"{RECONS_URL}/{recon_id}/dimensions/{dim_id}", headers=_auth(token))
    assert fetched.status_code == 404


async def test_reorder_shifts_intervening_dimensions(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_token_and_recon(client, make_user)
    ids = {}
    for name in ["A", "B", "C", "D"]:
        created = await client.post(
            f"{RECONS_URL}/{recon_id}/dimensions", headers=_auth(token), json=_dim_body(name)
        )
        ids[name] = created.json()["id"]
    # Sitting after the seeded mandatory three:
    # A=base, B=base+1, C=base+2, D=base+3
    base = MANDATORY_COUNT

    response = await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions/{ids['D']}/reorder",
        headers=_auth(token),
        json={"new_position": base + 1},
    )
    assert response.status_code == 200
    ordered = {d["id"]: d["position"] for d in response.json()}
    assert ordered[ids["A"]] == base
    assert ordered[ids["D"]] == base + 1
    assert ordered[ids["B"]] == base + 2
    assert ordered[ids["C"]] == base + 3


async def test_export_then_import_round_trips(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_token_and_recon(client, make_user)
    await client.post(f"{RECONS_URL}/{recon_id}/dimensions/seed-mandatory", headers=_auth(token))
    await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions", headers=_auth(token), json=_dim_body("CUSTOM_DIM")
    )

    exported = await client.get(f"{RECONS_URL}/{recon_id}/dimensions/export", headers=_auth(token))
    assert exported.status_code == 200
    assert "CUSTOM_DIM" in exported.text
    assert exported.headers["content-type"].startswith("text/csv")


async def test_import_replaces_non_mandatory_dimensions_but_keeps_mandatory(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_token_and_recon(client, make_user)
    await client.post(f"{RECONS_URL}/{recon_id}/dimensions/seed-mandatory", headers=_auth(token))
    await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions", headers=_auth(token), json=_dim_body("OLD_CUSTOM")
    )

    csv_content = (
        "serial_no,Dimension Name_1,Dimension In File_1,Location in File_1,"
        "Default Value_1,Active Flag_1,"
        "Dimension Name_2,Dimension In File_2,Location in File_2,"
        "Default Value_2,Active Flag_2\r\n"
        "1,NEW_CUSTOM,yes,C,,yes,NEW_CUSTOM,yes,D,,yes\r\n"
    )
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions/import",
        headers=_auth(token),
        files={"file": ("dimensions.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200
    names = {d["name"] for d in response.json()}
    assert "NEW_CUSTOM" in names
    assert "OLD_CUSTOM" not in names
    assert {"YEAR", "PERIOD", "AMOUNT"}.issubset(names)
    new_custom = next(d for d in response.json() if d["name"] == "NEW_CUSTOM")
    assert all(m["is_active"] is True for m in new_custom["mappings"])


async def test_import_old_dart_true_yes_flags_and_third_app(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """FCC/EPICOR/TABLEAU exports use YES/NO and TRUE/FALSE, with a
    third app's columns — not lowercase yes/no for apps 1–2 only."""
    token, recon_id = await _owner_token_and_recon(client, make_user)
    created = await client.post(
        f"{RECONS_URL}/{recon_id}/apps",
        headers=_auth(token),
        json={"app_number": 3, "name": "EPICOR"},
    )
    assert created.status_code == 201, created.text
    await client.post(f"{RECONS_URL}/{recon_id}/dimensions/seed-mandatory", headers=_auth(token))

    csv_content = (
        "serial_no,Dimension Name_1,Dimension In File_1,Location in File_1,"
        "Default Value_1,Active Flag_1,"
        "Dimension Name_2,Dimension In File_2,Location in File_2,"
        "Default Value_2,Active Flag_2,"
        "Dimension Name_3,Dimension In File_3,Location in File_3,"
        "Default Value_3,Active Flag_3\r\n"
        "0,YEAR,YES,2,,TRUE,YEAR,YES,1,,TRUE,YEAR,YES,1,,TRUE\r\n"
        "1,ENTITY,YES,3,,TRUE,COMPANY,YES,2,,TRUE,COMPANY,YES,2,,TRUE\r\n"
        "2,VIEW,YES,1,,TRUE,VIEW,NO,,FCCS_Periodic,TRUE,VIEW,NO,,FCCS_Periodic,TRUE\r\n"
    )
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions/import",
        headers=_auth(token),
        files={"file": ("dimensions.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200, response.text
    by_name = {d["name"]: d for d in response.json()}
    assert by_name["ENTITY"]["mappings"]
    assert all(m["is_active"] is True for m in by_name["ENTITY"]["mappings"])
    assert {m["app_number"] for m in by_name["ENTITY"]["mappings"]} == {1, 2, 3}
    year = by_name["YEAR"]
    assert all(m["is_active"] is True and m["in_file"] is True for m in year["mappings"])
    view = by_name["VIEW"]
    app2 = next(m for m in view["mappings"] if m["app_number"] == 2)
    assert app2["in_file"] is False
    assert app2["default_value"] == "FCCS_Periodic"
    assert app2["is_active"] is True


async def test_import_legacy_slno_dimension_template(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Old DART / MockDataDimension.csv repeats unnumbered headers
    (slno, dimension, dim in file, …) once per app. Headers are ignored;
    each app is five positional columns after serial_no."""
    token, recon_id = await _owner_token_and_recon(client, make_user)
    await client.post(f"{RECONS_URL}/{recon_id}/dimensions/seed-mandatory", headers=_auth(token))

    csv_content = (
        "slno,dimension,dim in file,yes type field,no type top member,is_active,"
        "dimension,dim in file,yes type field,no type top member,is_active\r\n"
        "0,YEAR,YES,1,,TRUE,YEAR,YES,1,,TRUE\r\n"
        "1,PERIOD,YES,2,,TRUE,PERIOD,YES,2,,TRUE\r\n"
        "2,AMOUNT,YES,8,,TRUE,AMOUNT,YES,7,,TRUE\r\n"
        "3,Entity,YES,3,,TRUE,Entity,YES,3,,TRUE\r\n"
        "4,Geography,YES,4,,TRUE,Geo,YES,4,,TRUE\r\n"
        "6,Project,YES,6,,TRUE,PlaceHolder,NO,,plchldr,TRUE\r\n"
    )
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions/import",
        headers=_auth(token),
        files={"file": ("MockDataDimension.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200, response.text
    by_name = {d["name"]: d for d in response.json()}
    assert {"YEAR", "PERIOD", "AMOUNT", "ENTITY", "GEOGRAPHY", "PROJECT"}.issubset(by_name)
    entity_apps = {m["app_number"]: m for m in by_name["ENTITY"]["mappings"]}
    assert entity_apps[1]["in_file"] is True
    assert entity_apps[1]["column_location"] == "3"
    project_app2 = next(m for m in by_name["PROJECT"]["mappings"] if m["app_number"] == 2)
    assert project_app2["in_file"] is False
    assert project_app2["default_value"] == "plchldr"


async def test_import_malformed_row_aborts_without_partial_writes(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_token_and_recon(client, make_user)
    await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions", headers=_auth(token), json=_dim_body("SURVIVOR")
    )

    csv_content = "serial_no,Dimension Name_1\r\n1,\r\n"
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/dimensions/import",
        headers=_auth(token),
        files={"file": ("dimensions.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 400

    listed = await client.get(f"{RECONS_URL}/{recon_id}/dimensions", headers=_auth(token))
    assert any(d["name"] == "SURVIVOR" for d in listed.json())


async def test_non_owner_gets_404_not_403_for_dimensions(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_token_and_recon(client, make_user)
    await make_user(email="b@dart.com", username="b", password="Password123!")
    token_b = await _login(client, "b@dart.com", "Password123!")

    response = await client.get(f"{RECONS_URL}/{recon_id}/dimensions", headers=_auth(token_b))
    assert response.status_code == 404
