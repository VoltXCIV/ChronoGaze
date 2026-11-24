"""Market calendars for the Time Geometry Calculator.

IHSG: weekends and the BEI holidays in db/ihsg_holidays.csv, one date per row
(column Date, YYYY-MM-DD). Add the next year's holidays to the CSV once BEI
publishes them. The holidays apply to IHSG only.

Global: no holidays. Whether Saturdays and Sundays count is read from the data:
crypto trades every day, other global markets are closed on weekends.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

HOLIDAYS_PATH = Path(__file__).resolve().parent.parent / "db" / "ihsg_holidays.csv"

# A market that trades every day has about 2 weekend bars in every 7 (28.6%).
WEEKEND_RECENT_BARS = 250
WEEKEND_MIN_SHARE = 0.2


def load_ihsg_holidays(path: Path = HOLIDAYS_PATH) -> list[str]:
    """Sorted, unique holiday dates as YYYY-MM-DD; weekend dates are dropped."""
    if not path.exists():
        return []
    dates = pd.to_datetime(pd.read_csv(path)["Date"], format="%Y-%m-%d")
    dates = dates[dates.dt.day_of_week < 5]
    return sorted(set(dates.dt.strftime("%Y-%m-%d")))


def trades_on_weekends(dates: pd.Series, recent: int = WEEKEND_RECENT_BARS,
                       min_share: float = WEEKEND_MIN_SHARE) -> bool:
    """True when the data trades on Saturdays and Sundays, like crypto.

    Judged on the last `recent` bars: at least `min_share` of them fall on a
    weekend. A Monday-Friday market has none; a feed with only a Sunday session
    has about 1 in 6, which stays below the default share.
    """
    days = pd.to_datetime(pd.Series(dates)).iloc[-recent:].dt.day_of_week
    return bool(len(days)) and float((days >= 5).mean()) >= min_share
