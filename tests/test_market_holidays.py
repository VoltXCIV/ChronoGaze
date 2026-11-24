import pandas as pd

from shared.market_holidays import load_ihsg_holidays


def test_ihsg_2026_holidays():
    days = [d for d in load_ihsg_holidays() if d.startswith("2026-")]
    assert len(days) == 22
    assert days[0] == "2026-01-01" and days[-1] == "2026-12-31"
    assert {"2026-03-18", "2026-03-24", "2026-08-17", "2026-08-25", "2026-12-24"} <= set(days)


def test_sorted_unique_and_weekdays_only(tmp_path):
    path = tmp_path / "h.csv"
    path.write_text("Date\n2026-12-25\n2026-01-01\n2026-12-25\n2026-11-28\n", encoding="utf-8")   # 28-11-26 is a Saturday
    assert load_ihsg_holidays(path) == ["2026-01-01", "2026-12-25"]


def test_missing_file(tmp_path):
    assert load_ihsg_holidays(tmp_path / "none.csv") == []


def test_weekend_trading_read_from_dates():
    from shared.market_holidays import trades_on_weekends
    every_day = pd.Series(pd.date_range("2026-01-01", periods=400))
    weekdays = pd.Series(pd.bdate_range("2026-01-01", periods=400))
    with_sundays = pd.Series(sorted(set(weekdays) | set(pd.date_range("2026-01-04", periods=60, freq="W-SUN"))))
    assert trades_on_weekends(every_day) is True          # crypto: no holidays
    assert trades_on_weekends(weekdays) is False          # weekends closed
    assert trades_on_weekends(with_sundays) is False      # a Sunday session only, about 1 bar in 6
    assert trades_on_weekends(pd.Series([], dtype="datetime64[ns]")) is False
