"""Small helpers shared across modules."""
from shared.config import IDX_SUFFIX


def normalize_ticker(ticker: str, suffix: str = IDX_SUFFIX) -> str:
    """Return the Yahoo Finance symbol for an IDX ticker.

    "bbri" -> "BBRI.JK", "BBRI.JK" -> "BBRI.JK".
    Non-IDX symbols (e.g. "AAPL") should pass suffix="" explicitly.
    """
    symbol = ticker.strip().upper()
    if suffix and not symbol.endswith(suffix):
        symbol = f"{symbol}{suffix}"
    return symbol


def bare_ticker(ticker: str, suffix: str = IDX_SUFFIX) -> str:
    """Return the ticker without the market suffix: "BBRI.JK" -> "BBRI"."""
    symbol = ticker.strip().upper()
    if suffix and symbol.endswith(suffix):
        return symbol[: -len(suffix)]
    return symbol
