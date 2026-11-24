"""Astro backtest: how often a swing high/low forms around astronomical events.

Events (all from the cached ephemeris, times converted to WIB):
  * every pair of Sun, Moon, Mercury ... Pluto at a major aspect
    (conjunction 0, sextile 60, square 90, trine 120, opposition 180);
    e.g. "Sun Square Mars". Waxing and waning aspects count as one event.
  * Moon phases: New Moon, First Quarter, Full Moon, Last Quarter.
  * Mercury / Venus station retrograde and station direct.

For each occurrence, a swing "happens at the event" when a swing bar lies
within +/- `window` calendar days of the event's WIB date (the nearest one is
used; on a tie the earlier). Occurrences whose window holds no trading bar,
or reaches outside the bars where swing status is known (2nd bar .. 2nd-to-
last bar), are left out. The move recorded for a swing high is High -> Low of
the next swing low; for a swing low, Low -> High of the next swing high.

The baseline is the same hit rate for every calendar day in the range, i.e.
what pure chance gives; an event is only interesting if it beats it.

Mercury and Venus retrograde periods also get the price change from the
first to the last bar of the period and whether the trend changed in it.
Every run is saved to db/backtest.sqlite.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from shared.ephemeris import BODIES, STEP, load_ephemeris, ut_to_wib
from shared.swing_detector import TAG_SWING_HIGH, TAG_SWING_LOW, swing_moves
from shared.trend import trend_states

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "backtest.sqlite"
ASPECTS = {"Conjunction": 0, "Sextile": 60, "Square": 90, "Trine": 120, "Opposition": 180}
PHASES = {"New Moon": 0, "First Quarter": 90, "Full Moon": 180, "Last Quarter": 270}
RETRO_BODIES = ["Mercury", "Venus"]
KIND_ASPECT, KIND_MOON, KIND_STATION = "Aspek", "Fase bulan", "Stasiun"


# ---------------------------------------------------------------- events
def _crossings(d: np.ndarray, target: float) -> np.ndarray:
    """Fractional indexes where the unwrapped angle `d` passes target (mod 360)."""
    k = np.floor((d - target) / 360.0)
    i = np.nonzero(np.diff(k))[0]
    level = target + 360.0 * np.maximum(k[i], k[i + 1])
    return i + (level - d[i]) / (d[i + 1] - d[i])


def _zero_crossings(v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fractional indexes where v changes sign, and +1 / -1 for up / down."""
    s = np.sign(v)
    i = np.nonzero(s[:-1] * s[1:] < 0)[0]
    frac = i + v[i] / (v[i] - v[i + 1])
    return frac, np.where(v[i + 1] > 0, 1, -1)


