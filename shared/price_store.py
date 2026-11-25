"""Daily prices of many IDX stocks, for reading each stock's current trend.

Saved as db/prices/<CODE>.csv (Date, Open, High, Low, Close, Volume), one file
per stock, separate from data/ so the chart's file list stays short.
Downloaded from Yahoo Finance in batches (<CODE>.JK, adjusted prices).

Run from the project folder to refresh every stock with a liquidity tier:
    .venv\\Scripts\\python -m shared.price_store
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from shared.config import DATA_DIR, IDX_SUFFIX, PROJECT_ROOT

PRICES_DIR = PROJECT_ROOT / "db" / "prices"
START = None                  # None = the whole history Yahoo Finance has (period="max")
BATCH = 50


def _frame(raw: pd.DataFrame) -> pd.DataFrame:
    """One ticker's yfinance columns -> Date, Open, High, Low, Close, Volume (no empty rows)."""
    df = raw.reset_index()
    df = df.rename(columns={df.columns[0]: "Date"})
    keep = ["Date", "Open", "High", "Low", "Close", "Volume"]
    df = df[[c for c in keep if c in df.columns]].dropna(subset=["Open", "High", "Low", "Close"])
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
    return df.sort_values("Date").drop_duplicates("Date").reset_index(drop=True)


def download_prices(codes: list[str], start: str | None = START, out_dir: Path = PRICES_DIR,
                    log=print) -> dict[str, list[str]]:
    """Download and save daily bars for `codes`. Returns {"ok": [...], "failed": [...]}."""
    import yfinance as yf

    out_dir.mkdir(parents=True, exist_ok=True)
    ok, failed = [], []
    for k in range(0, len(codes), BATCH):
        part = codes[k:k + BATCH]
        span = {"start": start} if start else {"period": "max"}
        raw = yf.download([c + IDX_SUFFIX for c in part], **span, interval="1d", auto_adjust=True,
                          group_by="ticker", progress=False, threads=True)
        for code in part:
            sym = code + IDX_SUFFIX
            try:
                df = _frame(raw[sym]) if sym in raw.columns.get_level_values(0) else pd.DataFrame()
            except Exception:
                df = pd.DataFrame()
            if len(df) < 30:
                failed.append(code)
                continue
            df.to_csv(out_dir / f"{code}.csv", index=False, date_format="%Y-%m-%d", float_format="%.4f")
            ok.append(code)
        log(f"{min(k + BATCH, len(codes))}/{len(codes)} diproses · {len(ok)} tersimpan · {len(failed)} gagal")
    return {"ok": ok, "failed": failed}


def price_files(data_dir: Path = DATA_DIR, prices_dir: Path = PRICES_DIR) -> dict[str, Path]:
    """{"AMMN": Path, ...}: a daily price CSV per IDX code. Looked for in `data_dir`
    ("IDX_AMMN, 1D.csv", "IDX_AMMN, 1D (Yahoo).csv" or "AMMN.csv") and in `prices_dir`
    ("AMMN.csv"); when a code has several files the newest one wins."""
    import re
    found = []
    for d in (data_dir, prices_dir):
        for f in d.glob("*.csv") if d.is_dir() else []:
            m = re.match(r"IDX_([A-Z0-9]+), 1D\b", f.stem) or re.fullmatch(r"([A-Z0-9]{2,8})", f.stem)
            if m:
                found.append((m[1], f, f.stat().st_mtime))
    out: dict[str, tuple[Path, float]] = {}
    for code, f, mt in found:
        if code not in out or mt > out[code][1]:
            out[code] = (f, mt)
    return {code: f for code, (f, _) in out.items()}


def trend_of_file(path: Path, data_dir: Path = DATA_DIR) -> dict:
    """Current trend (shared.trend.stock_trend) of one price CSV, plus where the data came from."""
    from shared.csv_loader import load_ohlc_csv
    from shared.trend import stock_trend
    try:
        stem = Path(path).stem
        own = Path(path).parent == data_dir and stem.startswith("IDX_") and "(Yahoo)" not in stem
        src = "data/" if own else "Yahoo Finance"
        return {**stock_trend(load_ohlc_csv(path)), "src": src}
    except Exception:
        return {"trend": "", "since": "", "last": "", "error": True}


def download_full_history(code: str, out_dir: Path) -> Path:
    """Every daily bar Yahoo Finance has for one IDX stock (period="max"), saved as
    `out_dir`/"IDX_<CODE>, 1D (Yahoo).csv" (a chart file next to the user's own CSVs,
    never overwriting them). Also refreshes db/prices/<CODE>.csv. Returns the path."""
    import yfinance as yf

    code = code.strip().upper()
    raw = yf.download(code + IDX_SUFFIX, period="max", interval="1d", auto_adjust=True,
                      progress=False, multi_level_index=False)
    if raw is None or raw.empty:
        raise ValueError(f"Yahoo Finance tidak punya data untuk {code}{IDX_SUFFIX}")
    df = _frame(raw)
    if len(df) < 30:
        raise ValueError(f"data {code} terlalu sedikit ({len(df)} bar)")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"IDX_{code}, 1D (Yahoo).csv"
    df.to_csv(path, index=False, date_format="%Y-%m-%d", float_format="%.4f")
    PRICES_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(PRICES_DIR / f"{code}.csv", index=False, date_format="%Y-%m-%d", float_format="%.4f")
    return path


if __name__ == "__main__":
    from shared.tag_db import load_idx_tags

    codes = [s["code"] for s in load_idx_tags() if s["tier"]]
    res = download_prices(codes)
    print("Gagal:", ", ".join(res["failed"]) or "-")
