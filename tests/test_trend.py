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
