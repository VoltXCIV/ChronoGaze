import numpy as np
import pandas as pd

from shared.swing_detector import find_swings, inside_bar_mask, tag_bars


def bars(highs, lows):
    return np.array(highs, dtype=float), np.array(lows, dtype=float)


def test_basic_high_then_low():
    h, l = bars([10, 12, 11, 9, 10], [8, 10, 9, 7, 8])
    assert find_swings(h, l) == [(1, "SH"), (3, "SL")]


def test_equal_highs_at_top_mark_rightmost():
    # bars 1 and 2 share the top high 12 -> the rightmost of them is the swing high
    h, l = bars([10, 12, 12, 9], [8, 9, 9, 8.5])
    assert find_swings(h, l) == [(2, "SH")]


def test_equal_lows_at_bottom_mark_rightmost():
    # the case from the AADI chart: two bars with exactly the same bottom low
    h, l = bars([20, 19, 18, 17, 18, 19], [15, 14, 12, 12, 13, 14])
    assert find_swings(h, l) == [(3, "SL")]


def test_three_equal_highs_mark_rightmost():
    h, l = bars([10, 12, 12, 12, 11], [5, 6, 6, 6, 6])
    assert find_swings(h, l) == [(3, "SH")]


def test_flat_run_that_is_not_a_peak_is_no_swing():
    # equal highs on a staircase up (higher bar after the run) -> not a swing high
    h, l = bars([10, 12, 12, 13, 12], [5, 6, 6, 7, 7])
    assert find_swings(h, l) == [(3, "SH")]
    # a flat run at the very start has no lower bar before it
    h, l = bars([12, 12, 11, 10], [6, 6, 5, 4])
    assert find_swings(h, l) == []


def test_consecutive_highs_keep_highest():
    # candidates: bar1 high 12, bar3 high 15, bar5 high 13; lows never qualify
    h, l = bars([10, 12, 11, 15, 12, 13, 11], [5, 6, 6, 7, 7, 8, 8])
    assert find_swings(h, l) == [(3, "SH")]


def test_consecutive_highs_tie_keeps_newest():
    h, l = bars([10, 12, 11, 12, 11], [5, 6, 6, 7, 7])
    assert find_swings(h, l) == [(3, "SH")]


def test_consecutive_lows_keep_lowest_tie_newest():
    h, l = bars([20, 19, 19, 19, 19, 19, 19], [10, 8, 9, 7, 9, 7, 9])
    assert find_swings(h, l) == [(5, "SL")]


def test_always_alternates():
    rng = np.random.default_rng(0)
    c = 100 + np.cumsum(rng.normal(0, 1, 500))
    h, l = c + rng.uniform(0, 1, 500), c - rng.uniform(0, 1, 500)
    kinds = [k for _, k in find_swings(h, l)]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))


def test_outside_bar_takes_opposite_type():
    # bar1 = swing high; bar3 is both higher-high and lower-low than neighbours
    h, l = bars([10, 12, 11, 13, 11], [8, 9, 9, 7, 8])
    assert find_swings(h, l) == [(1, "SH"), (3, "SL")]


def test_inside_bar_mask_strict():
    h, l = bars([10, 9, 10, 9.5], [5, 6, 5, 5])
    assert inside_bar_mask(h, l).tolist() == [False, True, False, False]


def test_tag_bars_column():
    df = pd.DataFrame({"High": [10, 12, 11, 9, 10], "Low": [8, 10, 10.5, 7, 8]})
    assert tag_bars(df)["Tag"].tolist() == ["", "SH", "IB", "SL", ""]


def test_deterministic():
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(0, 1, 300))
    df = pd.DataFrame({"High": c + 1, "Low": c - 1})
    assert tag_bars(df)["Tag"].equals(tag_bars(df)["Tag"])


