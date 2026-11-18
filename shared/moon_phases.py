"""New moon and full moon database.

Computed with Astronomy Engine (the same library and the same
SearchMoonQuarter / NextMoonQuarter search the Astronomy tab uses), so the
dates here match the calculator.

Dates are given in WIB (UTC+7), the time zone the rest of Stargazer uses
for IDX data. The database is saved to db/moon_phases.csv the first time it
is needed and read from there afterwards.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd

DB_DIR = Path(__file__).resolve().parent.parent / "db"
DB_PATH = DB_DIR / "moon_phases.csv"
# Which sectors each zodiac sign of the Moon boosts. Edit the CSV to change it.
SECTORS_PATH = DB_DIR / "moon_sign_sectors.csv"
SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
         "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
START_YEAR = 1990
END_YEAR = 2050          # exclusive
TZ_OFFSET_HOURS = 7      # WIB
PHASE_NEW = "NEW"
PHASE_FULL = "FULL"
EMOJI = {PHASE_NEW: "🌑", PHASE_FULL: "🌕"}
COLUMNS = ["Phase", "UTC", "Local", "Date", "Moon_Lon", "Sign"]


def sign_of(lon: float) -> str:
    """Tropical zodiac sign for an ecliptic longitude in degrees."""
    return SIGNS[int((lon % 360) // 30)]


def load_sign_sectors(path: Path = SECTORS_PATH) -> dict[str, str]:
    """{"Aries": "automobile, infrastructure, ...", ...}"""
    df = pd.read_csv(path)
    return dict(zip(df["Sign"].str.strip(), df["Sectors"].str.strip()))


def build_moon_db(start_year: int = START_YEAR, end_year: int = END_YEAR) -> pd.DataFrame:
    """Every new and full moon from 1 Jan `start_year` to before `end_year`."""
    import astronomy

    rows = []
    q = astronomy.SearchMoonQuarter(astronomy.Time.Make(start_year, 1, 1, 0, 0, 0))
    while q.time.Utc().year < end_year:
        if q.quarter in (0, 2):  # 0 = new moon, 2 = full moon
            utc = q.time.Utc().replace(microsecond=0)
            local = utc + timedelta(hours=TZ_OFFSET_HOURS)
            # Moon's tropical ecliptic longitude (true equinox of date), as on the Astronomy tab.
            lon = astronomy.EclipticGeoMoon(q.time).lon % 360
            rows.append({
                "Phase": PHASE_NEW if q.quarter == 0 else PHASE_FULL,
                "UTC": utc.strftime("%Y-%m-%d %H:%M:%S"),
                "Local": local.strftime("%Y-%m-%d %H:%M:%S"),
                "Date": local.strftime("%Y-%m-%d"),
                "Moon_Lon": round(lon, 4),
                "Sign": sign_of(lon),
            })
        q = astronomy.NextMoonQuarter(q)
    return pd.DataFrame(rows, columns=COLUMNS)


def load_moon_db(path: Path = DB_PATH) -> pd.DataFrame:
    """Read the database, building and saving it first if it does not exist."""
    if path.exists():
        db = pd.read_csv(path)
        if list(db.columns) == COLUMNS:
            return db
        # older file without the newer columns: rebuild it
    db = build_moon_db()
    path.parent.mkdir(parents=True, exist_ok=True)
    db.to_csv(path, index=False)
    return db


def nearest_bar_dates(event_dates: list[str], bar_dates: list[str]) -> list[str | None]:
    """Snap each event date to the nearest bar date (ties go to the earlier bar).

    Both lists hold "YYYY-MM-DD" strings; `bar_dates` must be sorted. Events
    before the first bar or after the last bar get None.
    """
    bars = pd.to_datetime(pd.Series(bar_dates)).reset_index(drop=True)
    out: list[str | None] = []
    if bars.empty:
        return [None] * len(event_dates)
    first, last = bars.iloc[0], bars.iloc[-1]
    for ev in pd.to_datetime(pd.Series(event_dates)):
        if ev < first or ev > last:
            out.append(None)
            continue
        i = int(bars.searchsorted(ev))          # first bar >= ev
        if bars.iloc[i] == ev or i == 0:
            out.append(bars.iloc[i].strftime("%Y-%m-%d"))
            continue
        before, after = bars.iloc[i - 1], bars.iloc[i]
        pick = before if (ev - before) <= (after - ev) else after
        out.append(pick.strftime("%Y-%m-%d"))
    return out
