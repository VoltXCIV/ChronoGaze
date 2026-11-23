"""Sun in Sign: which zodiac sign the Sun is in, bar by bar.

The sign boundaries are the moments the Sun actually enters each sign (its
tropical ecliptic longitude crosses a multiple of 30 degrees), computed with
Astronomy Engine and saved to db/sun_ingress.csv the first time they are
needed. The industries each sign boosts, and its element, come from the
"Sun in Sign" sheet of Tag DB.xlsx, so editing that sheet changes the chart.
"""
from __future__ import annotations

import math
from datetime import timedelta
from pathlib import Path

import pandas as pd

from shared.moon_phases import SIGNS, TZ_OFFSET_HOURS, sign_of
from shared.tag_db import TAG_DB_PATH, clean as _clean, column as _column

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "db" / "sun_ingress.csv"
TAG_SHEET = "Sun in Sign"
START_YEAR = 1970
END_YEAR = 2051          # exclusive
COLUMNS = ["Sign", "UTC", "Local"]

SYMBOLS = dict(zip(SIGNS, "♈♉♊♋♌♍♎♏♐♑♒♓"))
# Standard elements, used only when the sheet leaves a sign's element empty.
ELEMENTS = {s: e for e, signs in {
    "Fire": ["Aries", "Leo", "Sagittarius"],
    "Earth": ["Taurus", "Virgo", "Capricorn"],
    "Air": ["Gemini", "Libra", "Aquarius"],
    "Water": ["Cancer", "Scorpio", "Pisces"],
}.items() for s in signs}


def build_sun_ingress_db(start_year: int = START_YEAR, end_year: int = END_YEAR) -> pd.DataFrame:
    """Every moment the Sun enters a sign, from 1 Jan `start_year` to before `end_year`."""
    import astronomy

    t = astronomy.Time.Make(start_year, 1, 1, 0, 0, 0)
    target = (math.floor(astronomy.SunPosition(t).elon / 30) + 1) * 30 % 360
    rows = []
    while True:
        hit = astronomy.SearchSunLongitude(target, t, 40)
        utc = hit.Utc().replace(microsecond=0)
        if utc.year >= end_year:
            break
        local = utc + timedelta(hours=TZ_OFFSET_HOURS)
        rows.append({"Sign": sign_of(target + 1),
                     "UTC": utc.strftime("%Y-%m-%d %H:%M:%S"),
                     "Local": local.strftime("%Y-%m-%d %H:%M:%S")})
        t = hit.AddDays(1)
        target = (target + 30) % 360
    return pd.DataFrame(rows, columns=COLUMNS)


def load_sun_ingress_db(path: Path = DB_PATH) -> pd.DataFrame:
    """Read the ingress database, building and saving it first if needed."""
    if path.exists():
        db = pd.read_csv(path)
        if list(db.columns) == COLUMNS:
            return db
    db = build_sun_ingress_db()
    path.parent.mkdir(parents=True, exist_ok=True)
    db.to_csv(path, index=False)
    return db


def load_sun_sign_tags(path: Path = TAG_DB_PATH) -> dict[str, dict]:
    """{"Aries": {"element": "Fire", "bias": "Infrastruktur; ...", "winners": "..."}, ...}

    Read from the "Sun in Sign" sheet. Signs missing from the sheet (or a
    missing file) still get their standard element and empty tags.
    """
    out = {s: {"element": ELEMENTS[s], "bias": "", "winners": ""} for s in SIGNS}
    if not Path(path).exists():
        return out
    df = pd.read_excel(path, sheet_name=TAG_SHEET)
    sign_col = _column(df, "zodiac") or _column(df, "sign")
    bias_col = _column(df, "bias")
    win_col = _column(df, "winners")
    el_col = _column(df, "element")
    if sign_col is None:
        return out
    for _, row in df.iterrows():
        sign = _clean(row[sign_col]).title()
        if sign not in out:
            continue
        if el_col and _clean(row[el_col]):
            out[sign]["element"] = _clean(row[el_col]).title()
        if bias_col:
            out[sign]["bias"] = _clean(row[bias_col])
        if win_col:
            out[sign]["winners"] = _clean(row[win_col])
    return out


def sun_sign_segments(bar_times: list[pd.Timestamp], ingress: pd.DataFrame) -> list[dict]:
    """Group consecutive bars by the Sun's sign.

    `bar_times` are WIB wall-clock times in chart order; a bar belongs to the
    sign the Sun is in at that time. Returns
    [{"from": first bar index, "to": last bar index, "sign": ..., "start": ingress
      time (WIB), "end": next ingress time (WIB) or ""}, ...].
    Bars before the first ingress in the database are left out.
    """
    local = pd.to_datetime(ingress["Local"]).reset_index(drop=True)
    signs = ingress["Sign"].tolist()
    segs: list[dict] = []
    for i, t in enumerate(bar_times):
        k = int(local.searchsorted(t, side="right")) - 1   # last ingress <= t
        if k < 0:
            continue
        if segs and segs[-1]["_k"] == k:
            segs[-1]["to"] = i
            continue
        segs.append({"from": i, "to": i, "sign": signs[k], "_k": k,
                     "start": local[k].strftime("%Y-%m-%d %H:%M"),
                     "end": local[k + 1].strftime("%Y-%m-%d %H:%M") if k + 1 < len(local) else ""})
    for s in segs:
        del s["_k"]
    return segs
