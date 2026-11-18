"""Daily OHLC fetching from yfinance with a local CSV cache.

Cache rules:
  * CSV files live in data/ as <BARE_TICKER>.csv (e.g. data/BBRI.csv).
  * If the cache file exists and refresh=False, it is read and not re-downloaded.
  * prices are adjusted (auto_adjust=True) so splits and dividends do not
    create artificial gaps in history. Confirm this default in the installed
    yfinance version (verify with a known IDX corporate action).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from shared.config import DATA_DIR
from shared.utils import bare_ticker, normalize_ticker
from shared.validator import assert_valid_ohlc, REQUIRED_COLUMNS


def cache_path(ticker: str, data_dir: Path = DATA_DIR) -> Path:
    return Path(data_dir) / f"{bare_ticker(ticker)}.csv"


def _clean_download(raw: pd.DataFrame) -> pd.DataFrame:
    """Flatten yfinance output into columns Date, Open, High, Low, Close, Volume."""
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw.reset_index()
    df = df.rename(columns={df.columns[0]: "Date"})
    keep = ["Date", "Open", "High", "Low", "Close", "Volume"]
    df = df[[c for c in keep if c in df.columns]]
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
    return df.sort_values("Date").drop_duplicates("Date").reset_index(drop=True)


def download_daily(ticker: str, start: str, end: str | None = None) -> pd.DataFrame:
    """Download daily bars from yfinance. Does not touch the cache."""
    import yfinance as yf  # imported here so tests do not need network

    symbol = normalize_ticker(ticker)
    raw = yf.download(
        symbol,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=True,
        progress=False,
        multi_level_index=False,
    )
    if raw is None or raw.empty:
        raise ValueError(f"yfinance returned no data for {symbol}")
    return _clean_download(raw)


def load_daily(
    ticker: str,
    start: str = "2016-01-01",
    end: str | None = None,
    refresh: bool = False,
    data_dir: Path = DATA_DIR,
) -> pd.DataFrame:
    """Return daily OHLC for a ticker, using the CSV cache when present."""
    path = cache_path(ticker, data_dir)
    if path.exists() and not refresh:
        df = pd.read_csv(path, parse_dates=["Date"])
    else:
        df = download_daily(ticker, start=start, end=end)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)

    assert_valid_ohlc(df)
    return df[[c for c in REQUIRED_COLUMNS + ["Volume"] if c in df.columns]]
