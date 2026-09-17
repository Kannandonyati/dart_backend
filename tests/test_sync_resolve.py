"""Unit tests for Transformation resolve — old dart-db tfn join."""

from types import SimpleNamespace

from app.services.sync_resolve import apply_sync_mappings, sync_source_value, zip_distinct_lists


def _mapping(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "app_number": 1,
        "dimension_names": ["ACCOUNT"],
        "concat_delimiter": "-",
        "source_sync": "1000",
        "target_sync": "CASH",
        "flip_sign": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_sync_source_prefers_bridged_value_over_raw() -> None:
    assert sync_source_value("ACCOUNT", {"ACCOUNT": "1000"}, {"ACCOUNT": "CASH"}) == "CASH"


def test_sync_source_falls_back_to_raw_when_bridged_is_kickout() -> None:
    assert sync_source_value("ACCOUNT", {"ACCOUNT": "1000"}, {"ACCOUNT": "kickout"}) == "1000"


def test_apply_maps_concat_and_flip_sign_on_top_of_bridge_amount() -> None:
    result = apply_sync_mappings(
        app_number=1,
        data={"ACCOUNT": "1000", "COST_CENTER": "CC1"},
        resolved={"ACCOUNT": "1000", "COST_CENTER": "CC1"},
        mappings=[
            _mapping(
                dimension_names=["ACCOUNT", "COST_CENTER"],
                concat_delimiter="|",
                source_sync="1000|CC1",
                target_sync="CASH_CC1",
                flip_sign=True,
            )
        ],
        amount="100.00",
        sign_reversed_amount="100.00",
    )
    assert result.synced == {"ACCOUNT-COST_CENTER": "CASH_CC1"}
    assert result.flip_sign is True
    assert result.sign_reversed_amount == "-100.00"


def test_zip_distinct_lists_pairs_positionally_not_product() -> None:
    combos = zip_distinct_lists([["1000", "2000"], ["CC1", "CC2"]], delimiter="|")
    assert combos == ["1000|CC1", "2000|CC2"]
