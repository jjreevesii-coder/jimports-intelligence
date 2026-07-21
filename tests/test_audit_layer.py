from app.audit_layer import (
    VALIDATED_TRAFFIC_SOURCE_LABELS,
    overall_status,
    reconciliation_check,
)


def test_traffic_source_mapping():
    assert (
        VALIDATED_TRAFFIC_SOURCE_LABELS["SUBSCRIBER"]
        == "Browse features"
    )
    assert (
        VALIDATED_TRAFFIC_SOURCE_LABELS["NO_LINK_OTHER"]
        == "Direct or unknown"
    )
    assert (
        VALIDATED_TRAFFIC_SOURCE_LABELS["YT_OTHER_PAGE"]
        == "Other YouTube features"
    )


def test_reconciliation_pass():
    result = reconciliation_check(
        "test",
        expected=100000,
        observed=99500,
    )
    assert result["status"] == "PASS"


def test_reconciliation_warn():
    result = reconciliation_check(
        "test",
        expected=100000,
        observed=98000,
    )
    assert result["status"] == "WARN"


def test_reconciliation_fail():
    result = reconciliation_check(
        "test",
        expected=100000,
        observed=95000,
    )
    assert result["status"] == "FAIL"


def test_overall_status():
    assert overall_status([
        {"status": "PASS"},
        {"status": "PASS"},
    ]) == "PASS"

    assert overall_status([
        {"status": "PASS"},
        {"status": "WARN"},
    ]) == "WARN"

    assert overall_status([
        {"status": "WARN"},
        {"status": "FAIL"},
    ]) == "FAIL"
