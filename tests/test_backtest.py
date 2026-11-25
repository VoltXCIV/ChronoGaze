import sqlite3

import numpy as np
import pandas as pd

from shared.backtest import (_crossings, evaluate, find_events, retro_periods, run_backtest, save_run,
                             summarize)
from shared.ephemeris import load_ephemeris


def test_crossings_find_each_pass_mod_360():
    d = np.array([350.0, 370.0, 390.0, 700.0, 740.0])      # passes 360 and 720
    fi = _crossings(d, 0)
    assert np.allclose(fi, [0.5, 3.5])
    assert np.allclose(_crossings(d, -60), [2.0 + 270 / 310])   # 660 between 390 and 700


def test_events_match_known_sky():
    eph = load_ephemeris()
    ev = find_events(eph, pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-29"))
    full = ev[ev.event == "Full Moon"].time.iloc[0]
    assert abs(full - pd.Timestamp("2024-01-26 00:54")) < pd.Timedelta(minutes=5)   # WIB
    st = ev[ev.event == "Mercury station direct"].time.iloc[0]
    assert abs(st - pd.Timestamp("2024-01-02 10:08")) < pd.Timedelta(hours=1)
    rp = retro_periods(eph, pd.Timestamp("2026-10-01"), pd.Timestamp("2026-12-31"))
    merc = rp[rp.planet == "Mercury"].iloc[0]
    assert merc.start.strftime("%d/%m/%y") == "24/10/26" and merc.end.strftime("%d/%m/%y") == "13/11/26"


def _tagged():
    dates = pd.bdate_range("2024-01-01", periods=12)          # Mon..Tue, weekends skipped
    tags = ["", "SH", "", "SL", "", "", "SH", "", "SL", "", "SH", ""]
    high = [10, 12, 11, 9, 10, 11, 14, 12, 8, 10, 13, 12]
    low = [h - 2 for h in high]
    return pd.DataFrame({"Date": dates, "Open": high, "High": high, "Low": low, "Close": high, "Tag": tags})


def test_evaluate_window_and_moves():
    t = _tagged()
    ev = pd.DataFrame({"event": ["A", "A", "A", "B"], "kind": ["Aspek"] * 4,
                       "time": pd.to_datetime(["2024-01-03 09:00", "2024-01-06 09:00", "2024-01-15 00:00", "2024-01-12 00:00"])})
    ev["date"] = ev["time"].dt.normalize()
    hits, base, _ = evaluate(t, ev, window=1)
    # 3 Jan (Wed): Tue 2 Jan is SH, Thu 4 Jan is SL -> tie, earlier (SH) wins
    a = hits[hits.event == "A"].reset_index(drop=True)
    assert a.loc[0, "swing"] == "SH" and a.loc[0, "pct"] == (7 - 12) / 12 * 100
    # 6 Jan (Sat): window Fri 5..Sun 7 has a bar (Fri) but no swing
    assert a.loc[1, "swing"] == ""
    # 15 Jan (Mon): window reaches Tue 16, the last bar (swing status unknown): dropped
    assert len(a) == 2
    s = summarize(hits, base, threshold=60, min_samples=2)
    row = s[s.event == "A"].iloc[0]
    assert row.samples == 2 and row.swings == 1 and row.pct_swing == 50 and not row.passed
    assert 0 < base <= 1


def test_run_and_save(tmp_path):
    t = _tagged()
    r = run_backtest(t, "2024-01-01", "2024-01-16", window=1, threshold=60, min_samples=1)
    assert r["meta"]["bars"] == 12 and r["meta"]["occurrences"] > 0
    rid = save_run(r, "TEST", "ihsg", tmp_path / "bt.sqlite")
    with sqlite3.connect(tmp_path / "bt.sqlite") as con:
        assert con.execute("select count(*) from event_stats where run_id=?", (rid,)).fetchone()[0] == len(r["summary"])
        assert con.execute("select dataset from runs").fetchone()[0] == "TEST"


def test_next_occurrences_gives_first_date_after():
    from shared.backtest import next_occurrences
    eph = load_ephemeris()
    nx = next_occurrences(eph, ["Full Moon", "Mercury station direct", "No Such Event"], pd.Timestamp("2024-01-01"))
    assert list(nx.event) == ["Mercury station direct", "Full Moon"]          # sorted by time
    assert nx.date.iloc[0] == pd.Timestamp("2024-01-02")
    assert abs(nx.time.iloc[1] - pd.Timestamp("2024-01-26 00:54")) < pd.Timedelta(minutes=5)


def test_sign_periods_match_known_ingresses():
    from shared.backtest import sign_periods
    eph = load_ephemeris()
    sp = sign_periods(eph, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-12-31"))
    leo = sp[(sp.planet == "Sun") & (sp.sign == "Leo")].iloc[0]
    # Sun enters Leo 23/07/26 02:13 WIB and Virgo 23/08/26 09:19 WIB (Astronomy Engine)
    assert abs(leo.start - pd.Timestamp("2026-07-23 02:13")) < pd.Timedelta(minutes=5)
    assert abs(leo.end - pd.Timestamp("2026-08-23 09:19")) < pd.Timedelta(minutes=5)
    moon = sp[sp.planet == "Moon"]
    assert 150 <= len(moon) <= 170                       # ~13.4 laps x 12 signs a year
    assert (moon.end - moon.start).max() < pd.Timedelta(days=3)
    # consecutive stays of one body touch end to start
    sun = sp[sp.planet == "Sun"].reset_index(drop=True)
    assert (sun.start.iloc[1:].to_numpy() == sun.end.iloc[:-1].to_numpy()).all()


def test_period_change_is_open_to_close():
    from shared.backtest import evaluate_sign_periods
    t = _tagged()
    t["Open"] = t["High"] - 1
    periods = pd.DataFrame({"planet": ["Sun"], "sign": ["Aries"],
                            "start": [pd.Timestamp("2024-01-02 06:00")], "end": [pd.Timestamp("2024-01-04 18:00")]})
    r = evaluate_sign_periods(t, periods, [""] * len(t)).iloc[0]
    # bars 2, 3, 4 Jan (each counted at 12:00 WIB): Open of 2 Jan = 11, Close of 4 Jan = 9
    assert r.bars == 3 and r.open_start == 11 and r.close_end == 9
    assert abs(r.change_pct - (9 / 11 - 1) * 100) < 1e-9
    assert r.swings_high == 1 and r.swings_low == 1


def test_run_includes_signs_and_saves_them(tmp_path):
    t = _tagged()
    r = run_backtest(t, "2024-01-01", "2024-01-16", window=1, threshold=60, min_samples=1)
    assert set(r["sign_summary"].planet) == {"Moon", "Sun", "Mercury", "Venus"}
    assert len(r["sign_summary"]) == 48 and len(r["signs"]) > 0
    rid = save_run(r, "TEST", "ihsg", tmp_path / "bt.sqlite")
    with sqlite3.connect(tmp_path / "bt.sqlite") as con:
        assert con.execute("select count(*) from sign_stats where run_id=?", (rid,)).fetchone()[0] == 48
        assert con.execute("select count(*) from sign_periods where run_id=?", (rid,)).fetchone()[0] == len(r["signs"])
