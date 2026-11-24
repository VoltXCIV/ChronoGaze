"""Tag every bar of daily OHLC data as swing high, swing low, inside bar, or nothing.

Rules:
  1. Inside bar: High[N] < High[N-1] and Low[N] > Low[N-1]. Tag only; it does
     not change swing detection and is not drawn on the chart.
  2. Swing high candidate: High[N] > High[N-1] and High[N] > High[N+1].
     Swing low candidate:  Low[N]  < Low[N-1]  and Low[N]  < Low[N+1].
     (Strict: an equal neighbour means no candidate. The first and last bar
     can never be candidates because one neighbour is missing.)
  3. Swings alternate HIGH / LOW. Consecutive candidates of the same type
     with no opposite swing between them collapse to one: the highest high
     (or lowest low). On an exact tie the newest bar wins.
  4. A bar that is both a high and a low candidate (outside bar) becomes the
     type opposite to the previous swing. If there is no previous swing it
     is ignored.

The result is deterministic: the same input always gives the same tags.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TAG_SWING_HIGH = "SH"
TAG_SWING_LOW = "SL"
TAG_INSIDE = "IB"
TAG_NONE = ""


def inside_bar_mask(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    inside = np.zeros(len(high), dtype=bool)
    if len(high) > 1:
        inside[1:] = (high[1:] < high[:-1]) & (low[1:] > low[:-1])
    return inside


def _candidates(high: np.ndarray, low: np.ndarray) -> list[tuple[int, bool, bool]]:
    """(bar index, is_high_candidate, is_low_candidate) for bars that qualify."""
    out = []
    for i in range(1, len(high) - 1):
        is_high = high[i] > high[i - 1] and high[i] > high[i + 1]
        is_low = low[i] < low[i - 1] and low[i] < low[i + 1]
        if is_high or is_low:
            out.append((i, bool(is_high), bool(is_low)))
    return out


def find_swings(high: np.ndarray, low: np.ndarray) -> list[tuple[int, str]]:
    """Return alternating swing points as (bar index, "SH" | "SL")."""
    points: list[tuple[int, str]] = []
    for i, is_high, is_low in _candidates(high, low):
        if is_high and is_low:
            if not points:
                continue
            kind = TAG_SWING_LOW if points[-1][1] == TAG_SWING_HIGH else TAG_SWING_HIGH
        else:
            kind = TAG_SWING_HIGH if is_high else TAG_SWING_LOW

        if points and points[-1][1] == kind:
            j = points[-1][0]
            if kind == TAG_SWING_HIGH:
                replace = high[i] >= high[j]   # tie -> newer bar
            else:
                replace = low[i] <= low[j]
            if replace:
                points[-1] = (i, kind)
            continue
        points.append((i, kind))
    return points


def swing_moves(tagged: pd.DataFrame) -> list[dict]:
    """One record per swing: the move from it to the next (opposite) swing.

    `tagged` is the output of `tag_bars` (needs Date, High, Low, Tag).
    For a swing high the move runs from its High to the Low of the next
    swing low; for a swing low, from its Low to the High of the next swing
    high. `bars` counts bars between the two swings. The last swing has no
    next swing yet, so its move fields are None.
    """
    data = tagged.reset_index(drop=True)
    pos = data.index[data["Tag"].isin([TAG_SWING_HIGH, TAG_SWING_LOW])].tolist()
    moves = []
    for k, i in enumerate(pos):
        kind = data.at[i, "Tag"]
        price = float(data.at[i, "High"] if kind == TAG_SWING_HIGH else data.at[i, "Low"])
        rec = {"date": data.at[i, "Date"].strftime("%Y-%m-%d"), "type": kind, "price": price,
               "next_date": None, "next_price": None, "bars": None, "change": None, "pct": None}
        if k + 1 < len(pos):
            j = pos[k + 1]
            nxt = float(data.at[j, "Low"] if kind == TAG_SWING_HIGH else data.at[j, "High"])
            rec.update(next_date=data.at[j, "Date"].strftime("%Y-%m-%d"), next_price=nxt,
                       bars=int(j - i), change=nxt - price, pct=(nxt - price) / price * 100)
        moves.append(rec)
    return moves


def tag_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `df` with a `Tag` column: "SH", "SL", "IB" or "".

    `df` needs High and Low columns in bar order (oldest first).
    An inside bar can never be a swing (its high and low sit inside the
    previous bar), so one tag per bar is enough.
    """
    high = df["High"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)

    tags = np.full(len(df), TAG_NONE, dtype=object)
    tags[inside_bar_mask(high, low)] = TAG_INSIDE
    for i, kind in find_swings(high, low):
        tags[i] = kind

    out = df.copy()
    out["Tag"] = tags
    return out


def _collapse(points: list[tuple[int, str]], high: np.ndarray, low: np.ndarray) -> list[tuple[int, str]]:
    """Make swings alternate: consecutive same-type swings keep the most extreme
    one (highest high / lowest low), the newest on an exact tie."""
    out: list[tuple[int, str]] = []
    for i, kind in points:
        if out and out[-1][1] == kind:
            j = out[-1][0]
            better = high[i] >= high[j] if kind == TAG_SWING_HIGH else low[i] <= low[j]
            if better:
                out[-1] = (i, kind)
            continue
        out.append((i, kind))
    return out


def denoised_swings(high: np.ndarray, low: np.ndarray, period: int) -> list[tuple[int, str]]:
    """Swings that survive merging every `period` bars into one bar.

    1. Bars are grouped in blocks of `period`, counted from the first bar
       (so blocks stay put when new bars arrive; only the last block grows).
       A block's High is the highest High in it, its Low the lowest Low.
    2. `find_swings` runs on the blocks.
    3. A regular (1-bar) swing is valid when the block it sits in is a swing
       of the same type. Its own date is kept, not the block's.
    4. Valid swings are made to alternate again (see `_collapse`).

    period=1 gives exactly the regular swings.
    """
    period = max(1, int(period))
    regular = find_swings(high, low)
    if period == 1:
        return regular
    n = len(high)
    starts = np.arange(0, n, period)
    block_high = np.maximum.reduceat(high, starts)
    block_low = np.minimum.reduceat(low, starts)
    block_kind = dict(find_swings(block_high, block_low))
    valid = [(i, kind) for i, kind in regular if block_kind.get(i // period) == kind]
    return _collapse(valid, high, low)


def mother_candle_mask(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """True for a bar whose next bar sits inside it (next High lower and next Low higher)."""
    mother = np.zeros(len(high), dtype=bool)
    if len(high) > 1:
        mother[:-1] = inside_bar_mask(high, low)[1:]
    return mother
