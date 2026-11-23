import pandas as pd

from shared.sun_signs import build_sun_ingress_db, load_sun_sign_tags, sun_sign_segments


def test_known_2025_ingresses():
    db = build_sun_ingress_db(2025, 2026)
    assert len(db) == 12
    # March equinox 2025: 20 Mar 09:01 UTC; December solstice: 21 Dec 15:03 UTC
    aries = db[db.Sign == "Aries"].iloc[0]
    cap = db[db.Sign == "Capricorn"].iloc[0]
    assert aries.UTC.startswith("2025-03-20 09:0")
    assert cap.UTC.startswith("2025-12-21 15:0")
    assert aries.Local.startswith("2025-03-20 16:0")       # WIB = UTC+7


def test_segments_group_bars_by_sign():
    ingress = pd.DataFrame({"Sign": ["Aries", "Taurus", "Gemini"],
                            "UTC": ["", "", ""],
                            "Local": ["2025-03-20 16:01", "2025-04-20 02:56", "2025-05-21 01:54"]})
    bars = [pd.Timestamp(d) + pd.Timedelta(hours=12) for d in
            ["2025-03-19", "2025-03-20", "2025-04-18", "2025-04-21", "2025-05-22"]]
    segs = sun_sign_segments(bars, ingress)
    # 19 Mar is before the first ingress; 20 Mar 12:00 is still before 16:01
    assert [(s["from"], s["to"], s["sign"]) for s in segs] == [(2, 2, "Aries"), (3, 3, "Taurus"), (4, 4, "Gemini")]
    assert segs[0]["start"] == "2025-03-20 16:01" and segs[0]["end"] == "2025-04-20 02:56"
    assert segs[-1]["end"] == ""


def test_tags_from_sheet(tmp_path):
    path = tmp_path / "tags.xlsx"
    pd.DataFrame({"Zodiac": ["Aries", "Leo"], "Date": ["", ""],
                  "Konversi Tag Standar (Bias & Basket)": ["Infrastruktur; Semen", "Properti"],
                  "Konversi Tag Standar (5Y Winners)": ["Semen", None],
                  "Element": ["Fire", ""]}).to_excel(path, sheet_name="Sun in Sign", index=False)
    tags = load_sun_sign_tags(path)
    assert tags["Aries"] == {"element": "Fire", "bias": "Infrastruktur; Semen", "winners": "Semen"}
    assert tags["Leo"]["winners"] == "" and tags["Leo"]["element"] == "Fire"   # standard fallback
    assert tags["Pisces"] == {"element": "Water", "bias": "", "winners": ""}   # not in sheet
