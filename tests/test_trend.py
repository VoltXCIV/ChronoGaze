import pandas as pd

from shared.trend import DOWN, NONE, SIDEWAYS, UP, trend_states


def frame(points):
    """Bars from (tag, high, low) tuples."""
    return pd.DataFrame({"Date": pd.date_range("2024-01-01", periods=len(points)),
                         "High": [p[1] for p in points], "Low": [p[2] for p in points],
                         "Tag": [p[0] for p in points]})


def test_uptrend_needs_two_higher_highs_and_lows():
    pts = [("SL", 11, 9), ("SH", 21, 19), ("SL", 13, 11), ("SH", 23, 21),
           ("SL", 15, 13), ("SH", 25, 23), ("", 24, 22), ("", 24, 22)]
    st = trend_states(frame(pts))
    # 3rd high (bar 5) is known at bar 6; by then lows 9 < 11 < 13 and highs 21 < 23 < 25
    assert st[5] == NONE and st[6] == UP and st[7] == UP


def test_downtrend():
    pts = [("SH", 31, 29), ("SL", 21, 19), ("SH", 29, 27), ("SL", 19, 17),
           ("SH", 27, 25), ("SL", 17, 15), ("", 18, 16)]
    assert trend_states(frame(pts))[-1] == DOWN


def test_sideways_after_more_than_7_bars():
    # highs 100/101/100.5, lows 90/91: flat within 3 %
    seq = [("SH", 100, 95), ("", 98, 94), ("SL", 96, 90), ("", 97, 92), ("SH", 101, 96),
           ("", 99, 94), ("SL", 97, 91), ("", 98, 93), ("SH", 100.5, 96), ("", 99, 95),
           ("", 99, 95), ("", 99, 95)]
    st = trend_states(frame(seq))
    # band starts at bar 0; needs 2 highs + 2 lows (known at bar 7) and > 7 bars
    assert st[7] == NONE and st[8] == SIDEWAYS and st[-1] == SIDEWAYS


def test_wide_range_is_not_sideways():
    seq = [("SH", 100, 95), ("SL", 96, 80), ("SH", 120, 96), ("SL", 97, 91)] + [("", 99, 95)] * 10
    assert set(trend_states(frame(seq))) == {NONE}


def test_current_trend_reports_state_and_start():
    from shared.trend import current_trend
    pts = [("SL", 11, 9), ("SH", 21, 19), ("SL", 13, 11), ("SH", 23, 21),
           ("SL", 15, 13), ("SH", 25, 23), ("", 24, 22), ("", 24, 22)]
    assert current_trend(frame(pts)) == {"trend": UP, "since": "2024-01-07", "last": "2024-01-08"}
    assert current_trend(frame(pts[:3]))["trend"] == NONE


def test_current_trend_can_count_no_trend_as_sideways():
    from shared.trend import current_trend
    pts = [("SL", 11, 9), ("SH", 21, 19), ("SL", 13, 11)]
    assert current_trend(frame(pts), none_as=SIDEWAYS) == {"trend": SIDEWAYS, "since": "2024-01-01", "last": "2024-01-03"}


def test_stock_trend_uses_denoised_swings():
    import numpy as np
    from shared.swing_detector import denoised_swings
    from shared.trend import current_trend, stock_trend
    rng = np.random.default_rng(1)
    close = 100 + np.cumsum(rng.normal(0.3, 2, 400))
    df = pd.DataFrame({"Date": pd.date_range("2024-01-01", periods=400),
                       "High": close + 1, "Low": close - 1})
    tags = [""] * 400
    for i, k in denoised_swings(df["High"].to_numpy(), df["Low"].to_numpy(), 3):
        tags[i] = k
    expected = current_trend(df.assign(Tag=tags), none_as=SIDEWAYS)
    got = stock_trend(df)
    assert got == expected and got["trend"] in (UP, DOWN, SIDEWAYS)
