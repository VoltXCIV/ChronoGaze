import pandas as pd
import pytest

from shared.data_fetcher import cache_path, load_daily
from shared.utils import bare_ticker, normalize_ticker
from shared.validator import validate_ohlc


def good_df(n=5):
    dates = pd.bdate_range("2026-01-01", periods=n)
    return pd.DataFrame({
        "Date": dates,
        "Open": [10.0] * n,
        "High": [11.0] * n,
        "Low": [9.0] * n,
        "Close": [10.5] * n,
    })


def test_normalize_ticker_adds_idx_suffix():
    assert normalize_ticker("bbri") == "BBRI.JK"
    assert normalize_ticker("BBRI.JK") == "BBRI.JK"
    assert normalize_ticker("AAPL", suffix="") == "AAPL"


def test_bare_ticker_strips_suffix():
    assert bare_ticker("BBRI.JK") == "BBRI"
    assert bare_ticker("bbri") == "BBRI"


def test_validator_passes_clean_data():
    assert validate_ohlc(good_df()) == []


def test_validator_reports_missing_columns():
    problems = validate_ohlc(good_df().drop(columns=["High"]))
    assert problems and "missing columns" in problems[0]


def test_validator_catches_nan_and_duplicates():
    df = good_df()
    df.loc[2, "Close"] = float("nan")
    df.loc[4, "Date"] = df.loc[3, "Date"]
    problems = " ".join(validate_ohlc(df))
    assert "NaN" in problems
    assert "duplicate" in problems


def test_validator_catches_close_above_high():
    df = good_df()
    df.loc[1, "Close"] = 12.0
    assert any("High below Open/Close" in p for p in validate_ohlc(df))


def test_load_daily_uses_cache_without_network(tmp_path):
    df = good_df()
    path = cache_path("BBRI.JK", data_dir=tmp_path)
    df.to_csv(path, index=False)

    loaded = load_daily("BBRI", data_dir=tmp_path)  # must not call yfinance
    assert len(loaded) == len(df)
    assert list(loaded.columns) == ["Date", "Open", "High", "Low", "Close"]


def test_load_daily_rejects_bad_cache(tmp_path):
    df = good_df()
    df.loc[0, "High"] = 5.0  # High below Low
    df.to_csv(cache_path("BBRI", data_dir=tmp_path), index=False)
    with pytest.raises(ValueError):
        load_daily("BBRI", data_dir=tmp_path)
