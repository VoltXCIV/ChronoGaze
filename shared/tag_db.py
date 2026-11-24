"""Readers for Tag DB.xlsx, the user's sector/tag workbook.

Sheets used:
  "Moon in Sign"   Sign | Date | Tag                      -> sectors the Moon boosts per sign
  "Sun in Sign"    (read by shared.sun_signs)
  "Planet in Sign" Planet | Sector | Commodity | Sign | Note -> a planet in one of its
                   listed signs boosts those sectors and commodities

Tags are kept as the sheet writes them: "Tag A; Tag B; ...".
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
TAG_DB_PATH = ROOT_DIR / "Tag DB.xlsx"
MOON_SECTORS_CSV = ROOT_DIR / "db" / "moon_sign_sectors.csv"
MOON_SHEET = "Moon in Sign"
PLANET_SHEET = "Planet in Sign"
SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
         "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]


def column(df: pd.DataFrame, *words: str) -> str | None:
    """First column whose name contains all `words` (case-insensitive)."""
    for c in df.columns:
        if all(w.lower() in str(c).lower() for w in words):
            return c
    return None


def clean(v) -> str:
    """Cell as stripped text; empty cells and a lone "-" become ""."""
    s = "" if pd.isna(v) else str(v).strip()
    return "" if s == "-" else s


def split_tags(s: str) -> list[str]:
    return [t.strip() for t in str(s).split(";") if t.strip()]


def load_moon_sign_tags(path: Path = TAG_DB_PATH) -> dict[str, str]:
    """{"Aries": "Otomotif; Infrastruktur; ...", ...} from the "Moon in Sign" sheet."""
    df = pd.read_excel(path, sheet_name=MOON_SHEET)
    sign_col, tag_col = column(df, "sign"), column(df, "tag")
    out = {}
    for _, row in df.iterrows():
        sign = clean(row[sign_col]).title()
        if sign in SIGNS:
            out[sign] = "; ".join(split_tags(clean(row[tag_col])))
    return out


def write_moon_sign_csv(tags: dict[str, str], path: Path = MOON_SECTORS_CSV) -> None:
    """Save the Moon tags as the database CSV (Sign, Sectors), in zodiac order."""
    rows = [{"Sign": s, "Sectors": tags.get(s, "")} for s in SIGNS]
    pd.DataFrame(rows).to_csv(path, index=False)


def load_planet_sign_tags(path: Path = TAG_DB_PATH) -> list[dict]:
    """[{"planet": "Sun", "signs": ["Leo", "Aries"], "sector": [...], "commodity": [...],
    "note": "..."}, ...] from the "Planet in Sign" sheet. Planets with no sign are kept
    (with signs == []) so the caller can see them, but they never qualify."""
    df = pd.read_excel(path, sheet_name=PLANET_SHEET)
    cols = {k: column(df, k) for k in ("planet", "sector", "commodity", "sign", "note")}
    out = []
    for _, row in df.iterrows():
        get = lambda k: clean(row[cols[k]]) if cols[k] is not None else ""
        planet = get("planet").title()
        if not planet:
            continue
        out.append({"planet": planet,
                    "signs": [s.title() for s in split_tags(get("sign")) if s.title() in SIGNS],
                    "sector": split_tags(get("sector")),
                    "commodity": split_tags(get("commodity")),
                    "note": get("note")})
    return out


IDX_SHEET = "IDX Tag"


def load_idx_tags(path: Path = TAG_DB_PATH) -> list[dict]:
    """[{"code": "AADI", "name": "PT Adaro ...", "tags": ["Energi", ...], "tier": "A"}, ...]
    from the "IDX Tag" sheet, in sheet order. Rows without a code are skipped; "tier" is
    the liquidity tier (A-D), or "" when the sheet leaves it empty."""
    df = pd.read_excel(path, sheet_name=IDX_SHEET)
    code_col = column(df, "kode") or column(df, "code")
    name_col = column(df, "nama") or column(df, "name")
    tag_col = column(df, "tag")
    tier_col = column(df, "tier")
    out = []
    for _, row in df.iterrows():
        code = clean(row[code_col]).upper()
        if code:
            out.append({"code": code, "name": clean(row[name_col]) if name_col else "",
                        "tags": split_tags(clean(row[tag_col])),
                        "tier": clean(row[tier_col]).upper() if tier_col else ""})
    return out
