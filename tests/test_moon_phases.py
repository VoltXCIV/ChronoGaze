from shared.moon_phases import PHASE_FULL, PHASE_NEW, build_moon_db, nearest_bar_dates


def test_known_2024_phases():
    db = build_moon_db(2024, 2025)
    # Jan 2024: new moon 11 Jan 11:57 UTC, full moon 25 Jan 17:54 UTC
    new = db[(db.Phase == PHASE_NEW)].iloc[0]
    full = db[(db.Phase == PHASE_FULL)].iloc[0]
    assert new.UTC.startswith("2024-01-11 11:5")
    assert full.UTC.startswith("2024-01-25 17:5")
    # WIB date can roll over: 25 Jan 17:54 UTC = 26 Jan 00:54 WIB
    assert full.Date == "2024-01-26"
    assert 24 <= len(db) <= 26          # ~12-13 of each per year
    phases = db.Phase.tolist()
    assert all(a != b for a, b in zip(phases, phases[1:]))   # alternate


def test_nearest_bar_dates():
    bars = ["2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"]   # Thu Fri | Mon Tue
    events = ["2024-01-05",   # exact
              "2024-01-06",   # Sat -> Fri (1 day) beats Mon (2 days)
              "2024-01-07",   # Sun -> Mon (1 day)
              "2024-01-01",   # before data
              "2024-01-10"]   # after data
    assert nearest_bar_dates(events, bars) == ["2024-01-05", "2024-01-05", "2024-01-08", None, None]


def test_nearest_tie_goes_earlier():
    assert nearest_bar_dates(["2024-01-03"], ["2024-01-01", "2024-01-05"]) == ["2024-01-01"]


def test_signs_and_sectors():
    from shared.moon_phases import SIGNS, load_sign_sectors, sign_of
    db = build_moon_db(2024, 2025)
    # Jan 2024: new moon ~20° Capricorn, full moon ~5° Leo
    assert db[db.Phase == PHASE_NEW].iloc[0].Sign == "Capricorn"
    assert db[db.Phase == PHASE_FULL].iloc[0].Sign == "Leo"
    assert sign_of(0) == "Aries" and sign_of(359.9) == "Pisces" and sign_of(360) == "Aries"
    sectors = load_sign_sectors()
    assert set(sectors) == set(SIGNS)
    assert sectors["Taurus"] == "Perbankan; Investasi; Asuransi"
