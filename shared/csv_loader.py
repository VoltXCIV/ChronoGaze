"""Load OHLC price data from a CSV file into a clean, standard DataFrame.

Accepted input:
  * Column names in any letter case: Date (or Datetime / Time / Timestamp),
    Open, High, Low, Close, and optionally Volume.
  * CSVs written by yfinance, including the newer 3-row header layout
    ("Price,Close,..." / "Ticker,BBRI.JK,..." / "Date,,,...").

Output columns: Date (datetime64), Open, High, Low, Close, Volume (float).
Rows are sorted by Date, duplicate dates keep the last row, and rows with a
missing price are dropped. Volume is 0 when the file has none.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import BinaryIO, Union

import pandas as pd

PRICE_COLUMNS = ["Open", "High", "Low", "Close"]
OUTPUT_COLUMNS = ["Date", *PRICE_COLUMNS, "Volume"]
DATE_ALIASES = {"date", "datetime", "time", "timestamp"}

Source = Union[str, Path, BinaryIO, bytes]


def _read_raw(source: Source) -> pd.DataFrame:
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    raw = pd.read_csv(source)

    # yfinance multi-row header: row 0 = "Ticker,...", row 1 = "Date,,,".
    first = str(raw.columns[0]).strip().lower()
    if first == "price" and len(raw) >= 2 and str(raw.iloc[0, 0]).strip().lower() == "ticker":
        raw = raw.iloc[2:].rename(columns={raw.columns[0]: "Date"})
    return raw


def load_ohlc_csv(source: Source) -> pd.DataFrame:
    """Read a CSV file (path, file-like object, or bytes) into standard OHLC.

    Raises:
        ValueError when a date column or any of Open/High/Low/Close is missing,
        or when no usable rows remain.
    """
    raw = _read_raw(source)

    rename = {}
    for col in raw.columns:
        key = str(col).strip().lower()
        if key in DATE_ALIASES and "Date" not in rename.values():
            rename[col] = "Date"
        elif key in {"open", "high", "low", "close", "volume"}:
            rename[col] = key.capitalize()
    df = raw.rename(columns=rename)

    missing = [c for c in ["Date", *PRICE_COLUMNS] if c not in df.columns]
    if missing:
        raise ValueError(
            f"CSV tidak punya kolom: {', '.join(missing)}. "
            f"Kolom yang ada: {', '.join(map(str, raw.columns))}"
        )

    if "Volume" not in df.columns:
        df["Volume"] = 0.0
    df = df[OUTPUT_COLUMNS].copy()

    # Timezone-aware strings (e.g. "2024-01-02 00:00:00+07:00") keep their
    # local wall-clock time; the timezone itself is dropped.
    dates = pd.to_datetime(df["Date"], errors="coerce", utc=False, format="mixed")
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_localize(None)
    df["Date"] = dates
    for col in [*PRICE_COLUMNS, "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Volume"] = df["Volume"].fillna(0.0)

    df = df.dropna(subset=["Date", *PRICE_COLUMNS])
    df = df.sort_values("Date").drop_duplicates("Date", keep="last").reset_index(drop=True)
    if df.empty:
        raise ValueError("CSV tidak berisi baris data yang valid.")
    return df