def find_events(eph: dict, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """All events between `start` and `end` (WIB dates, inclusive).

    Columns: event, kind, time (WIB datetime64), date (WIB date)."""
    ut = eph["ut"]
    j2000 = np.datetime64("2000-01-01T12:00:00")
    lo = (np.datetime64(start) - np.timedelta64(7, "h") - j2000) / np.timedelta64(1, "D") - 2
    hi = (np.datetime64(end + pd.Timedelta(days=1)) - np.timedelta64(7, "h") - j2000) / np.timedelta64(1, "D") + 2
    sl = slice(max(0, int(np.searchsorted(ut, lo)) - 1), int(np.searchsorted(ut, hi)) + 1)
    u = ut[sl]
    lon = {b: eph[b][sl] for b in BODIES}
    names, kinds, fis = [], [], []

    def add(name, kind, fi):
        names.extend([name] * len(fi)); kinds.extend([kind] * len(fi)); fis.append(fi)

    for a, b in combinations(BODIES, 2):
        d = lon[a] - lon[b]
        for asp, ang in ASPECTS.items():
            targets = [ang] if ang in (0, 180) else [ang, -ang]
            add(f"{a} {asp} {b}", KIND_ASPECT, np.concatenate([_crossings(d, t) for t in targets]))
    elong = lon["Moon"] - lon["Sun"]
    for ph, ang in PHASES.items():
        add(ph, KIND_MOON, _crossings(elong, ang))
    for b in RETRO_BODIES:
        fi, direction = _zero_crossings(np.gradient(lon[b], STEP))
        add(f"{b} station retrograde", KIND_STATION, fi[direction < 0])
        add(f"{b} station direct", KIND_STATION, fi[direction > 0])

    fi = np.concatenate(fis) if fis else np.array([])
    t = ut_to_wib(u[0] + fi * STEP)
    ev = pd.DataFrame({"event": names, "kind": kinds, "time": pd.to_datetime(t)})
    ev["date"] = ev["time"].dt.normalize()
    ev = ev[(ev["date"] >= start) & (ev["date"] <= end)]
    return ev.sort_values("time").reset_index(drop=True)


def retro_periods(eph: dict, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Mercury/Venus retrograde periods that start and end inside [start, end]."""
    ev = find_events(eph, start - pd.Timedelta(days=200), end + pd.Timedelta(days=200))
    rows = []
    for b in RETRO_BODIES:
        st = ev[ev["event"].str.startswith(b + " station")]
        opened = None
        for _, r in st.iterrows():
            if r["event"].endswith("retrograde"):
                opened = r["time"]
            elif opened is not None:
                rows.append({"planet": b, "start": opened, "end": r["time"]})
                opened = None
    df = pd.DataFrame(rows, columns=["planet", "start", "end"])
    df = df[(df["start"].dt.normalize() >= start) & (df["end"].dt.normalize() <= end)]
    return df.sort_values("start").reset_index(drop=True)


NEXT_MIN_PCT = 70.0          # events at or above this swing % get their next date marked
NEXT_HORIZON_DAYS = 3 * 365  # how far ahead to look for the next occurrence


def next_occurrences(eph: dict, events: list[str], after: pd.Timestamp,
                     horizon_days: int = NEXT_HORIZON_DAYS) -> pd.DataFrame:
    """First time each of `events` happens on or after the WIB date `after`.

    Columns: event, kind, time (WIB), date. Events not found within
    `horizon_days` are left out. Sorted by time."""
    after = pd.Timestamp(after).normalize()
    found = find_events(eph, after, after + pd.Timedelta(days=horizon_days))
    found = found[found["event"].isin(set(events))]
    return found.drop_duplicates("event", keep="first").reset_index(drop=True)


# ---------------------------------------------------------------- swings
def _calendar(tagged: pd.DataFrame):
    """Per-calendar-day arrays: has a bar, has a swing (+ the swing record)."""
    dates = tagged["Date"].dt.normalize()
    day0, day1 = dates.iloc[0], dates.iloc[-1]
    days = pd.date_range(day0, day1, freq="D")
    pos = {d: i for i, d in enumerate(days)}
    has_bar = np.zeros(len(days), bool)
    has_bar[[pos[d] for d in dates]] = True
    swing_at: dict[int, dict] = {}
    for m in swing_moves(tagged):
        swing_at[pos[pd.Timestamp(m["date"])]] = m
    return days, pos, has_bar, swing_at


def _nearest_swing(k: int, w: int, swing_at: dict) -> dict | None:
    for off in range(0, w + 1):
        for j in ((k - off, k + off) if off else (k,)):     # earlier first on a tie
            if j in swing_at:
                return swing_at[j]
    return None


def evaluate(tagged: pd.DataFrame, events: pd.DataFrame, window: int) -> tuple[pd.DataFrame, float, int]:
    """Occurrence table (one row per usable event) + baseline hit rate + baseline days."""
    days, pos, has_bar, swing_at = _calendar(tagged)
    dates = tagged["Date"].dt.normalize()
    known_from, known_until = pos[dates.iloc[1]], pos[dates.iloc[-2]]
    w = int(window)

    # baseline: every calendar day whose window is fully known and holds a bar
    swing_mask = np.zeros(len(days), bool)
    swing_mask[list(swing_at)] = True
    kernel = np.ones(2 * w + 1, int)
    bars_in = np.convolve(has_bar.astype(int), kernel, "same")
    swings_in = np.convolve(swing_mask.astype(int), kernel, "same")
    ks = np.arange(len(days))
    usable = (ks - w >= known_from) & (ks + w <= known_until) & (bars_in > 0)
    base_days = int(usable.sum())
    baseline = float((swings_in[usable] > 0).mean()) if base_days else float("nan")

    rows = []
    for e in events.itertuples(index=False):
        k = pos.get(e.date)
        if k is None or k - w < known_from or k + w > known_until or bars_in[k] == 0:
            continue
        m = _nearest_swing(k, w, swing_at)
        rows.append({"event": e.event, "kind": e.kind, "time": e.time,
                     "swing": (m["type"] if m else ""),
                     "swing_date": (m["date"] if m else None),
                     "price": (m["price"] if m else None),
                     "next_date": (m["next_date"] if m else None),
                     "next_price": (m["next_price"] if m else None),
                     "bars": (m["bars"] if m else None),
                     "pct": (m["pct"] if m else None)})
    hits = pd.DataFrame(rows, columns=["event", "kind", "time", "swing", "swing_date", "price",
                                       "next_date", "next_price", "bars", "pct"])
    return hits, baseline, base_days


def summarize(hits: pd.DataFrame, baseline: float, threshold: float, min_samples: int) -> pd.DataFrame:
    """One row per event with sample size, swing %, high/low split and average moves."""
    rows = []
    for (event, kind), g in hits.groupby(["event", "kind"], sort=False):
        n = len(g)
        sh, sl = g[g["swing"] == TAG_SWING_HIGH], g[g["swing"] == TAG_SWING_LOW]
        k = len(sh) + len(sl)
        pct = 100.0 * k / n if n else 0.0
        rows.append({
            "event": event, "kind": kind, "samples": n, "swings": k, "pct_swing": pct,
            "pct_high": 100.0 * len(sh) / k if k else 0.0,
            "pct_low": 100.0 * len(sl) / k if k else 0.0,
            "avg_move_high": sh["pct"].mean() if len(sh) else np.nan,   # SH -> next SL (negative)
            "avg_move_low": sl["pct"].mean() if len(sl) else np.nan,    # SL -> next SH (positive)
            "lift": pct / (100.0 * baseline) if baseline else np.nan,
            "passed": n >= min_samples and pct >= threshold,
        })
    cols = ["event", "kind", "samples", "swings", "pct_swing", "pct_high", "pct_low",
            "avg_move_high", "avg_move_low", "lift", "passed"]
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values(["passed", "pct_swing", "samples"], ascending=[False, False, False]).reset_index(drop=True)


def _compress(states: list[str]) -> list[str]:
    out: list[str] = []
    for s in states:
        if not out or out[-1] != s:
            out.append(s)
    return out


def evaluate_retro(tagged: pd.DataFrame, periods: pd.DataFrame) -> pd.DataFrame:
    """Price change and trend over each retrograde period (first to last bar inside it)."""
    data = tagged.reset_index(drop=True)
    dates = data["Date"].dt.normalize()
    states = trend_states(data)
    rows = []
    for p in periods.itertuples(index=False):
        i0 = int(dates.searchsorted(p.start.normalize()))
        i1 = int(dates.searchsorted(p.end.normalize(), side="right")) - 1
        if i0 >= len(data) or i1 < i0:
            continue
        seg = data.iloc[i0:i1 + 1]
        c0, c1 = float(data.at[i0, "Close"]), float(data.at[i1, "Close"])
        path = _compress(states[i0:i1 + 1])
        rows.append({"planet": p.planet, "start": p.start, "end": p.end,
                     "days": (p.end - p.start).total_seconds() / 86400,
                     "bar_start": dates.iloc[i0], "bar_end": dates.iloc[i1], "bars": i1 - i0 + 1,
                     "close_start": c0, "close_end": c1, "change_pct": (c1 / c0 - 1) * 100,
                     "high": float(seg["High"].max()), "low": float(seg["Low"].min()),
                     "trend_start": states[i0], "trend_end": states[i1],
                     "trend_path": path, "trend_changed": len(path) > 1})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- run + storage
def run_backtest(tagged: pd.DataFrame, start, end, window: int = 1, threshold: float = 60.0,
                 min_samples: int = 10, eph: dict | None = None) -> dict:
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    data = tagged[(tagged["Date"] >= start) & (tagged["Date"] < end + pd.Timedelta(days=1))].reset_index(drop=True)
    if len(data) < 5:
        raise ValueError("rentang tanggal terlalu pendek (butuh minimal 5 bar)")
    eph = eph if eph is not None else load_ephemeris()
    events = find_events(eph, start, end)
    hits, baseline, base_days = evaluate(data, events, window)
    summary = summarize(hits, baseline, threshold, min_samples)
    retro = evaluate_retro(data, retro_periods(eph, start, end))
    meta = {"start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"), "window": int(window),
            "threshold": float(threshold), "min_samples": int(min_samples), "bars": len(data),
            "swings": int(data["Tag"].isin([TAG_SWING_HIGH, TAG_SWING_LOW]).sum()),
            "baseline": baseline, "baseline_days": base_days, "events": len(events),
            "occurrences": len(hits), "event_types": len(summary), "passed": int(summary["passed"].sum())}
    return {"meta": meta, "summary": summary, "hits": hits, "retro": retro}


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, dataset TEXT, market TEXT,
  range_start TEXT, range_end TEXT, window_days INTEGER, threshold REAL, min_samples INTEGER,
  bars INTEGER, swings INTEGER, baseline REAL, meta_json TEXT);
CREATE TABLE IF NOT EXISTS event_stats (
  run_id INTEGER, event TEXT, kind TEXT, samples INTEGER, swings INTEGER, pct_swing REAL,
  pct_high REAL, pct_low REAL, avg_move_high REAL, avg_move_low REAL, lift REAL, passed INTEGER);
CREATE TABLE IF NOT EXISTS event_hits (
  run_id INTEGER, event TEXT, kind TEXT, event_time TEXT, swing TEXT, swing_date TEXT,
  price REAL, next_date TEXT, next_price REAL, bars INTEGER, pct REAL);
CREATE TABLE IF NOT EXISTS retro_periods (
  run_id INTEGER, planet TEXT, start TEXT, "end" TEXT, bars INTEGER, close_start REAL,
  close_end REAL, change_pct REAL, high REAL, low REAL, trend_start TEXT, trend_end TEXT,
  trend_path TEXT, trend_changed INTEGER);
"""


def save_run(result: dict, dataset: str, market: str, path: Path = DB_PATH) -> int:
    """Store a run (settings, every event's stats, every occurrence, retro periods); return its id."""
    m = result["meta"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.executescript(SCHEMA)
        cur = con.execute(
            "INSERT INTO runs (created_at, dataset, market, range_start, range_end, window_days, threshold,"
            " min_samples, bars, swings, baseline, meta_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), dataset, market, m["start"], m["end"], m["window"],
             m["threshold"], m["min_samples"], m["bars"], m["swings"], m["baseline"], json.dumps(m)))
        rid = cur.lastrowid
        s = result["summary"]
        con.executemany("INSERT INTO event_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(rid, r.event, r.kind, int(r.samples), int(r.swings), r.pct_swing, r.pct_high, r.pct_low,
                          _num(r.avg_move_high), _num(r.avg_move_low), _num(r.lift), int(r.passed))
                         for r in s.itertuples(index=False)])
        h = result["hits"]
        con.executemany("INSERT INTO event_hits VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        [(rid, r.event, r.kind, r.time.strftime("%Y-%m-%d %H:%M"), r.swing, r.swing_date,
                          _num(r.price), r.next_date, _num(r.next_price), _int(r.bars), _num(r.pct))
                         for r in h.itertuples(index=False)])
        rt = result["retro"]
        con.executemany("INSERT INTO retro_periods VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(rid, r.planet, r.start.strftime("%Y-%m-%d %H:%M"), r.end.strftime("%Y-%m-%d %H:%M"),
                          int(r.bars), r.close_start, r.close_end, r.change_pct, r.high, r.low, r.trend_start,
                          r.trend_end, " > ".join(x or "-" for x in r.trend_path), int(r.trend_changed))
                         for r in rt.itertuples(index=False)])
    return rid


def _num(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


def _int(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else int(x)
