import pandas as pd

from shared.tag_db import load_moon_sign_tags, load_planet_sign_tags, write_moon_sign_csv


def _book(path):
    with pd.ExcelWriter(path) as w:
        pd.DataFrame({"Sign": ["Aries", "taurus "], "Date": ["", ""],
                      "Tag": ["Otomotif;  Semen ;", "Perbankan"]}).to_excel(w, sheet_name="Moon in Sign", index=False)
        pd.DataFrame({"Planet": ["Sun", "Mercury", "Pluto"],
                      "Sector": ["BUMN; Energi", "Kertas", "Farmasi"],
                      "Commodity": ["Logam", "-", "Emas"],
                      "Sign": ["Leo; Aries", "Virgo", None],
                      "Note": [None, "Saat retrograde: boost emas", None]}).to_excel(w, sheet_name="Planet in Sign", index=False)


def test_moon_sign_tags(tmp_path):
    path = tmp_path / "t.xlsx"; _book(path)
    tags = load_moon_sign_tags(path)
    assert tags == {"Aries": "Otomotif; Semen", "Taurus": "Perbankan"}
    out = tmp_path / "m.csv"
    write_moon_sign_csv(tags, out)
    df = pd.read_csv(out, keep_default_na=False)
    assert df.Sign.tolist()[:3] == ["Aries", "Taurus", "Gemini"] and df.Sectors[2] == ""


def test_planet_sign_tags(tmp_path):
    path = tmp_path / "t.xlsx"; _book(path)
    rules = {r["planet"]: r for r in load_planet_sign_tags(path)}
    assert rules["Sun"] == {"planet": "Sun", "signs": ["Leo", "Aries"], "sector": ["BUMN", "Energi"],
                            "commodity": ["Logam"], "note": ""}
    assert rules["Mercury"]["commodity"] == [] and rules["Mercury"]["note"].startswith("Saat")
    assert rules["Pluto"]["signs"] == []


def test_idx_tags(tmp_path):
    from shared.tag_db import load_idx_tags
    path = tmp_path / "t.xlsx"
    _book(path)
    with pd.ExcelWriter(path, mode="a") as w:
        pd.DataFrame({"kode_emiten": ["aadi", None], "Nama Perusahaan": ["PT Adaro", "x"],
                      "tag": ["Energi; Batu Bara", "Emas"], "planet_terkait": ["Sun", ""]}
                     ).to_excel(w, sheet_name="IDX Tag", index=False)
    assert load_idx_tags(path) == [{"code": "AADI", "name": "PT Adaro", "tags": ["Energi", "Batu Bara"]}]
