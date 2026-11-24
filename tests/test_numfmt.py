import pandas as pd

from shared.numfmt import idn, idn_styler


def test_idn_thousands_and_decimals():
    assert idn(1000.5, "{:,.1f}") == "1.000,5"
    assert idn(1234567.891) == "1.234.567,89"
    assert idn(-0.5, "{:+.2f}%") == "-0,50%"
    assert idn(6169, "{:,}") == "6.169"


def test_idn_styler_keeps_numbers():
    df = pd.DataFrame({"Close": [1000.5, None], "Name": ["a", "b"]})
    sty = idn_styler(df, {"Close": "{:,.2f}", "Missing": "{:,}"})
    html = sty.to_html()
    assert "1.000,50" in html and "—" in html
    assert sty.data["Close"].iloc[0] == 1000.5
