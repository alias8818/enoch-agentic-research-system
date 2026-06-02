from scripts.validate_dashboard_operator_inventory import validate


def test_dashboard_operator_inventory_is_complete() -> None:
    assert validate() == []
