import numpy as np
import pandas as pd
import pytest

from shared.swing_detector import tag_bars
from shared.tg_backtest import CROSS, RATIOS, run_tg_backtest, step_projections


def tagged_from(tags: dict[int, str], n: int) -> pd.DataFrame:
    return pd.DataFrame({"Date": pd.bdate_range("2026-01-05", periods=n),
                         "Tag": [tags.get(i, "") for i in range(n)]})


def by_name(result):
    return {r["variable"]: r for r in result["rows"]}


def points(target, anchor=36, same=(0, 10, 18, 30), prev=30):
    """(interval start, interval end, F, "tepat" or "±1") for every projection that gets a point."""
    p = step_projections(anchor, np.array(same), prev)
    out = set()
    for start, end, r, land in zip(p["start"], p["end"], p["ratio"], p["land"]):
        if land == target:
            out.add((int(start), int(end), RATIOS[r], "tepat"))
        elif abs(land - target) == 1:
            out.add((int(start), int(end), RATIOS[r], "±1"))
    return out


def test_sh5_example():
    # SH1 0, SH2 10, SH3 18, SH4 30, then a swing low at 36 (the anchor). Where does SH5 give points?
    assert points(45) == {(0, 18, 1.5, "tepat"), (0, 30, 0.5, "tepat"), (10, 30, 0.786, "±1"),
                          (18, 30, 1.272, "tepat"), (30, 36, 1.5, "tepat"),
                          (30, 36, 1.272, "±1"), (30, 36, 1.618, "±1")}     # cross: 44 and 46
    assert points(54) == {(0, 18, 2.0, "tepat"), (0, 30, 0.786, "tepat"), (10, 30, 1.272, "±1"),
                          (18, 30, 2.0, "tepat")}
    assert points(42) == {(0, 18, 1.272, "±1"), (10, 30, 0.618, "tepat"), (18, 30, 1.0, "tepat"),
                          (30, 36, 1.0, "tepat"), (30, 36, 0.786, "±1")}    # cross 0.786: 41


def test_counts_by_hand():
    # SH 1, SL 3, SH 5, SL 7, SH 9. Only one step has 2 same-type swings:
    # anchor SL 7, target SH 9, interval SH 1 -> SH 5 (d=4, from bar 5) and cross SH 5 -> SL 7 (d=2, from bar 7).
    res = run_tg_backtest(tagged_from({1: "SH", 3: "SL", 5: "SH", 7: "SL", 9: "SH"}, 11))
    # same-type lands 7,7,8,9,10,11,11,13,14,15; cross lands 8,8,9,9,10,10,10,11,11,12
    tol = res["tolerance"]
    assert (tol["exact_hits"], tol["exact_dates"]) == (3, 18)     # bar 9: F 1, cross F 0.786 and F 1
    assert (tol["near_hits"], tol["near_dates"]) == (7, 35)       # bar 8 or 10
    assert tol["on"] is True                                      # 7/35 = 0.2 per date > 3/18
    rows = by_name(res)
    assert [rows[f"F {f:g}"]["weight"] for f in RATIOS] == [0.5, 0.5, 1, 1, 1, 0.5, 0.5, 0, 0, 0]
    assert (rows["F 1"]["hits"], rows["F 1"]["projections"]) == (2, 2)
    assert (rows["Faktor silang"]["hits"], rows["Faktor silang"]["projections"]) == (7, 10)
    assert rows["Faktor silang"]["weight"] == 1.0                 # 0.7 vs 0.3 for same-type, capped at 1
    assert res["setting"] == {"ratios": {f"{f:g}": rows[f"F {f:g}"]["weight"] for f in RATIOS},
                              "tolOn": True, "cross": 1.0}


def regular_cycles(seed: int = 0, blocks: int = 60) -> pd.DataFrame:
    """Swing highs repeat the same cycle length a few times before it changes;
    each swing low sits at a random bar between two swing highs."""
    rng = np.random.default_rng(seed)
    tags, sh = {}, 5
    tags[sh] = "SH"
    for _ in range(blocks):
        period = int(rng.integers(8, 25))
        for _ in range(4):
            tags[int(rng.integers(sh + 2, sh + period - 1))] = "SL"
            sh += period
            tags[sh] = "SH"
    return tagged_from(tags, sh + 5)


def test_repeating_cycles_find_the_cycle_ratios_exact():
    # the next swing high comes one cycle later: F 1 on one-cycle intervals and F 0.5 on two-cycle intervals
    res = run_tg_backtest(regular_cycles())
    weights = {r["variable"]: r["weight"] for r in res["rows"][:len(RATIOS)]}
    assert sorted(weights, key=weights.get)[-2:] in (["F 1", "F 0.5"], ["F 0.5", "F 1"])
    assert res["tolerance"]["on"] is False        # the exact date is right far more often than the dates beside it


def test_weights_in_range_with_three_decimals():
    rng = np.random.default_rng(5)
    c = 100 + np.cumsum(rng.normal(0, 1, 1500))
    df = pd.DataFrame({"Date": pd.bdate_range("2020-01-01", periods=1500),
                       "High": c + rng.uniform(0, 1, 1500), "Low": c - rng.uniform(0, 1, 1500)})
    res = run_tg_backtest(tag_bars(df))
    assert [r["variable"] for r in res["rows"]] == [f"F {f:g}" for f in RATIOS] + ["Faktor silang"]
    for r in res["rows"]:
        assert 0 <= r["weight"] <= 1
        assert round(r["weight"], 3) == r["weight"]
    assert max(r["weight"] for r in res["rows"][:len(RATIOS)]) == 1.0
    assert set(res["setting"]) == {"ratios", "tolOn", "cross"}


def test_cross_interval_is_last():
    p = step_projections(36, np.array([0, 10, 18, 30]), 30)
    assert set(p["source"][-len(RATIOS):]) == {CROSS}
    assert (p["start"][-1], p["end"][-1]) == (30, 36)
    assert len(p["land"]) == (6 + 1) * len(RATIOS)              # 6 pairs of 4 swings + cross


def test_too_few_swings():
    with pytest.raises(ValueError):
        run_tg_backtest(tagged_from({1: "SH", 3: "SL"}, 5))
