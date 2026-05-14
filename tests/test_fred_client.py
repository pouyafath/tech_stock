from src.fred_client import _macro_summary


def test_macro_summary_includes_all_available_fields():
    assert (
        _macro_summary(5.25, 0.18, 3.1, 17.8)
        == "Rates: 5.25% | Curve: +0.18% | CPI: +3.1% YoY | VIX: 17.8"
    )


def test_macro_summary_handles_missing_optional_fields():
    assert _macro_summary(5.25, None, 3.1, None) == "Rates: 5.25% | CPI: +3.1% YoY"
