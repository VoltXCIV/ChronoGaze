"""Shared default settings.

These values are PROPOSALS. Each one is an explicit, named parameter so it
can be changed and its effect measured. Do not hard-code them elsewhere.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Market suffix for Indonesia Stock Exchange tickers on Yahoo Finance.
IDX_SUFFIX = ".JK"

# Swing pivot: a bar is a swing high/low when it is strictly more extreme than
# `SWING_LOOKBACK` bars on each side. A pivot is only confirmable
# `SWING_LOOKBACK` bars after it forms, so live use must not act earlier.
SWING_LOOKBACK = 2

# Minimum bars between consecutive swing points before the pair is flagged
# as sideways (doc section 4: "< 5 bars").
MIN_BAR_GAP = 5
