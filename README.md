# Stargazer

Core shared library for swing detection and the feature modules that build on it.
Modules (`modules/*`) are developed in separate discussions; this folder holds only `shared/`.

## Setup
    python -m venv .venv
    source .venv/bin/activate        # Windows: .venv\Scripts\activate
    pip install -r requirements.txt

## Test (offline, no network needed)
    python -m pytest -q

## Live download (run on your machine; needs internet)
    python -c "from shared.data_fetcher import load_daily; print(load_daily('BBRI').tail())"

Data is cached to `data/<TICKER>.csv`. Use `refresh=True` to re-download.

## Detect swings
    from shared.data_fetcher import load_daily
    from shared.swing_detector import detect_swings
    df = load_daily('BBRI')
    print(detect_swings(df))

## Parameters (shared/config.py, all PROPOSED defaults)
- `SWING_LOOKBACK = 2`: bars on each side that must be less/more extreme.
- `MIN_BAR_GAP = 5`: swings closer than this are flagged as sideways.
- Inside bars are never pivots; a bar that is both high and low pivot is skipped.
- Pivots are confirmed `SWING_LOOKBACK` bars later (`Confirmed_Date`). Do not act earlier.

## Chart viewer
    streamlit run app.py

Sidebar **Load Data**: pick a CSV from `data/` or upload one, then click **Load**.
Needs columns Date, Open, High, Low, Close (Volume optional; any letter case; yfinance CSVs work).

## Supporting tools (tabs under the chart)
- `modules/time_geometry/index.html` — Time Geometry Calculator
- `modules/astronomy/index.html` — Nusantara Sky Calculator
Each is a self-contained page; edit the HTML file and reload the app.
