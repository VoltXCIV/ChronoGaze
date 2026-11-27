import pandas as pd

from shared.price_update import update_price_file, yahoo_symbol


def yahoo(rows):
    """rows: (date, o, h, l, c, adj_close, volume)"""
    df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "AdjClose", "Volume"])
    df["Date"] = pd.to_datetime(df["Date"])
    return lambda symbol, start: df[df["Date"] >= start].reset_index(drop=True)


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_bytes(text.encode())
    return p


TV = ("time,open,high,low,close,Volume\n"
      "2026-11-19,100,110,90,105,1000\n"
      "2026-11-20,105,112,100,108,2000\n"
      "2026-11-23,108,109,101,102,300")           # last bar was intraday, no trailing newline


def test_symbols():
    assert yahoo_symbol("BBCA") == "BBCA.JK"
    assert yahoo_symbol("IDX_ANTM, 1D") == "ANTM.JK"
    assert yahoo_symbol("IDX_AADI, 1D (Yahoo)") == "AADI.JK"
    assert yahoo_symbol("IDX_COMPOSITE, 1D (5)") == "^JKSE"
    assert yahoo_symbol("IDX_LQ45, 1D") == "^JKLQ45"
    assert yahoo_symbol("CRYPTO_BTCUSD, 1D") == "BTC-USD"
    assert yahoo_symbol("FX_IDC_XAUUSD, 1D (4)") is None


def test_replace_last_and_append(tmp_path):
    p = write(tmp_path, "IDX_TEST, 1D.csv", TV)
    fetch = yahoo([("2026-11-20", 105, 112, 100, 108, 108, 2000),
                   ("2026-11-23", 108, 111, 100, 110, 110, 5000),
                   ("2026-11-24", 110, 115, 109, 114, 114, 4000),
                   ("2026-11-25", 114, 116, 112, 113, 113, 3500)])
    r = update_price_file(p, fetch)
    assert r.status == "updated" and r.replaced and r.added == 2
    assert r.last_before == "2026-11-23" and r.last_after == "2026-11-25"
    lines = p.read_text().splitlines()
    assert lines[:3] == TV.splitlines()[:3]                # older rows untouched
    assert lines[3:] == ["2026-11-23,108,111,100,110,5000",
                         "2026-11-24,110,115,109,114,4000",
                         "2026-11-25,114,116,112,113,3500"]


def test_running_twice_changes_nothing(tmp_path):
    p = write(tmp_path, "IDX_TEST, 1D.csv", TV)
    fetch = yahoo([("2026-11-23", 108, 111, 100, 110, 110, 5000),
                   ("2026-11-24", 110, 115, 109, 114, 114, 4000)])
    update_price_file(p, fetch)
    once = p.read_bytes()
    r = update_price_file(p, fetch)
    assert r.status == "up_to_date" and p.read_bytes() == once


def test_last_bar_kept_when_yahoo_lacks_it(tmp_path):
    p = write(tmp_path, "IDX_TEST, 1D.csv", TV)
    fetch = yahoo([("2026-11-20", 105, 112, 100, 108, 108, 2000),
                   ("2026-11-24", 110, 115, 109, 114, 114, 4000)])
    r = update_price_file(p, fetch)
    assert not r.replaced and r.added == 1
    assert p.read_text().splitlines()[-2:] == ["2026-11-23,108,109,101,102,300",
                                               "2026-11-24,110,115,109,114,4000"]


def test_adjusted_file_uses_adjusted_prices(tmp_path):
    # File holds adjusted prices (Date header). Yahoo raw close 108, adjusted 54 (factor 0.5).
    text = ("Date,Open,High,Low,Close,Volume\n"
            "2026-11-20,52.5000,56.0000,50.0000,54.0000,2000.0000\n")
    p = write(tmp_path, "TEST.csv", text)
    fetch = yahoo([("2026-11-20", 105, 112, 100, 108, 54, 2000),
                   ("2026-11-23", 110, 116, 108, 114, 57, 3000)])
    r = update_price_file(p, fetch)
    assert r.basis == "adjusted" and not r.warnings
    assert p.read_text().splitlines()[-1] == "2026-11-23,55,58,54,57,3000"


def test_raw_file_with_big_gap_warns(tmp_path):
    p = write(tmp_path, "IDX_TEST, 1D.csv", TV)
    fetch = yahoo([("2026-11-23", 54, 55, 50, 51, 51, 5000)])   # file says 102: a split happened
    r = update_price_file(p, fetch)
    assert r.warnings


def test_crlf_and_extra_columns_kept(tmp_path):
    text = ("time,open,high,low,close,Volume,RSI\r\n"
            "2026-11-20,105,112,100,108,2000,55.1\r\n")
    p = write(tmp_path, "IDX_TEST, 1D.csv", text)
    fetch = yahoo([("2026-11-20", 105, 112, 100, 108, 108, 2000),
                   ("2026-11-23", 108, 111.5, 100, 110.25, 110.25, 5000)])
    update_price_file(p, fetch)
    assert p.read_bytes().decode() == ("time,open,high,low,close,Volume,RSI\r\n"
                                       "2026-11-20,105,112,100,108,2000,\r\n"
                                       "2026-11-23,108,111.5,100,110.25,5000,\r\n")


def test_unknown_and_network_failure(tmp_path):
    p = write(tmp_path, "FX_IDC_XAUUSD, 1D.csv", TV)
    assert update_price_file(p, yahoo([])).status == "skipped"
    p2 = write(tmp_path, "IDX_TEST, 1D.csv", TV)

    def boom(symbol, start):
        raise ConnectionError("offline")
    r = update_price_file(p2, boom)
    assert r.status == "error" and p2.read_text() == TV
