"""Trend state of every bar, read from the swing highs and lows.

Rules:
  Uptrend    the last 3 swing highs rise (2 Higher Highs in a row) and the last
             3 swing lows rise (2 Higher Lows in a row).
  Downtrend  the last 3 swing highs fall (2 Lower Highs) and the last 3 swing
             lows fall (2 Lower Lows).
  Sideways   otherwise, when the most recent swings (at least 2 highs and 2
             lows) stay in a flat band: the highs lie within SIDEWAYS_TOL of
             each other and so do the lows, and the band has lasted more than
             SIDEWAYS_MIN_BARS bars.
  No trend   none of the above ("").

A swing at bar j is only known once bar j+1 exists (it needs its right-hand
neighbour), so the state at bar i uses swings at bars < i: no look-ahead.
"""
from __future__ import annotations

import pandas as pd

from shared.swing_detector import TAG_SWING_HIGH, TAG_SWING_LOW

UP, DOWN, SIDEWAYS, NONE = "Uptrend", "Downtrend", "Sideways", ""
SIDEWAYS_TOL = 0.03          # 3 %
SIDEWAYS_MIN_BARS = 7        # must last more than this


def _rising(x: list[float]) -> bool:
    return len(x) >= 3 and x[-3] < x[-2] < x[-1]


def _falling(x: list[float]) -> bool:
    return len(x) >= 3 and x[-3] > x[-2] > x[-1]


def _flat(prices: list[float], tol: float) -> bool:
    return min(prices) > 0 and max(prices) / min(prices) - 1 <= tol


def _sideways_start(swings: list[tuple[int, str, float]], tol: float) -> int | None:
    """Bar index where the flat band of the latest swings begins, or None.

    Walks back from the newest swing while the highs stay within `tol` of each
    other and the lows too; needs at least 2 highs and 2 lows in the band.
    """
    highs: list[float] = []
    lows: list[float] = []
    start = None
    for idx, kind, price in reversed(swings):
        cand_h = highs + [price] if kind == TAG_SWING_HIGH else highs
        cand_l = lows + [price] if kind == TAG_SWING_LOW else lows
        if (cand_h and not _flat(cand_h, tol)) or (cand_l and not _flat(cand_l, tol)):
            break
        highs, lows, start = cand_h, cand_l, idx
    return start if len(highs) >= 2 and len(lows) >= 2 else None


def trend_states(tagged: pd.DataFrame, tol: float = SIDEWAYS_TOL,
                 min_bars: int = SIDEWAYS_MIN_BARS) -> list[str]:
    """One trend label per bar of `tagged` (output of tag_bars)."""
    data = tagged.reset_index(drop=True)
    tags = data["Tag"].tolist()
    high, low = data["High"].tolist(), data["Low"].tolist()
    swings: list[tuple[int, str, float]] = []
    highs: list[float] = []
    lows: list[float] = []
    out: list[str] = []
    base, side_from = NONE, None
    for i in range(len(data)):
        j = i - 1                                    # swing at j becomes known at bar i
        if j >= 0 and tags[j] in (TAG_SWING_HIGH, TAG_SWING_LOW):
            price = high[j] if tags[j] == TAG_SWING_HIGH else low[j]
            swings.append((j, tags[j], price))
            (highs if tags[j] == TAG_SWING_HIGH else lows).append(price)
            if _rising(highs) and _rising(lows):
                base = UP
            elif _falling(highs) and _falling(lows):
                base = DOWN
            else:
                base = NONE
            side_from = _sideways_start(swings, tol) if base == NONE else None
        if base != NONE:
            out.append(base)
        elif side_from is not None and i - side_from > min_bars:
            out.append(SIDEWAYS)
        else:
            out.append(NONE)
    return out


def current_trend(tagged: pd.DataFrame, none_as: str = NONE) -> dict:
    """Trend at the last bar of `tagged`, with the date that state began.

    {"trend": "Uptrend" | "Downtrend" | "Sideways" | "", "since": "YYYY-MM-DD" or "",
     "last": "YYYY-MM-DD"} (dates from the "Date" column). Bars with no trend
    are labelled `none_as` (e.g. SIDEWAYS) before the state and its start are read.
    """
    states = [s or none_as for s in trend_states(tagged)]
    if not states:
        return {"trend": NONE, "since": "", "last": ""}
    dates = pd.to_datetime(tagged["Date"]).dt.strftime("%Y-%m-%d").tolist()
    now, i = states[-1], len(states) - 1
    while i > 0 and states[i - 1] == now:
        i -= 1
    return {"trend": now, "since": dates[i] if now else "", "last": dates[-1]}


TREND_DENOISE = 3            # candles merged by Denoised Swing before reading a stock's trend


def stock_trend(df: pd.DataFrame, period: int = TREND_DENOISE) -> dict:
    """Current trend of a stock (OHLC with Date, High, Low), as shown in the Aspect Calendar.

    Swings are marked with Denoised Swing (`period` candles), then the trend
    rules above are read; a bar with no trend counts as Sideways. Same dict as
    current_trend().
    """
    from shared.swing_detector import TAG_NONE, denoised_swings

    data = df.reset_index(drop=True).copy()
    tags = [TAG_NONE] * len(data)
    for i, kind in denoised_swings(data["High"].to_numpy(dtype=float), data["Low"].to_numpy(dtype=float), period):
        tags[i] = kind
    data["Tag"] = tags
    return current_trend(data, none_as=SIDEWAYS)
