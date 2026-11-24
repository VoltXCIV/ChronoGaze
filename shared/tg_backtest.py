"""Backtest of the Time Geometry Calculator's settings on one chart's swings.

The projections are the Calculator's:
  * Same-type intervals: every pair of the last HISTORY swings of one type
    (SH1->SH2, SH1->SH3, ...), d bars apart. d x F, rounded half up, is the
    projected distance, counted from the pair's later swing.
  * Cross interval: from the latest swing of the target's type to the latest
    swing overall (the anchor), projected from the anchor.
  * Only dates after the anchor count. Old and new intervals count the same.

Walk forward from the earliest swing to the latest. At every swing (the anchor)
only swings that had formed by then are used, and the target is the next swing,
which is always of the opposite type. Every projection (one interval x one F)
is checked on its own:
  * it lands on the target bar: a point for its F, with +-1 bar off;
  * it lands one bar before or after the target: a point for its F, with +-1 bar on.
Distances are counted in bars of the data, so holidays and weekends are handled
by the data itself.

The setting found:
  * +-1 bar: on when the dates one bar beside the projections are hit more often
    per date than the projected dates themselves; otherwise the extra dates only
    add dates that are wrong more often.
  * F: points / projections of that F (a point = within +-1 bar when +-1 is on,
    exact when it is off), divided by the best F's, so the best F = 1.
  * Cross factor: the same rate for the cross interval's projections / the rate
    for the same-type intervals' projections, at most 1.
Weights are 0..1, rounded to 3 decimals.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from shared.swing_detector import TAG_SWING_HIGH, TAG_SWING_LOW

RATIOS = (0.5, 0.618, 0.786, 1.0, 1.272, 1.5, 1.618, 2.0, 2.24, 2.618)
HISTORY = 10          # swings per type, as many as the chart sends to the Calculator
SAME, CROSS = 0, 1
_F = np.array(RATIOS)


def _walk_steps(tagged: pd.DataFrame, history: int) -> tuple[list, list]:
    """Swing points and the walk-forward steps.

    A step is (anchor, target, target type, same-type swings so far (last `history`),
    latest swing of the target's type): at the anchor swing, forecast the target,
    which is the next swing.
    """
    tags = tagged["Tag"].to_numpy()
    pts = [(i, t) for i, t in enumerate(tags) if t in (TAG_SWING_HIGH, TAG_SWING_LOW)]
    seen: dict[str, list[int]] = {TAG_SWING_HIGH: [], TAG_SWING_LOW: []}
    steps = []
    for s in range(len(pts) - 1):
        seen[pts[s][1]].append(pts[s][0])
        if s == 0:
            continue
        kind = pts[s + 1][1]
        same = seen[kind][-history:]
        if len(same) >= 2:
            steps.append((pts[s][0], pts[s + 1][0], kind, np.array(same), pts[s - 1][0]))
    if not steps:
        raise ValueError("Swing terlalu sedikit untuk backtest (butuh minimal 2 swing high dan 2 swing low).")
    return pts, steps


def step_projections(anchor: int, same: np.ndarray, prev: int) -> dict[str, np.ndarray]:
    """Every projection of one step, one entry per interval x F: source (SAME or CROSS),
    the interval's first and last swing bar, the ratio index and the projected bar."""
    a, b = np.triu_indices(len(same), 1)
    start = np.append(same[a], prev)
    end = np.append(same[b], anchor)
    source = np.append(np.full(len(a), SAME), CROSS)
    bars = np.floor((end - start)[:, None] * _F[None, :] + 0.5).astype(np.int64)   # like JS Math.round
    n = len(RATIOS)
    return {"source": np.repeat(source, n), "start": np.repeat(start, n), "end": np.repeat(end, n),
            "ratio": np.tile(np.arange(n), len(end)), "land": (end[:, None] + bars).ravel()}


def _rate(hits: float, n: float) -> float:
    return float(hits / n) if n > 0 else 0.0


def run_tg_backtest(tagged: pd.DataFrame, history: int = HISTORY) -> dict:
    """Walk-forward backtest of the Calculator's settings on `tagged` (needs Date and Tag).

    Returns {"meta", "rows" (one per F, then the cross factor: weight, hits, projections, rate),
    "tolerance" (+-1 bar: on, and the hits per date exact vs one bar beside),
    "setting" (the form the Calculator takes: ratios, tolOn, cross)}.
    """
    pts, steps = _walk_steps(tagged, history)
    shape = (2, len(RATIOS))                         # source x ratio
    exact_dates, exact_hits = np.zeros(shape), np.zeros(shape)
    near_dates, near_hits = np.zeros(shape), np.zeros(shape)
    window_projections = np.zeros(shape)             # projections with a date after the anchor within +-1
    for anchor, target, _, same, prev in steps:
        p = step_projections(anchor, same, prev)
        land, at = p["land"], (p["source"], p["ratio"])
        np.add.at(exact_dates, at, (land > anchor).astype(float))
        np.add.at(exact_hits, at, (land == target).astype(float))
        np.add.at(near_dates, at, (land - 1 > anchor).astype(float) + (land + 1 > anchor))
        np.add.at(near_hits, at, (np.abs(land - target) == 1).astype(float))
        np.add.at(window_projections, at, (land + 1 > anchor).astype(float))

    exact_rate = _rate(exact_hits.sum(), exact_dates.sum())
    near_rate = _rate(near_hits.sum(), near_dates.sum())
    tol_on = near_rate > exact_rate
    hits = exact_hits + near_hits if tol_on else exact_hits
    projections = window_projections if tol_on else exact_dates

    f_hits, f_n = hits.sum(axis=0), projections.sum(axis=0)
    f_rate = np.divide(f_hits, f_n, out=np.zeros(len(RATIOS)), where=f_n > 0)
    if f_rate.max() <= 0:
        raise ValueError("Belum ada proyeksi yang kena swing berikutnya; swing terlalu sedikit untuk backtest.")
    weights = f_rate / f_rate.max()
    same_rate = _rate(hits[SAME].sum(), projections[SAME].sum())
    cross_rate = _rate(hits[CROSS].sum(), projections[CROSS].sum())
    cross = min(1.0, cross_rate / same_rate) if same_rate > 0 else float(cross_rate > 0)

    rows = [{"variable": f"F {f:g}", "weight": round(float(w), 3), "hits": int(h), "projections": int(n),
             "rate": float(r)} for f, w, h, n, r in zip(RATIOS, weights, f_hits, f_n, f_rate)]
    rows.append({"variable": "Faktor silang", "weight": round(cross, 3), "hits": int(hits[CROSS].sum()),
                 "projections": int(projections[CROSS].sum()), "rate": cross_rate})
    tolerance = {"on": bool(tol_on),
                 "exact_hits": int(exact_hits.sum()), "exact_dates": int(exact_dates.sum()), "exact_rate": exact_rate,
                 "near_hits": int(near_hits.sum()), "near_dates": int(near_dates.sum()), "near_rate": near_rate}
    setting = {"ratios": {f"{f:g}": round(float(w), 3) for f, w in zip(RATIOS, weights)},
               "tolOn": bool(tol_on), "cross": round(cross, 3)}
    dates = tagged["Date"]
    meta = {"bars": len(tagged), "swings": len(pts), "steps": len(steps), "history": history,
            "first": dates.iloc[0], "last": dates.iloc[-1], "same_rate": same_rate}
    return {"meta": meta, "rows": rows, "tolerance": tolerance, "setting": setting}
