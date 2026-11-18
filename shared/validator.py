"""Input validation for daily OHLC data.

Every check returns a list of human-readable problems. An empty list means
the data passed. Callers decide whether to stop or to warn.
"""
import pandas as pd

REQUIRED_COLUMNS = ["Date", "Open", "High", "Low", "Close"]


def validate_ohlc(df: pd.DataFrame) -> list[str]:
    problems: list[str] = []

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        # Without the columns the other checks cannot run.
        return [f"missing columns: {', '.join(missing)}"]

    if df.empty:
        return ["no rows"]

    nan_counts = df[REQUIRED_COLUMNS[1:]].isna().sum()
    for col, count in nan_counts.items():
        if count:
            problems.append(f"{col} has {count} NaN value(s)")

    dates = pd.to_datetime(df["Date"])
    if dates.duplicated().any():
        problems.append(f"{dates.duplicated().sum()} duplicate date(s)")
    if not dates.is_monotonic_increasing:
        problems.append("dates are not sorted ascending")

    # Only check bar consistency on rows that have values.
    valid = df.dropna(subset=REQUIRED_COLUMNS[1:])
    bad_range = valid[valid["High"] < valid["Low"]]
    if len(bad_range):
        problems.append(f"{len(bad_range)} bar(s) with High < Low")

    bad_high = valid[valid["High"] < valid[["Open", "Close"]].max(axis=1)]
    if len(bad_high):
        problems.append(f"{len(bad_high)} bar(s) with High below Open/Close")

    bad_low = valid[valid["Low"] > valid[["Open", "Close"]].min(axis=1)]
    if len(bad_low):
        problems.append(f"{len(bad_low)} bar(s) with Low above Open/Close")

    non_positive = valid[(valid[REQUIRED_COLUMNS[1:]] <= 0).any(axis=1)]
    if len(non_positive):
        problems.append(f"{len(non_positive)} bar(s) with non-positive prices")

    return problems


def assert_valid_ohlc(df: pd.DataFrame) -> None:
    """Raise ValueError listing every problem found."""
    problems = validate_ohlc(df)
    if problems:
        raise ValueError("OHLC validation failed: " + "; ".join(problems))
