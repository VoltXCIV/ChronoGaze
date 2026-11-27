"""Bring a price CSV in data/ up to date from Yahoo Finance.

Rule (run on every Load):
  1. Find the last date D already in the file.
  2. Replace the bar of D with Yahoo's bar for D (the old one may have been
     an unfinished intraday bar).
  3. Append every Yahoo bar after D, up to Yahoo's latest bar.
Older rows are never touched. If Yahoo has no bar for D, the old bar stays.

Price basis: files differ. TradingView exports ("time,open,..." header) hold
prices that are not dividend-adjusted; files saved by shared.price_store
("Date,Open,..." header) hold Yahoo's adjusted prices. Yahoo is asked for raw
bars plus Adj Close, and the basis whose close is closest to the file's close
on the latest shared date is used, so the new rows continue the old ones.

The file is edited as text: only the last line is replaced and new lines are
appended, so the rest of the file stays byte-for-byte the same.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from shared.csv_loader import load_ohlc_csv

OVERLAP_DAYS = 10          # Yahoo is asked from D - OVERLAP_DAYS to compare price basis
WARN_GAP_PCT = 2.0         # warn when the file and Yahoo disagree by more than this on a shared date

# Special file names -> Yahoo symbol. Anything else is tried as an IDX code.
SPECIAL = {"COMPOSITE": "^JKSE", "LQ45": "^JKLQ45"}


@dataclass
class UpdateResult:
    status: str                    # "updated", "up_to_date", "skipped", "error"
    symbol: str | None = None
    message: str = ""
    last_before: str | None = None
    last_after: str | None = None
    added: int = 0
    replaced: bool = False
    basis: str | None = None       # "raw" or "adjusted"
    warnings: list[str] = field(default_factory=list)


def yahoo_symbol(stem: str) -> str | None:
    """File name (without .csv) -> Yahoo Finance symbol, or None when there is no match.

    "BBCA" / "IDX_BBCA, 1D" / "IDX_BBCA, 1D (Yahoo)" -> "BBCA.JK"
    "IDX_COMPOSITE, 1D (5)" -> "^JKSE",  "CRYPTO_BTCUSD, 1D" -> "BTC-USD".
    FX files (e.g. XAUUSD spot) have no matching Yahoo series and return None.
    """
    s = stem.strip().upper()
    m = re.match(r"IDX_([A-Z0-9]+)\b", s)
    if m:
        code = m[1]
        return SPECIAL.get(code, code + ".JK")
    m = re.match(r"CRYPTO_([A-Z0-9]+?)(USDT?|USD)\b", s)
    if m:
        return f"{m[1]}-USD"
    if re.fullmatch(r"[A-Z0-9]{2,8}", s):
        return s + ".JK"
    return None


def fetch_yahoo(symbol: str, start: pd.Timestamp) -> pd.DataFrame:
    """Raw daily bars from `start`: Date, Open, High, Low, Close, AdjClose, Volume."""
    import yfinance as yf

    raw = yf.download(symbol, start=start.strftime("%Y-%m-%d"), interval="1d", auto_adjust=False,
                      progress=False, multi_level_index=False)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "AdjClose", "Volume"])
    df = raw.reset_index().rename(columns={"Adj Close": "AdjClose"})
    df = df.rename(columns={df.columns[0]: "Date"})
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None).dt.normalize()
    if "AdjClose" not in df.columns:
        df["AdjClose"] = df["Close"]
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df.sort_values("Date").drop_duplicates("Date", keep="last").reset_index(drop=True)


def _basis_frame(yh: pd.DataFrame, basis: str) -> pd.DataFrame:
    out = yh[["Date", "Open", "High", "Low", "Close", "Volume"]].copy()
    if basis == "adjusted":
        factor = (yh["AdjClose"] / yh["Close"]).where(yh["Close"] > 0, 1.0)
        for c in ["Open", "High", "Low", "Close"]:
            out[c] = yh[c] * factor
    return out


def choose_basis(old: pd.DataFrame, yh: pd.DataFrame, default: str) -> tuple[str, float | None]:
    """Pick "raw" or "adjusted" by the latest date both have; returns (basis, gap %).

    The file's own last bar is avoided when possible: it is the one being
    replaced, often because it was saved mid-session and is not final."""
    common = sorted(set(old["Date"]) & set(yh["Date"]))
    if not common:
        return default, None
    settled = [d for d in common if d < old["Date"].iloc[-1]]
    d = settled[-1] if settled else common[-1]
    file_close = float(old.loc[old["Date"] == d, "Close"].iloc[-1])
    row = yh.loc[yh["Date"] == d].iloc[-1]
    raw_close = float(row["Close"])
    adj_close = float(row["AdjClose"])
    gaps = {b: abs(v - file_close) / file_close * 100 if file_close else 0.0
            for b, v in (("raw", raw_close), ("adjusted", adj_close))}
    if abs(gaps["raw"] - gaps["adjusted"]) < 1e-9:
        return default, gaps[default]
    best = min(gaps, key=gaps.get)
    return best, gaps[best]


def _fmt(x) -> str:
    if x is None or pd.isna(x):
        return ""
    x = float(x)
    if x.is_integer():
        return str(int(x))
    return f"{x:.6f}".rstrip("0").rstrip(".")


def _date_style(field: str) -> str | None:
    field = field.strip().strip('"')
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", field):
        return "iso"
    if re.fullmatch(r"\d{9,11}", field):
        return "unix"
    return None


def update_price_file(path: Path, fetch: Callable[[str, pd.Timestamp], pd.DataFrame] = fetch_yahoo,
                      symbol: str | None = None) -> UpdateResult:
    """Apply the update rule to one CSV file in place. Never raises; see UpdateResult."""
    path = Path(path)
    sym = symbol or yahoo_symbol(path.stem)
    if sym is None:
        return UpdateResult("skipped", message="tidak ada padanan di Yahoo Finance untuk file ini")
    try:
        old = load_ohlc_csv(path)
    except Exception as exc:
        return UpdateResult("error", sym, f"file tidak bisa dibaca: {exc}")

    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.rstrip("\r\n").splitlines()
    header = [h.strip().lstrip("﻿") for h in lines[0].split(",")]
    style = _date_style(lines[-1].split(",")[0]) if len(lines) > 1 else None
    if style is None:
        return UpdateResult("skipped", sym, "format tanggal di file tidak dikenali (harus YYYY-MM-DD atau unix)")

    last = old["Date"].iloc[-1].normalize()
    first = lines[-1].split(",")[0].strip().strip('"')
    tail_date = pd.Timestamp(first) if style == "iso" else pd.Timestamp(int(first), unit="s")
    if tail_date.normalize() != last:
        return UpdateResult("skipped", sym, "baris terakhir file bukan tanggal terbaru (file tidak urut)")
    res = UpdateResult("up_to_date", sym, last_before=f"{last:%Y-%m-%d}", last_after=f"{last:%Y-%m-%d}")
    try:
        yh = fetch(sym, last - pd.Timedelta(days=OVERLAP_DAYS))
    except Exception as exc:
        res.status, res.message = "error", f"gagal mengambil data Yahoo: {exc}"
        return res
    if yh is None or yh.empty:
        res.status, res.message = "error", f"Yahoo Finance tidak mengembalikan data untuk {sym}"
        return res

    default = "adjusted" if header[0] == "Date" else "raw"
    res.basis, gap = choose_basis(old, yh, default)
    if gap is not None and gap > WARN_GAP_PCT:
        res.warnings.append(
            f"harga di file beda {gap:.1f}% dari Yahoo pada tanggal yang sama; kemungkinan ada "
            "dividen/split sejak file dibuat. Pertimbangkan download ulang penuh.")

    new = _basis_frame(yh, res.basis)
    new = new[new["Date"] >= last].reset_index(drop=True)
    if new.empty:
        res.message = "Yahoo belum punya bar sampai tanggal terakhir file"
        return res

    # Rule step 2: replace the last bar only when Yahoo has that same date.
    replace_last = bool((new["Date"] == last).any())
    keep = lines[:-1] if replace_last else lines

    lower = [h.lower() for h in header]
    def row_line(r) -> str:
        cells = []
        for name in lower:
            if name in ("date", "time", "datetime", "timestamp"):
                cells.append(f"{r.Date:%Y-%m-%d}" if style == "iso" else str(int(r.Date.timestamp())))
            elif name in ("open", "high", "low", "close"):
                cells.append(_fmt(round(getattr(r, name.capitalize()), 6)))
            elif name == "volume":
                cells.append(_fmt(r.Volume))
            else:
                cells.append("")       # indicator columns from TradingView: unknown for new bars
        return ",".join(cells)

    out = keep + [row_line(r) for r in new.itertuples(index=False)]
    end = nl if text.endswith(("\n", "\r")) else ""
    new_text = nl.join(out) + end
    added = int((new["Date"] > last).sum())
    res.replaced, res.added = replace_last, added
    res.last_after = f"{new['Date'].iloc[-1]:%Y-%m-%d}"
    if new_text != text:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
        tmp.replace(path)
        res.status = "updated"
    if res.status == "updated":
        res.message = (f"{added} bar baru sampai {res.last_after}"
                       + (f", bar {res.last_before} diganti data Yahoo" if replace_last else ""))
    else:
        res.message = "sudah paling baru"
    return res
