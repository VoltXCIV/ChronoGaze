"""Cached geocentric ecliptic longitudes of the Sun, Moon and planets.

Computed once with Astronomy Engine (true equinox of date, the same
GeoVector -> Ecliptic call the Astronomy tab uses) on a half-day grid from
1970 to 2051 and saved to db/ephemeris.npz. Longitudes are unwrapped
(continuous, may exceed 360) so differences and crossings can be found with
plain array maths. Slow bodies are computed on a coarser grid and
interpolated, which is far below a minute of error for daily work.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "ephemeris.npz"
BODIES = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto"]
START_YEAR, END_YEAR = 1970, 2051
STEP = 0.5                                     # days
# Grid step actually computed per body; the rest is interpolated.
COMPUTE_STEP = {"Moon": 0.5, "Pluto": 4.0, "Neptune": 2.0, "Uranus": 2.0}
DEFAULT_COMPUTE_STEP = 1.0


def _lon(body: str, t) -> float:
    import astronomy
    return astronomy.Ecliptic(astronomy.GeoVector(getattr(astronomy.Body, body), t, True)).elon


def build_ephemeris(start_year: int = START_YEAR, end_year: int = END_YEAR, progress=None) -> dict:
    """{"ut": days since J2000 (UT), "<Body>": unwrapped longitude in degrees, ...}"""
    import astronomy
    t0 = astronomy.Time.Make(start_year, 1, 1, 0, 0, 0)
    t1 = astronomy.Time.Make(end_year, 1, 1, 0, 0, 0)
    ut = np.arange(t0.ut, t1.ut + STEP, STEP)
    out = {"ut": ut}
    for k, body in enumerate(BODIES):
        step = COMPUTE_STEP.get(body, DEFAULT_COMPUTE_STEP)
        grid = np.arange(t0.ut, t1.ut + step, step)
        lon = np.array([_lon(body, t0.AddDays(u - t0.ut)) for u in grid])
        out[body] = np.interp(ut, grid, np.unwrap(lon, period=360))
        if progress:
            progress((k + 1) / len(BODIES), body)
    return out


def load_ephemeris(path: Path = DB_PATH, progress=None) -> dict:
    if path.exists():
        with np.load(path) as z:
            if all(b in z for b in BODIES):
                return {k: z[k] for k in z.files}
    eph = build_ephemeris(progress=progress)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **eph)
    return eph


def ut_to_wib(ut: np.ndarray | float):
    """UT days since J2000 -> numpy datetime64 in WIB (UTC+7)."""
    j2000 = np.datetime64("2000-01-01T12:00:00")
    return j2000 + (np.asarray(ut) * 86400e3 + 7 * 3600e3).astype("timedelta64[ms]")