def test_swing_moves():
    from shared.swing_detector import swing_moves
    df = pd.DataFrame({
        "Date": pd.bdate_range("2026-01-05", periods=7),
        "High": [10, 12, 11, 9, 10, 13, 12],
        "Low":  [8, 10, 9, 7, 8, 11, 11.5],
    })
    tagged = tag_bars(df)
    assert tagged["Tag"].tolist() == ["", "SH", "", "SL", "", "SH", "IB"]
    m = swing_moves(tagged)
    assert [x["type"] for x in m] == ["SH", "SL", "SH"]
    # swing high 12 (bar 1) -> next swing low 7 (bar 3)
    assert m[0]["price"] == 12 and m[0]["next_price"] == 7 and m[0]["bars"] == 2
    assert m[0]["change"] == -5 and round(m[0]["pct"], 4) == round(-5 / 12 * 100, 4)
    # swing low 7 (bar 3) -> next swing high 13 (bar 5)
    assert m[1]["next_price"] == 13 and m[1]["bars"] == 2 and m[1]["change"] == 6
    # last swing has no next swing yet
    assert m[2]["next_price"] is None and m[2]["bars"] is None
    assert m[0]["date"] == "2026-01-06"


def test_denoised_period_1_equals_regular():
    rng = np.random.default_rng(2)
    c = 100 + np.cumsum(rng.normal(0, 1, 400))
    h, l = c + rng.uniform(0, 1, 400), c - rng.uniform(0, 1, 400)
    from shared.swing_detector import denoised_swings
    assert denoised_swings(h, l, 1) == find_swings(h, l)


def test_denoised_drops_noise_keeps_original_date():
    from shared.swing_detector import denoised_swings
    # regular swings: SH1 SL2 SH3 SL4 SH7 SL10; the small wiggle at bars 1-4 is noise
    h, l = bars([10, 11, 10.5, 11.5, 11, 12, 13, 15, 14, 12, 11, 12, 13],
                [9, 9.5, 9, 10, 9.6, 11, 12, 14, 13, 11, 8, 10, 12])
    regular = find_swings(h, l)
    assert regular == [(1, "SH"), (2, "SL"), (3, "SH"), (4, "SL"), (7, "SH"), (10, "SL")]
    # blocks of 3: [0-2] [3-5] [6-8] [9-11] [12] -> highs 11,12,15,13,13 lows 9,9.6,12,8,12
    # block swings: SH at block 2 (bars 6-8), SL at block 3 (bars 9-11)
    assert denoised_swings(h, l, 3) == [(7, "SH"), (10, "SL")]


def test_denoised_always_alternates_and_is_subset():
    from shared.swing_detector import denoised_swings
    rng = np.random.default_rng(3)
    c = 100 + np.cumsum(rng.normal(0, 1, 600))
    h, l = c + rng.uniform(0, 1, 600), c - rng.uniform(0, 1, 600)
    regular = set(find_swings(h, l))
    for p in (2, 3, 5, 10):
        pts = denoised_swings(h, l, p)
        assert set(pts) <= regular
        kinds = [k for _, k in pts]
        assert all(a != b for a, b in zip(kinds, kinds[1:]))
        assert len(pts) <= len(regular)


def test_mother_candle_mask():
    from shared.swing_detector import mother_candle_mask
    h, l = bars([10, 12, 11, 9, 10], [8, 10, 10.5, 7, 8])
    # bar 2 is inside bar 1 -> bar 1 is the mother candle
    assert mother_candle_mask(h, l).tolist() == [False, True, False, False, False]


def test_denoised_equal_lows_mark_rightmost():
    from shared.swing_detector import denoised_swings
    h, l = bars([20, 19, 18, 17, 18, 19], [15, 14, 12, 12, 13, 14])
    assert denoised_swings(h, l, 1) == [(3, "SL")]
    # blocks of 2: [15,14] [12,12] [13,14] -> block lows 14, 12, 13 -> block 1 is a swing low
    assert denoised_swings(h, l, 2) == [(3, "SL")]
