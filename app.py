"""ChronoGaze chart viewer.

Run:  streamlit run app.py

Sidebar "Load Data" menu picks a CSV (from the data/ folder or an upload)
and shows it as an interactive candlestick chart drawn with TradingView's
open-source Lightweight Charts library.
"""
import json
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from shared.backtest import (DB_PATH as BACKTEST_DB, NEXT_MIN_PCT, SIGN_BODIES, SIGNS, next_occurrences,
                             run_backtest, save_run)
from shared.csv_loader import load_ohlc_csv
from shared.ephemeris import DB_PATH as EPHEMERIS_DB, load_ephemeris
from shared.market_holidays import load_ihsg_holidays, trades_on_weekends
from shared.numfmt import idn, idn_styler
from shared.moon_phases import EMOJI, load_moon_db, load_sign_sectors, nearest_bar_dates
from shared.tag_db import load_idx_tags, load_moon_sign_tags, load_planet_sign_tags
from shared.tg_backtest import RATIOS as TG_RATIOS, run_tg_backtest
from shared.sun_signs import SYMBOLS as SUN_SYMBOLS, TAG_DB_PATH, load_sun_ingress_db, load_sun_sign_tags, sun_sign_segments
from shared.price_store import PRICES_DIR, download_full_history, price_files, trend_of_file
from shared.trend_api import start_trend_api
from shared.trend import stock_trend
from shared.swing_detector import (TAG_SWING_HIGH, TAG_SWING_LOW, denoised_swings, mother_candle_mask,
                                   swing_moves, tag_bars)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / "cache"
# Supporting tools, each a self-contained HTML page shown in its own tab.
TOOLS = [
    ("⏳ Time Geometry", ROOT / "modules" / "time_geometry" / "index.html"),
    ("🔭 Astronomy", ROOT / "modules" / "astronomy" / "index.html"),
]
TOOL_HEIGHT = 1100
TIME_GEOMETRY_PAGE = TOOLS[0][1]
ASTRONOMY_PAGE = TOOLS[1][1]
# Small scripts added to the Astronomy page (the page file itself is unchanged).
ASTRO_PATCH_DATES = (ASTRONOMY_PAGE.parent / "patch_dates.js").read_text(encoding="utf-8")
ASTRO_PATCH_MOON_SECTORS = (ASTRONOMY_PAGE.parent / "patch_moon_sectors.js").read_text(encoding="utf-8")
ASTRO_PATCH_RETROGRADE = (ASTRONOMY_PAGE.parent / "patch_retrograde.js").read_text(encoding="utf-8")
ASTRO_PATCH_ASPECT_CALENDAR = (ASTRONOMY_PAGE.parent / "patch_aspect_calendar.js").read_text(encoding="utf-8")
# Seeker: call the two pickers "Planet A" / "Planet B" instead of "Point A" / "Point B".
SEEKER_LABELS_JS = ("<script>[['skA','Planet A'],['skB','Planet B']].forEach(([id,t])=>{"
                    "const l=document.querySelector('label[for='+id+']');if(l)l.textContent=t;});</script>")

# The Astronomy page is shown once per sub-tab, each time trimmed by CSS to one job.
# The calculations still run in full; only what is displayed changes.
_ASTRO_COMMON_CSS = """
[hidden] { display:none !important; }  /* the artifact wrapper used to supply this */
.side, footer { display:none !important; }
.shell { grid-template-columns:1fr !important; }
"""
ASTRO_VIEWS = [
    ("📅 Aspect Calendar", "calendar", 1100, _ASTRO_COMMON_CSS + """
#page-calculator, #page-seeker { display:none !important; }
"""),
    ("🔍 Aspect Seeker", "seeker", 900, _ASTRO_COMMON_CSS),
    ("℞ Retrograde", "retrograde", 900, _ASTRO_COMMON_CSS + """
#page-calculator, #page-seeker { display:none !important; }
"""),
    ("📊 Backtest", "backtest", 0, ""),   # native Streamlit, see render_backtest()
    ("🧮 Calculator", "calculator", 1100, _ASTRO_COMMON_CSS + """
#page-calculator > header, .hero,
section.panel:has(#planets), section.panel:has(#timeInfo) { display:none !important; }
.grid2 { grid-template-columns:1fr !important; }
/* natal chart: keep only the Aspects table (and the minor-aspects toggle) */
#horo > .sec-head, #horo .field:has(#hsys), #transitBtn, #horo .horo-grid,
#horo > div:has(#placements), #transitWrap, #horoNote { display:none !important; }
#horo::before { content:"Aspects"; font-family:var(--serif); font-size:26px; line-height:1.15; }
/* order: moon phases, upcoming events, input, aspects */
#page-calculator > .grid2 { order:1; }
#page-calculator > section.panel:has(#events) { order:2; }
#page-calculator > #ctl { order:3; position:static; }
#page-calculator > #horo { order:4; }
"""),
]


# Seeker: extra column telling whether a swing formed within ±1 calendar day of
# each exact aspect date, and the move from that swing to the next one.
# __SWINGS__ is replaced by the JSON from seeker_swing_payload() (or null).
SEEKER_SWING_JS = r"""
<style>
.sg-hi{color:#c99400;font-weight:700}.sg-lo{color:#2196f3;font-weight:700}
.sg-none{color:var(--muted)}td.sg-col{font-family:var(--sans);white-space:nowrap}
</style>
<script>
(function(){
const SG = __SWINGS__;
const MON = {Jan:0,Feb:1,Mar:2,Apr:3,May:4,Jun:5,Jul:6,Aug:7,Sep:8,Oct:9,Nov:10,Dec:11};
const MNAME = Object.keys(MON);
const tbl = document.getElementById('seekResults');
const iso = (y,m,d) => new Date(Date.UTC(y,m,d)).toISOString().slice(0,10);
const num = (x,dg) => x.toLocaleString('id-ID',{maximumFractionDigits:dg});
const short = s => { const p=s.split('-'); return +p[2]+' '+MNAME[+p[1]-1]; };
function describe(e){
  const hi = e.type==='SH';
  const head = `<span class="${hi?'sg-hi':'sg-lo'}">${hi?'^':'v'}</span> ${short(e.date)}`;
  if(e.next_price==null) return head+` · <span class="sg-none">swing ${hi?'low':'high'} berikutnya belum terbentuk</span>`;
  const sign = e.change>=0?'+':'−';
  return head+` <b>${sign}${num(Math.abs(e.pct),2)}%</b> (${sign}${num(Math.abs(e.change),2)}) · ${e.bars} bar`;
}
function cellFor(y,m,d){
  if(!SG) return '<span class="sg-none">No Data</span>';
  const lo = iso(y,m,d-1), hi = iso(y,m,d+1);
  const hits = SG.moves.filter(e => e.date>=lo && e.date<=hi);
  if(hits.length) return hits.map(describe).join('<br>');
  const covered = lo>=SG.first && hi<=SG.known_until;
  return `<span class="sg-none">${covered?'No Effect':'No Data'}</span>`;
}
function decorate(){
  const head = tbl.querySelector('thead tr');
  if(!head || head.querySelector('.sg-col')) return;
  // placed right after Date and Time so it is visible without scrolling sideways
  head.cells[1].insertAdjacentHTML('afterend',
    `<th class="l sg-col">Swing ±1 hari${SG?' · '+SG.name:''}</th>`);
  tbl.querySelectorAll('tbody tr').forEach(tr => {
    if(tr.cells.length < 2) return;   // "no aspect found" message row
    const m = tr.cells[0].textContent.match(/(\d{1,2}) ([A-Z][a-z]{2}) (\d{4})/);
    const html = m && (m[2] in MON) ? cellFor(+m[3], MON[m[2]], +m[1]) : '—';
    tr.cells[1].insertAdjacentHTML('afterend', `<td class="l sg-col">${html}</td>`);
  });
  // column order: ... Swing | Planet A | Aspect | Planet B ... (the page puts Aspect first)
  tbl.querySelectorAll('tr').forEach(tr => {
    if(tr.cells.length > 4) tr.insertBefore(tr.cells[4], tr.cells[3]);
  });
}
new MutationObserver(decorate).observe(tbl, {childList:true});
decorate();
})();
</script>
"""


def seeker_swing_payload() -> dict | None:
    """Swing moves of the loaded data, or None when nothing is loaded."""
    if "df" not in st.session_state:
        return None
    df = st.session_state["df"]
    if len(df) < 3:
        return None
    dates = df["Date"].dt.strftime("%Y-%m-%d")
    # The first and last bar can never be swings (a neighbour is missing),
    # so swing status is only known from the 2nd bar to the 2nd-to-last bar.
    return {"name": st.session_state["name"], "first": dates.iloc[1],
            "known_until": dates.iloc[-2], "moves": swing_moves(df)}


def tag_db_mtime() -> float:
    return TAG_DB_PATH.stat().st_mtime if TAG_DB_PATH.exists() else 0.0


@st.cache_data
def moon_sign_tags(mtime: float) -> dict[str, str]:
    """Moon sign -> sectors, from the "Moon in Sign" sheet of Tag DB.xlsx
    (db/moon_sign_sectors.csv when the workbook is missing). `mtime` reloads an edited file."""
    return load_moon_sign_tags() if mtime else load_sign_sectors()


@st.cache_data
def planet_sign_tags(mtime: float) -> list[dict]:
    """Rules from the "Planet in Sign" sheet of Tag DB.xlsx (none if the workbook is missing)."""
    return load_planet_sign_tags() if mtime else []


@st.cache_data
def idx_tags(mtime: float) -> list[dict]:
    """IDX stocks with a liquidity tier, and their tags, from the "IDX Tag" sheet of
    Tag DB.xlsx. Stocks the sheet gives no tier are left out of the web page."""
    return [s for s in load_idx_tags() if s["tier"]] if mtime else []


@st.cache_data
def _stock_trend(path: str, mtime: float) -> dict:
    return trend_of_file(Path(path), DATA_DIR)


def stock_trends() -> dict[str, dict]:
    """Current trend (shared.trend rules) per IDX code that has a daily price CSV
    (data/ or db/prices/, see shared.price_store.price_files)."""
    return {code: _stock_trend(str(f), f.stat().st_mtime) for code, f in price_files(DATA_DIR, PRICES_DIR).items()}


@st.cache_resource
def trend_api_port() -> int:
    """Local service the Aspect Calendar asks on hover for a stock with no price data yet."""
    return start_trend_api()


def astronomy_view(html: str, page: str, css: str) -> str:
    """Add view CSS and the view's scripts; `page` is calendar, seeker, retrograde or calculator."""
    extra = f"<script>{ASTRO_PATCH_DATES}</script>"
    if page == "seeker":
        data = json.dumps(seeker_swing_payload()).replace("</", "<\\/")
        extra += SEEKER_SWING_JS.replace("__SWINGS__", data) + SEEKER_LABELS_JS
    elif page == "retrograde":
        extra += f"<script>{ASTRO_PATCH_RETROGRADE}</script>"
    elif page == "calendar":
        rules = json.dumps(planet_sign_tags(tag_db_mtime())).replace("</", "<\\/")
        stocks = json.dumps(idx_tags(tag_db_mtime())).replace("</", "<\\/")
        trends = json.dumps(stock_trends()).replace("</", "<\\/")
        extra += f"<script>window.CHRONOGAZE_PLANET_SIGNS={rules};window.CHRONOGAZE_IDX={stocks};window.CHRONOGAZE_TRENDS={trends};window.CHRONOGAZE_TREND_API='http://127.0.0.1:{trend_api_port()}';{ASTRO_PATCH_ASPECT_CALENDAR}</script>"
    else:
        sectors = json.dumps(moon_sign_tags(tag_db_mtime())).replace("</", "<\\/")
        extra += f"<script>window.CHRONOGAZE_SECTORS={sectors};{ASTRO_PATCH_MOON_SECTORS}</script>"
    if page in ("retrograde", "calendar"):   # own page, built by the patch; nothing to switch to
        return html.replace("<style>", f"<style>{css}</style>\n<style>", 1) + extra
    open_page = (f"<script>document.querySelector('.navbtn[data-page=\"{page}\"]').click();"
                 + ("document.getElementById('skGo').click();" if page == "seeker" else "")
                 + "window.scrollTo(0,0);</script>")
    return html.replace("<style>", f"<style>{css}</style>\n<style>", 1) + extra + open_page
# Number of most recent swing highs (and, separately, swing lows) sent to Time Geometry.
TG_LAST_N = 10
# Time Geometry has two calendars: IHSG skips BEI holidays, Global does not.
MARKETS = {"ihsg": "IHSG", "global": "Global"}


def load_buttons() -> str | None:
    """Two load buttons; return the market of the one clicked, else None."""
    if st.button("🇮🇩 Load Saham IHSG", type="primary", use_container_width=True,
                 help="Emiten BEI. Time Geometry memakai kalender IHSG (libur BEI dilewati)."):
        return "ihsg"
    if st.button("🌐 Load Komoditas Global", use_container_width=True,
                 help="Emas, forex, crypto, saham luar. Time Geometry memakai aturan Global."):
        return "global"
    return None


# Denoised Swing: the user picks how many candles are merged into one, 1..DENOISE_MAX.
# Every choice is computed up front so the chart can switch without a rerun.
DENOISE_MAX = 30


def swing_sets(df: pd.DataFrame) -> dict[int, list[tuple[int, str]]]:
    """Denoised swings for every period; period 1 is the regular Swing indicator."""
    high = df["High"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    return {p: denoised_swings(high, low, p) for p in range(1, DENOISE_MAX + 1)}


def time_geometry_payload(df: pd.DataFrame, name: str, market: str, last_n: int) -> dict:
    """Most recent `last_n` swing highs and lows as DD-MM-YY strings, per swing
    indicator: "sets"["1"] is the regular Swing, "sets"["N"] Denoised Swing with N candles.
    The Time Geometry page picks the set of the indicator switched on in the chart.
    "weekend": the data trades on Saturdays and Sundays (crypto); the Global calendar
    then counts every day, otherwise it skips weekends."""
    dates = df["Date"].dt.strftime("%d-%m-%y").tolist()

    def last(points, tag):
        return [dates[i] for i, k in points if k == tag][-last_n:]

    sets = {str(p): {"high": last(pts, TAG_SWING_HIGH), "low": last(pts, TAG_SWING_LOW)}
            for p, pts in swing_sets(df).items()}
    return {"name": f"{name} · chart", "market": market, "weekend": trades_on_weekends(df["Date"]),
            **sets["1"], "sets": sets}


def inject_before_first_script(html: str, payload: dict, name: str = "CHRONOGAZE_SWINGS") -> str:
    """Define window.<name> before the page's own script runs."""
    data = json.dumps(payload).replace("</", "<\\/")
    return html.replace("<script>", f"<script>window.{name}={data};</script>\n<script>", 1)
LWC_URL = "https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"
CHART_HEIGHT = 640
CHART_PAGE = ROOT / "modules" / "chart" / "chart.html"

st.set_page_config(page_title="ChronoGaze Chart", layout="wide")


def to_chart_records(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """Convert OHLC rows to Lightweight Charts candle + volume records."""
    daily = (df["Date"].dt.normalize() == df["Date"]).all()
    if daily:
        times = df["Date"].dt.strftime("%Y-%m-%d").tolist()
    else:
        # Intraday: wall-clock time as UTC seconds so the axis shows local time.
        times = df["Date"].astype("datetime64[s]").astype("int64").tolist()

    candles, volumes = [], []
    for t, o, h, l, c, v in zip(times, df["Open"], df["High"], df["Low"], df["Close"], df["Volume"]):
        candles.append({"time": t, "open": float(o), "high": float(h), "low": float(l), "close": float(c)})
        volumes.append({
            "time": t,
            "value": float(v),
            "color": "rgba(38,166,154,0.5)" if c >= o else "rgba(239,83,80,0.5)",
        })

    return candles, volumes


# How far past today (or past the last bar, if later) the chart extends so
# upcoming new/full moons are visible.
MOON_FUTURE_DAYS = 90


def is_daily(df: pd.DataFrame) -> bool:
    return bool((df["Date"].dt.normalize() == df["Date"]).all())


def future_bar_dates(df: pd.DataFrame) -> list[str]:
    """Empty bars after daily data, so future moons and signs have somewhere to sit.

    Data with weekend bars (crypto) gets weekend bars in the future too.
    """
    last = df["Date"].iloc[-1]
    end = max(pd.Timestamp.today().normalize(), last) + pd.Timedelta(days=MOON_FUTURE_DAYS)
    has_weekends = (df["Date"].dt.dayofweek >= 5).any()
    future = pd.date_range(last + pd.Timedelta(days=1), end, freq="D" if has_weekends else "B")
    return future.strftime("%Y-%m-%d").tolist()


@st.cache_data
def sun_ingress_db() -> pd.DataFrame:
    return load_sun_ingress_db()


@st.cache_data
def sun_sign_tags(mtime: float) -> dict:
    """Tags per sign from Tag DB.xlsx; `mtime` makes an edited file reload."""
    return load_sun_sign_tags(TAG_DB_PATH)


def sun_sign_records(df: pd.DataFrame) -> tuple[list[dict], dict]:
    """Sun in Sign segments over the chart's bars (incl. empty future bars) + info per sign.

    Segment "from"/"to" are bar indexes on the chart's time axis. A daily bar
    belongs to the sign the Sun is in at 12:00 WIB that day.
    """
    if is_daily(df):
        dates = df["Date"].tolist() + [pd.Timestamp(d) for d in future_bar_dates(df)]
        times = [d + pd.Timedelta(hours=12) for d in dates]
    else:
        times = df["Date"].tolist()
    segs = sun_sign_segments(times, sun_ingress_db())
    mtime = TAG_DB_PATH.stat().st_mtime if TAG_DB_PATH.exists() else 0.0
    info = {sign: dict(v, symbol=SUN_SYMBOLS[sign]) for sign, v in sun_sign_tags(mtime).items()}
    return segs, info


@st.cache_data
def moon_db() -> pd.DataFrame:
    return load_moon_db()


def moon_records(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """Moon series points (incl. empty future bars) and their emoji markers.

    Each new/full moon is drawn on its own date, or on the nearest bar that
    exists: a trading day for past dates, an empty future bar after the data.
    Daily data only.
    """
    if not is_daily(df):
        return [], []
    bar_dates = df["Date"].dt.strftime("%Y-%m-%d").tolist()
    future_dates = future_bar_dates(df)

    db = moon_db()
    db = db[(db["Date"] >= bar_dates[0]) & (db["Date"] <= future_dates[-1] if future_dates else True)]
    snapped = nearest_bar_dates(db["Date"].tolist(), bar_dates + future_dates)

    moon_at = {}
    for (_, row), at in zip(db.iterrows(), snapped):
        if at is not None:
            moon_at[at] = row
    series = [{"time": d, "value": 0} for d in bar_dates if d in moon_at]
    series += [{"time": d, "value": 0} if d in moon_at else {"time": d} for d in future_dates]
    markers = [{"time": d, "position": "inBar", "color": "#d1d4dc", "shape": "circle", "size": 0,
                "text": EMOJI[moon_at[d]["Phase"]],
                "id": f"{moon_at[d]['Phase']}|{moon_at[d]['Local']}"}
               for d in sorted(moon_at)]
    return series, markers


def backtest_next_marks(name: str) -> list[dict]:
    """Next dates of the strong events of this data's last backtest, for the chart:
    [{"date": "YYYY-MM-DD", "time": "HH:MM", "event": ..., "pct": 94.7}, ...]."""
    bt = st.session_state.get("backtest")
    if not bt or bt["name"] != name or bt.get("next") is None:
        return []
    return [{"date": r.date.strftime("%Y-%m-%d"), "time": r.time.strftime("%H:%M"),
             "event": r.event, "pct": round(float(r.pct_swing), 1)} for r in bt["next"].itertuples()]


def strong_event_dates(summary: pd.DataFrame, min_samples: int) -> pd.DataFrame:
    """Next occurrence (from today, WIB) of every event with swing % >= NEXT_MIN_PCT
    and at least `min_samples` samples. Columns of next_occurrences + the event's stats."""
    strong = summary[(summary["pct_swing"] >= NEXT_MIN_PCT) & (summary["samples"] >= min_samples)]
    if strong.empty:
        return pd.DataFrame(columns=["event", "kind", "time", "date", "pct_swing", "samples", "pct_high", "pct_low"])
    today = (pd.Timestamp.utcnow().tz_localize(None) + pd.Timedelta(hours=7)).normalize()
    nxt = next_occurrences(ephemeris(), strong["event"].tolist(), today)
    return nxt.merge(strong[["event", "pct_swing", "samples", "pct_high", "pct_low"]], on="event")


def render_chart(df: pd.DataFrame, title: str) -> None:
    candles, volumes = to_chart_records(df)
    # Swing indicators: bar indexes per period (1 = regular Swing), drawn by the page.
    swings = {str(p): [[i, k] for i, k in pts] for p, pts in swing_sets(df).items()}
    mother = mother_candle_mask(df["High"].to_numpy(dtype=float), df["Low"].to_numpy(dtype=float))
    moon_series, moon_markers = moon_records(df)
    sun_segs, sun_info = sun_sign_records(df)
    payload = json.dumps(
        {"candles": candles, "volumes": volumes, "title": title,
         "swings": swings, "mother": mother.nonzero()[0].tolist(), "denoiseMax": DENOISE_MAX,
         "moonSeries": moon_series, "moonMarkers": moon_markers,
         "sunSegs": sun_segs, "sunInfo": sun_info, "btNext": backtest_next_marks(title)}
    ).replace("</", "<\\/")
    html = (CHART_PAGE.read_text(encoding="utf-8")
            .replace("__PAYLOAD__", payload)
            .replace("__HEIGHT__", str(CHART_HEIGHT))
            .replace("__LWC_URL__", LWC_URL))
    components.html(html, height=CHART_HEIGHT + 4)



# ---------------------------------------------------------------- backtest
TREND_LABEL = {"": "Tanpa trend"}


@st.cache_resource
def ephemeris() -> dict:
    return load_ephemeris()


def _dmy(x, time: bool = False) -> str:
    if x is None or x is pd.NaT or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return pd.Timestamp(x).strftime("%d/%m/%y %H:%M" if time else "%d/%m/%y")


def render_backtest() -> None:
    """Backtest tab: swing hit rate around planet aspects, moon phases and stations."""
    st.markdown("#### Backtest astro × swing")
    if "df" not in st.session_state:
        st.info("Load data dulu lewat **📂 Load Data** di sidebar. Backtest memakai data chart yang sedang ditampilkan.")
        return
    df, name = st.session_state["df"], st.session_state["name"]
    if not is_daily(df):
        st.warning("Backtest hanya bisa untuk data harian.")
        return
    first, last = df["Date"].iloc[0].date(), df["Date"].iloc[-1].date()
    with st.form(f"bt_form_{name}"):
        c = st.columns([1.2, 1.2, 1, 1, 1])
        start = c[0].date_input("Tanggal mulai", value=first, min_value=first, max_value=last, format="DD/MM/YYYY")
        end = c[1].date_input("Tanggal akhir", value=last, min_value=first, max_value=last, format="DD/MM/YYYY")
        window = c[2].number_input("Jendela swing (± hari)", min_value=0, max_value=10, value=1, step=1,
                                   help="Swing dihitung terjadi saat event bila ada swing dalam ± hari kalender ini.")
        threshold = c[3].number_input("Filter % swing minimal", min_value=0, max_value=100, value=60, step=5)
        min_samples = c[4].number_input("Sampel minimal", min_value=1, max_value=1000, value=10, step=1,
                                        help="Event yang terjadi lebih sedikit dari ini tidak lolos filter.")
        go = st.form_submit_button("▶ Backtest", type="primary")
    # a click on an Emiten in the Aspect Calendar loads that stock and runs the backtest once
    if st.session_state.pop("bt_autorun", False):
        go = True
    if go:
        if end <= start:
            st.error("Tanggal akhir harus setelah tanggal mulai.")
            return
        first_time = not EPHEMERIS_DB.exists()
        with st.spinner("Membangun database posisi planet (sekali saja, ±1 menit)…" if first_time
                        else "Menjalankan backtest…"):
            try:
                result = run_backtest(df, start, end, window, threshold, min_samples, eph=ephemeris())
                run_id = save_run(result, name, st.session_state["market"])
                nxt = strong_event_dates(result["summary"], min_samples)
            except Exception as exc:
                st.error(f"Backtest gagal: {exc}")
                return
        st.session_state["backtest"] = {"name": name, "result": result, "run_id": run_id, "next": nxt}
        st.rerun()   # so the chart above draws the next event dates
    bt = st.session_state.get("backtest")
    if not bt or bt["name"] != name:
        st.caption("Atur rentang dan filter, lalu tekan **Backtest**. Hasil setiap run otomatis disimpan "
                   f"di `{BACKTEST_DB.relative_to(ROOT).as_posix()}`.")
        return
    show_backtest_report(bt["result"], bt["run_id"], name)
    show_next_events(bt.get("next"), bt["result"]["meta"])


def show_next_events(nxt: pd.DataFrame | None, meta: dict) -> None:
    """Table of the next dates of the events with swing % >= NEXT_MIN_PCT (also marked on the chart)."""
    st.markdown(f"**Tanggal kejadian berikutnya** · event dengan swing ≥ {NEXT_MIN_PCT:g}% "
                f"dan ≥ {meta['min_samples']} sampel, ditandai ◆ di chart")
    if nxt is None:
        st.caption("Jalankan backtest lagi untuk menghitung tanggal kejadian berikutnya.")
        return
    if nxt.empty:
        st.info(f"Tidak ada event dengan swing ≥ {NEXT_MIN_PCT:g}% pada run ini.")
        return
    today = (pd.Timestamp.utcnow().tz_localize(None) + pd.Timedelta(hours=7)).normalize()
    st.dataframe(pd.DataFrame({
        "Tanggal (WIB)": [_dmy(t, True) for t in nxt["time"]],
        "Hari lagi": [(d - today).days for d in nxt["date"]],
        "Event": nxt["event"], "Jenis": nxt["kind"],
        "% Swing": [idn(x, "{:.1f}%") for x in nxt["pct_swing"]],
        "% High / % Low": [f"{idn(h, '{:.0f}')} / {idn(l, '{:.0f}')}" for h, l in zip(nxt["pct_high"], nxt["pct_low"])],
        "Sampel": nxt["samples"]}), hide_index=True, use_container_width=True)
    st.caption(f"Dicari sampai {3} tahun ke depan. Chart hanya punya bar kosong ±{MOON_FUTURE_DAYS} hari ke depan, "
               "jadi tanggal yang lebih jauh hanya ada di tabel ini.")


def _pct_col(label: str, fmt: str = "%.1f%%", help: str | None = None):
    return st.column_config.NumberColumn(label, format=fmt, help=help)


# Event table columns: (DataFrame column, header lines, number format, tooltip).
# A custom HTML table so long headers can wrap onto two lines and the table stays slim.
EVENT_COLUMNS = [
    ("Event", ["Event"], None, None),
    ("Jenis", ["Jenis"], None, None),
    ("Sampel", ["Sampel"], "{:,.0f}", "Berapa kali event ini terjadi dan diuji."),
    ("Swing", ["Swing"], "{:,.0f}", "Berapa kejadian yang punya swing dalam jendela."),
    ("% Swing", ["%", "Swing"], "{:.1f}%", None),
    ("% High", ["%", "High"], "{:.1f}%", "Porsi swing high di antara swing yang terjadi."),
    ("% Low", ["%", "Low"], "{:.1f}%", "Porsi swing low di antara swing yang terjadi."),
    ("Rata² SH → SL", ["Rata²", "SH → SL"], "{:+.2f}%", "Rata-rata perubahan dari High swing high ke Low swing low berikutnya."),
    ("Rata² SL → SH", ["Rata²", "SL → SH"], "{:+.2f}%", "Rata-rata perubahan dari Low swing low ke High swing high berikutnya."),
    ("Lift", ["Lift"], "{:.2f}×", "% Swing dibanding peluang swing pada hari biasa. Di atas 1 = lebih sering dari kebetulan."),
    ("Lolos", ["Lolos"], None, None),
]


def event_table(view: pd.DataFrame, max_height: int = 420) -> None:
    """Sortable event table with two-line headers (click a header to sort)."""
    from html import escape
    cols = [c for c in EVENT_COLUMNS if c[0] in view.columns]
    head = "".join(
        f'<th data-i="{i}" class="{"num" if fmt else "txt"}"'
        f'{f" title={chr(34)}{escape(tip)}{chr(34)}" if tip else ""}>{"<br>".join(escape(x) for x in lines)}'
        f'<span class="ar"></span></th>'
        for i, (_, lines, fmt, tip) in enumerate(cols))
    body = []
    for _, row in view.iterrows():
        cells = []
        for key, _, fmt, _ in cols:
            v = row[key]
            if isinstance(v, (bool,)) or key == "Lolos":
                cells.append(f'<td class="ok" data-v="{int(bool(v))}">{"✓" if v else ""}</td>')
            elif fmt:
                missing = v is None or pd.isna(v)
                cls = "num" + (" neg" if not missing and key.startswith("Rata") and v < 0 else
                               " pos" if not missing and key.startswith("Rata") and v > 0 else "")
                cells.append(f'<td class="{cls}" data-v="{"" if missing else float(v)}">'
                             f'{"—" if missing else idn(v, fmt)}</td>')
            else:
                cells.append(f'<td data-v="{escape(str(v))}">{escape(str(v))}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    height = min(max_height, 62 + 33 * len(view))
    html = f"""<style>
    :root{{--bg:#0E1117;--head:#1A1D26;--line:rgba(250,250,250,.10);--ink:#FAFAFA;--muted:rgba(250,250,250,.6);
           --hover:rgba(250,250,250,.05);--pos:#5FD38D;--neg:#FF7B7B;--accent:#FF4B4B}}
    html,body{{margin:0;background:var(--bg);color:var(--ink);font:14px "Source Sans Pro","Source Sans 3",system-ui,sans-serif}}
    .wrap{{height:{height - 2}px;overflow:auto;border:1px solid var(--line);border-radius:8px}}
    table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
    th{{position:sticky;top:0;background:var(--head);color:var(--muted);font-weight:600;font-size:13px;line-height:1.2;
        padding:7px 8px;border-bottom:1px solid var(--line);cursor:pointer;user-select:none;vertical-align:bottom;white-space:nowrap}}
    th:hover{{color:var(--ink)}}
    th.txt{{text-align:left}} th.num{{text-align:right}}
    th .ar{{font-size:10px;margin-left:3px;color:var(--accent)}}
    td{{padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}}
    td.num{{text-align:right}} td.ok{{text-align:center;color:var(--pos)}}
    td.pos{{color:var(--pos)}} td.neg{{color:var(--neg)}}
    tr:hover td{{background:var(--hover)}}
    </style>
    <div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>
    <script>
    const tb=document.querySelector('tbody'), ths=[...document.querySelectorAll('th')];
    let col=-1, dir=1;
    ths.forEach(th=>th.addEventListener('click',()=>{{
      const i=+th.dataset.i; dir = col===i ? -dir : (th.classList.contains('num') ? -1 : 1); col=i;
      const key=tr=>tr.children[i].dataset.v, num=th.classList.contains('num')||i===ths.length-1;
      [...tb.rows].sort((a,b)=>{{
        const x=key(a), y=key(b);
        if(x==='') return 1; if(y==='') return -1;      // empty values always last
        return (num ? (+x - +y) : x.localeCompare(y)) * dir;
      }}).forEach(r=>tb.appendChild(r));
      ths.forEach(t=>t.querySelector('.ar').textContent='');
      th.querySelector('.ar').textContent = dir>0 ? '▲' : '▼';
    }}));
    </script>"""
    components.html(html, height=height)


def show_backtest_report(result: dict, run_id: int, name: str) -> None:
    m, summary, hits, retro = result["meta"], result["summary"], result["hits"], result["retro"]
    st.divider()
    st.markdown(f"##### Laporan backtest · {name}")
    st.caption(f"Run #{run_id} · {_dmy(m['start'])} – {_dmy(m['end'])} · {idn(m['bars'], '{:,}')} bar · {idn(m['swings'], '{:,}')} swing · "
               f"jendela ±{m['window']} hari · filter ≥{m['threshold']:g}% swing dan ≥{m['min_samples']} sampel · "
               f"tersimpan di `{BACKTEST_DB.relative_to(ROOT).as_posix()}`")
    k = st.columns(3)
    k[0].metric("Jenis Event Astrology Diuji", idn(m['event_types'], "{:,}"))
    k[1].metric("Event Diuji", idn(m['occurrences'], "{:,}"))
    k[2].metric("Lolos filter", idn(m['passed'], "{:,}"))

    tabs = st.tabs(["🔭 Aspek & fase", "℞ Retrograde"] + [f"{SIGN_TAB_ICON[b]} {b} in Sign" for b in SIGN_BODIES])
    with tabs[0]:
        show_event_section(summary, hits, run_id)
    with tabs[1]:
        show_retro_section(retro)
    for tab, body in zip(tabs[2:], SIGN_BODIES):
        with tab:
            show_sign_section(result, body, run_id)


SIGN_TAB_ICON = {"Moon": "☽", "Sun": "☉", "Mercury": "☿", "Venus": "♀"}
SIGN_SYMBOL = dict(zip(SIGNS, "♈♉♊♋♌♍♎♏♐♑♒♓"))
TREND_NOTE = ("Trend: Uptrend = 2× Higher High dan 2× Higher Low berturut-turut; Downtrend = 2× Lower High dan "
              "2× Lower Low; Sideways = swing high dan swing low masing-masing dalam rentang ≤3% selama lebih "
              "dari 7 bar. Trend di suatu bar hanya memakai swing yang sudah terbentuk sebelum bar itu.")


def show_event_section(summary: pd.DataFrame, hits: pd.DataFrame, run_id: int) -> None:
    st.markdown("**Event dengan swing ≥ filter** · aspek planet, fase bulan, stasiun Mercury/Venus")
    show_all = st.toggle("Tampilkan semua event (termasuk yang tidak lolos)", key=f"bt_all_{run_id}")
    table = summary if show_all else summary[summary["passed"]]
    if table.empty:
        st.info("Tidak ada event yang lolos filter. Coba turunkan filter % swing atau sampel minimal.")
        return
    view = pd.DataFrame({
        "Event": table["event"], "Jenis": table["kind"], "Sampel": table["samples"],
        "Swing": table["swings"], "% Swing": table["pct_swing"], "% High": table["pct_high"],
        "% Low": table["pct_low"], "Rata² SH → SL": table["avg_move_high"],
        "Rata² SL → SH": table["avg_move_low"], "Lift": table["lift"], "Lolos": table["passed"]})
    event_table(view)
    st.download_button("⬇ Download CSV", view.to_csv(index=False).encode("utf-8"),
                       file_name=f"backtest_{run_id}_events.csv", mime="text/csv", key=f"bt_csv_{run_id}")
    st.caption("% High / % Low = porsi swing high / swing low di antara swing yang terjadi. "
               "SH → SL = perubahan dari High swing high ke Low swing low berikutnya; "
               "SL → SH = dari Low swing low ke High swing high berikutnya.")
    pick = st.selectbox("Rincian kejadian untuk event", table["event"].tolist(), key=f"bt_pick_{run_id}")
    show_occurrences(hits[hits["event"] == pick])


def show_occurrences(occ: pd.DataFrame) -> None:
    sw_label = {TAG_SWING_HIGH: "^ Swing high", TAG_SWING_LOW: "v Swing low", "": "—"}
    # text columns so a missing value reads "—" instead of "None"
    num = lambda x, fmt="{:,.2f}": "—" if x is None or pd.isna(x) else idn(x, fmt)
    st.dataframe(pd.DataFrame({
        "Waktu event (WIB)": [_dmy(t, True) for t in occ["time"]],
        "Swing": occ["swing"].map(sw_label),
        "Tanggal swing": [_dmy(x) for x in occ["swing_date"]],
        "Harga swing": [num(x) for x in occ["price"]],
        "Swing berikutnya": [_dmy(x) for x in occ["next_date"]],
        "Harga berikutnya": [num(x) for x in occ["next_price"]],
        "Perubahan": [num(x, "{:+.2f}%") for x in occ["pct"]],
        "Bar": [num(x, "{:.0f}") for x in occ["bars"]]}).iloc[::-1],
        hide_index=True, use_container_width=True)
    st.caption(f"{len(occ)} kejadian diuji, {int((occ['swing'] != '').sum())} dengan swing. "
               "Kejadian tanpa swing tetap dihitung sebagai sampel.")


def _open_col(df: pd.DataFrame) -> pd.Series:
    # runs saved before the switch to Open -> Close only have close_start
    return df["open_start"] if "open_start" in df.columns else df["close_start"]


def show_retro_section(retro: pd.DataFrame) -> None:
    st.markdown("**Periode retrograde Mercury & Venus** · perubahan = Open bar pertama → Close bar terakhir")
    if retro.empty:
        st.info("Tidak ada periode retrograde yang utuh di dalam rentang ini.")
        return
    if "open_start" not in retro.columns:
        st.warning("Hasil ini dari run lama (Close → Close). Tekan **Backtest** lagi untuk menghitung Open → Close.")
    planets = retro["planet"].unique().tolist()
    for col, planet in zip(st.columns(len(planets)), planets):
        g = retro[retro["planet"] == planet]
        col.metric(f"{planet} ℞ · {len(g)} periode · rata-rata perubahan", idn(g['change_pct'].mean(), "{:+.2f}%"),
                   help="Rata-rata perubahan dari Open bar pertama ke Close bar terakhir periode retrograde.")
        col.caption(f"Naik {100 * (g['change_pct'] > 0).mean():.0f}% · turun {100 * (g['change_pct'] < 0).mean():.0f}% · "
                    f"trend berubah {100 * g['trend_changed'].mean():.0f}% periode")
    tl = lambda x: TREND_LABEL.get(x, x)
    st.dataframe(idn_styler(pd.DataFrame({
        "Planet": retro["planet"],
        "Mulai (WIB)": [_dmy(t, True) for t in retro["start"]],
        "Selesai (WIB)": [_dmy(t, True) for t in retro["end"]],
        "Bar": retro["bars"], "Open awal": _open_col(retro), "Close akhir": retro["close_end"],
        "Perubahan": retro["change_pct"],
        "Trend awal": retro["trend_start"].map(tl), "Trend akhir": retro["trend_end"].map(tl),
        "Perjalanan trend": [" → ".join(tl(x) for x in p) for p in retro["trend_path"]],
        "Trend berubah": retro["trend_changed"].map({True: "Ya", False: "Tidak"})}).iloc[::-1],
        {"Perubahan": "{:+.2f}%", "Open awal": "{:,.2f}", "Close akhir": "{:,.2f}"}),
        hide_index=True, use_container_width=True)
    st.caption(TREND_NOTE)


def show_sign_section(result: dict, body: str, run_id: int) -> None:
    if "sign_summary" not in result:
        st.info("Run ini dibuat sebelum fitur *in Sign* ada. Tekan **Backtest** lagi untuk menghitungnya.")
        return
    summ = result["sign_summary"]
    summ = summ[summ["planet"] == body]
    stays = result["signs"]
    stays = stays[stays["planet"] == body] if len(stays) else stays
    st.markdown(f"**{body} in Sign** · setiap periode {body} berada di satu rasi; "
                "perubahan = Open bar pertama → Close bar terakhir periode")
    if summ["periods"].sum() == 0:
        st.info(f"Tidak ada periode {body} in Sign yang utuh di dalam rentang ini.")
        return
    best = summ.dropna(subset=["avg_change"])
    k = st.columns(3)
    k[0].metric("Periode diuji", idn(int(summ["periods"].sum()), "{:,}"),
                help=f"Rata-rata {idn(stays['days'].mean(), '{:.1f}')} hari per periode.")
    if len(best):
        up, dn = best.loc[best["avg_change"].idxmax()], best.loc[best["avg_change"].idxmin()]
        k[1].metric(f"Rata-rata terbaik · {SIGN_SYMBOL[up['sign']]} {up['sign']}", idn(up["avg_change"], "{:+.2f}%"))
        k[2].metric(f"Rata-rata terburuk · {SIGN_SYMBOL[dn['sign']]} {dn['sign']}", idn(dn["avg_change"], "{:+.2f}%"))
    view = pd.DataFrame({
        "Rasi": [f"{SIGN_SYMBOL[s]} {s}" for s in summ["sign"]],
        "Periode": summ["periods"], "Bar/periode": summ["avg_bars"],
        "Rata² perubahan": summ["avg_change"], "Median": summ["median_change"],
        "% Naik": summ["pct_up"], "% Turun": summ["pct_down"],
        "Swing H / L": [f"{h} / {l}" for h, l in zip(summ["swings_high"], summ["swings_low"])],
        "% Trend berubah": summ["pct_trend_changed"],
        "Sampel ingress": summ["ingress_samples"], "% Swing saat masuk": summ["ingress_pct_swing"],
        "% High / Low saat masuk": [("—" if pd.isna(h) else f"{idn(h, '{:.0f}')} / {idn(l, '{:.0f}')}")
                                    for h, l in zip(summ["ingress_pct_high"], summ["ingress_pct_low"])],
        "Lift masuk": summ["ingress_lift"],
        "Lolos": summ["ingress_passed"].map({True: "✓", False: ""})})
    # ⚠️ next to a period count below the minimum sample size; the CSV keeps the plain number
    min_n = int(result["meta"]["min_samples"])
    shown = view.assign(Periode=[f"{idn(n, '{:,}')} ⚠️" if n < min_n else idn(n, "{:,}") for n in summ["periods"]])
    st.dataframe(idn_styler(shown, {
        "Bar/periode": "{:.1f}", "Rata² perubahan": "{:+.2f}%", "Median": "{:+.2f}%", "% Naik": "{:.0f}%",
        "% Turun": "{:.0f}%", "% Trend berubah": "{:.0f}%",
        "% Swing saat masuk": "{:.1f}%", "Lift masuk": "{:.2f}×"}),
        hide_index=True, use_container_width=True)
    st.caption(f"Kolom *saat masuk* menilai momen {body} masuk rasi seperti event lain: ada swing dalam "
               "±jendela hari? Lolos = memenuhi filter % swing dan sampel minimal. Sebuah bar harian dihitung milik "
               f"rasi tempat {body} berada pada jam 12:00 WIB; periode tanpa bar bursa (mis. Moon di akhir pekan) "
               f"tidak dihitung. ⚠️ = jumlah periode di bawah sampel minimal ({min_n}), hasilnya kurang bisa dipercaya.")
    st.download_button("⬇ Download CSV", view.to_csv(index=False).encode("utf-8"),
                       file_name=f"backtest_{run_id}_{body.lower()}_in_sign.csv", mime="text/csv",
                       key=f"bt_sign_csv_{run_id}_{body}")

    pick = st.selectbox(f"Rincian periode {body} di rasi", SIGNS, key=f"bt_sign_pick_{run_id}_{body}",
                        format_func=lambda s: f"{SIGN_SYMBOL[s]} {s}")
    g = stays[stays["sign"] == pick]
    if g.empty:
        st.caption("Tidak ada periode untuk rasi ini.")
        return
    tl = lambda x: TREND_LABEL.get(x, x)
    st.dataframe(idn_styler(pd.DataFrame({
        "Masuk (WIB)": [_dmy(t, True) for t in g["start"]],
        "Keluar (WIB)": [_dmy(t, True) for t in g["end"]],
        "Bar": g["bars"], "Open awal": g["open_start"], "Close akhir": g["close_end"],
        "Perubahan": g["change_pct"], "Swing H / L": [f"{h} / {l}" for h, l in zip(g["swings_high"], g["swings_low"])],
        "Trend awal": g["trend_start"].map(tl), "Trend akhir": g["trend_end"].map(tl),
        "Trend berubah": g["trend_changed"].map({True: "Ya", False: "Tidak"})}).iloc[::-1],
        {"Perubahan": "{:+.2f}%", "Open awal": "{:,.2f}", "Close akhir": "{:,.2f}"}),
        hide_index=True, use_container_width=True)
    st.caption(TREND_NOTE)


# ---------------------------------------------------------------- time geometry backtest
def swings_tagged(df: pd.DataFrame, period: int) -> pd.DataFrame:
    """`df` with its Tag column holding Denoised Swing points (period 1 = regular Swing)."""
    if period == 1:
        return df
    tags = [""] * len(df)
    for i, kind in denoised_swings(df["High"].to_numpy(dtype=float), df["Low"].to_numpy(dtype=float), period):
        tags[i] = kind
    return df.assign(Tag=tags)


def swing_source_label(period: int) -> str:
    return "Swing biasa" if period == 1 else f"Denoised Swing {period} candle"


def render_tg_backtest() -> None:
    """Time Geometry > Backtest: a confirmation, then the Calculator setting scored
    on the loaded chart (points per var F, +-1 bar on/off, cross factor)."""
    if "df" not in st.session_state:
        st.info("Load data dulu lewat **📂 Load Data** di sidebar. Backtest memakai data chart yang sedang ditampilkan.")
        return
    df, name, market = st.session_state["df"], st.session_state["name"], st.session_state["market"]
    if not is_daily(df):
        st.warning("Backtest Time Geometry hanya bisa untuk data harian.")
        return
    c = st.columns(3)
    period = int(c[0].number_input(
        "Swing: jumlah candle Denoised Swing (1 = Swing biasa)", min_value=1, max_value=DENOISE_MAX,
        value=1, step=1, key="tgbt_period",
        help="Samakan dengan indikator swing yang Anda pakai di chart, karena itulah yang dikirim ke Calculator."))
    tagged = swings_tagged(df, period)
    counts = tagged["Tag"].value_counts()
    ratios = ", ".join(f"{f:g}" for f in TG_RATIOS)
    st.markdown(
        f"Backtest akan menilai **setting Calculator** untuk **{name}** ({MARKETS[market]}): "
        f"**{idn(len(df), '{:,}')} bar**, {df['Date'].iloc[0]:%d/%m/%y} sampai {df['Date'].iloc[-1]:%d/%m/%y}, dengan "
        f"**{counts.get(TAG_SWING_HIGH, 0)} swing high** dan **{counts.get(TAG_SWING_LOW, 0)} swing low** "
        f"dari {swing_source_label(period)}.\n\n"
        "Backtest berjalan maju dari swing paling awal sampai paling akhir. Di setiap swing, proyeksi dihitung "
        f"hanya dari {TG_LAST_N} swing high dan {TG_LAST_N} swing low terakhir yang sudah terbentuk saat itu, "
        f"untuk semua var F ({ratios}) di setiap interval dan di faktor silang. Lalu dicek di bar mana swing "
        "berikutnya benar-benar terjadi:\n"
        "- Proyeksi yang jatuh **tepat** di bar itu: poin untuk var F-nya, dengan ±1 hari off.\n"
        "- Proyeksi yang meleset **1 bar** (sebelum atau sesudah): poin untuk var F-nya, dengan ±1 hari on.\n\n"
        "Hasilnya: **bobot 0–1 tiap var F**, **±1 hari on atau off**, dan **bobot faktor silang**. "
        "Interval lama dan baru dihitung sama.")
    run_key = (name, len(df), str(df["Date"].iloc[-1]), period)
    if st.button("▶ Start Backtest", type="primary", key="tgbt_go"):
        with st.spinner("Menghitung poin tiap var F…"):
            try:
                result = run_tg_backtest(tagged, history=TG_LAST_N)
            except ValueError as exc:
                st.error(str(exc))
                return
        st.session_state["tg_backtest"] = {"key": run_key, "result": result}
    bt = st.session_state.get("tg_backtest")
    if bt and bt.get("key") == run_key:
        show_tg_backtest(bt["result"], name, swing_source_label(period))


def apply_tg_weights(setting: dict, label: str) -> None:
    """Button callback: hand the setting to the Calculator page and open it.
    The page applies it once (a new id per click), then keeps manual edits."""
    st.session_state["tg_weights"] = {"id": uuid.uuid4().hex, "label": label, **setting}
    st.session_state["tg_weights_notice"] = True
    st.session_state["nav_sel"] = "tg"


def show_tg_backtest(res: dict, name: str, source: str) -> None:
    m, tol, rows = res["meta"], res["tolerance"], res["rows"]
    pct = lambda x: idn(100 * x, "{:.2f}%")
    state = "ON" if tol["on"] else "OFF"
    st.divider()
    st.markdown(f"##### Hasil backtest · {name} · {source}")
    st.caption(f"{idn(m['steps'], '{:,}')} swing dinilai · {_dmy(m['first'])} – {_dmy(m['last'])}")
    st.markdown(
        f"**±1 hari: {state}.** Tanggal proyeksi yang tepat kena {idn(tol['exact_hits'], '{:,}')} dari "
        f"{idn(tol['exact_dates'], '{:,}')} tanggal ({pct(tol['exact_rate'])}); tanggal 1 bar di sebelahnya kena "
        f"{idn(tol['near_hits'], '{:,}')} dari {idn(tol['near_dates'], '{:,}')} tanggal ({pct(tol['near_rate'])}). "
        + ("Tanggal di sebelahnya lebih sering kena, jadi proyeksi yang meleset 1 bar ikut mendapat poin."
           if tol["on"] else
           "Tanggal di sebelahnya tidak lebih sering kena, jadi hanya proyeksi yang tepat yang mendapat poin."))
    table = pd.DataFrame({
        "Variabel": [r["variable"] for r in rows],
        "Bobot": [r["weight"] for r in rows],
        "Poin": [r["hits"] for r in rows],
        "Proyeksi": [r["projections"] for r in rows],
        "Kena %": [100 * r["rate"] for r in rows]})
    st.dataframe(idn_styler(table, {"Kena %": "{:.2f}%", "Poin": "{:,}", "Proyeksi": "{:,}"}),
                 hide_index=True, use_container_width=True, height=35 * (len(table) + 1) + 3,
                 column_config={
                     "Bobot": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.3f")})
    hit = "tepat atau meleset 1 bar" if tol["on"] else "tepat"
    st.caption(
        f"**Poin** = berapa kali proyeksi var F itu jatuh {hit} di swing berikutnya. **Proyeksi** = berapa kali "
        "var F itu menunjuk tanggal sesudah swing terakhir. **Kena %** = Poin ÷ Proyeksi. **Bobot** = Kena % "
        "dibagi Kena % tertinggi di antara var F, jadi var F terbaik = 1. Bobot faktor silang = Kena % faktor "
        f"silang ÷ Kena % interval swing sejenis ({pct(m['same_rate'])}), paling tinggi 1.")
    c = st.columns([1.5, 1, 2.5])
    c[0].button("✅ Terapkan ke Calculator", type="primary", key="tgbt_apply", use_container_width=True,
                on_click=apply_tg_weights, args=(res["setting"], f"{name} · {source}"),
                help="Bobot var F dan faktor silang dipasang di Calculator (bobot 0 = dimatikan), "
                     "dan ±1 hari dinyalakan atau dimatikan.")
    csv = pd.concat([pd.DataFrame({"Variabel": ["±1 hari"], "Bobot": [state]}), table.astype({"Bobot": object})],
                    ignore_index=True)
    c[1].download_button("⬇ Download CSV", csv.to_csv(index=False).encode("utf-8"), use_container_width=True,
                         file_name=f"tg_setting_{name}.csv", mime="text/csv", key="tgbt_csv")


# ---------------------------------------------------------------- navigation
# Sidebar navigation: a tree with one folder per tool and its views below it.
# Only the chosen view is drawn below the chart.
NAV_TIME_GEOMETRY, NAV_ASTRONOMY = TOOLS[0][0], TOOLS[1][0]
TG_VIEWS = [("🧮 Calculator", "tg"), ("📊 Backtest", "tg_backtest")]
NAV_GROUPS = [
    ("tg", NAV_TIME_GEOMETRY, TG_VIEWS),
    ("astro", NAV_ASTRONOMY, [(label, view) for label, view, _, _ in ASTRO_VIEWS]),
    ("gann", "📐 Gann", []),      # not built yet: a single "Coming Soon" page
    ("bazi", "☯️ BaZi", []),
]
COMING_SOON = {"gann", "bazi"}


def load_data_menu() -> None:
    """Folder/upload picker and the two load buttons. On success the app reruns
    so the (then collapsed) menu and the chart show the new data."""
    source = st.radio("Sumber CSV", ["Folder data/", "Upload file"], horizontal=True)
    chosen = None
    if source == "Folder data/":
        files = sorted(DATA_DIR.glob("*.csv")) if DATA_DIR.exists() else []
        if files:
            pick = st.selectbox("Pilih file", files, format_func=lambda p: p.name)
            market = load_buttons()
            if market:
                chosen = (pick.stem, pick.read_bytes(), market)
        else:
            st.info(f"Belum ada file .csv di folder:\n\n`{DATA_DIR}`")
    else:
        up = st.file_uploader("Pilih file CSV", type=["csv"])
        if up is not None:
            market = load_buttons()
            if market:
                chosen = (Path(up.name).stem, up.getvalue(), market)
    st.caption("Kolom: Date, Open, High, Low, Close (Volume opsional).")

    if chosen is None:
        return
    name, content, market = chosen
    try:
        tagged = tag_bars(load_ohlc_csv(content))
        CACHE_DIR.mkdir(exist_ok=True)
        tagged.to_csv(CACHE_DIR / f"{name}_tags.csv", index=False)
    except Exception as exc:  # show the reason instead of crashing the app
        st.session_state["error"] = f"Gagal load **{name}**: {exc}"
        return
    st.session_state.update(df=tagged, name=name, market=market)
    st.session_state.pop("error", None)
    st.rerun()


NAV_CSS = """<style>
.st-key-navtree { gap:2px; }
.st-key-navtree button { justify-content:flex-start; border:none; border-radius:8px;
  min-height:0; padding:5px 10px; color:var(--text-color); background:transparent; }
.st-key-navtree button > div { justify-content:flex-start; width:100%; }
.st-key-navtree button p { font-size:14px; }
.st-key-navtree button:hover { background:rgba(128,128,128,.12); color:var(--text-color); }
.st-key-navtree button[kind="secondary"] { background:rgba(128,128,128,.22); }
.st-key-navtree [class*="st-key-navc_"] button { padding-left:30px; }
</style>"""


def _nav_select(item: str) -> None:
    st.session_state["nav_sel"] = item


def _nav_group(view: str) -> tuple[str, str, list]:
    """The tool holding `view`; a tool without views is selected by its own key."""
    return next(g for g in NAV_GROUPS if g[0] == view and not g[2] or any(v == view for _, v in g[2]))


def _nav_toggle(group: str) -> None:
    """Fold a tool open or closed; opening one that holds no selected view selects its first view."""
    key = f"nav_open_{group}"
    opening = not st.session_state.get(key, False)
    st.session_state[key] = opening
    items = next(g[2] for g in NAV_GROUPS if g[0] == group)
    if opening and _nav_group(st.session_state.get("nav_sel", "tg"))[0] != group:
        st.session_state["nav_sel"] = items[0][1]


def nav_tree() -> tuple[str, str, str]:
    """Tree menu like a file explorer: each tool folds open/closed with its views
    indented below it. Returns (tool label, view key, view label)."""
    st.markdown(NAV_CSS, unsafe_allow_html=True)
    sel = st.session_state.setdefault("nav_sel", "tg")
    if not any(v == sel for g in NAV_GROUPS for _, v in g[2]) and sel not in COMING_SOON:
        sel = st.session_state["nav_sel"] = "tg"
    current = _nav_group(sel)[0]
    with st.container(key="navtree"):
        for group, label, items in NAV_GROUPS:
            if not items:   # a tool with no views: one plain item, no fold arrow
                st.button(label, key=f"navp_{group}", use_container_width=True,
                          type="secondary" if sel == group else "tertiary", on_click=_nav_select, args=(group,))
                continue
            is_open = st.session_state.setdefault(f"nav_open_{group}", group == current)
            st.button(f"{label}  {'⌄' if is_open else '›'}", key=f"navp_{group}", use_container_width=True,
                      type="secondary" if group == current and not is_open else "tertiary",
                      on_click=_nav_toggle, args=(group,))
            if is_open:
                for child, view in items:
                    st.button(child, key=f"navc_{view}", use_container_width=True,
                              type="secondary" if sel == view else "tertiary", on_click=_nav_select, args=(view,))
    _, tool, items = _nav_group(sel)
    return tool, sel, next((child for child, v in items if v == sel), "")


def open_stock_from_calendar() -> None:
    """Callback of the hidden bridge input. A click on an Emiten chip in the Aspect
    Calendar writes "CODE|nonce" into it: download that stock's full daily history
    from Yahoo Finance, load it as the chart data, open Astronomy · Backtest and run it."""
    import re
    code = str(st.session_state.get("cg_bridge_in", "")).split("|")[0].strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,8}", code):
        return
    try:
        with st.spinner(f"Mengunduh seluruh data harga {code} dari Yahoo Finance…"):
            path = download_full_history(code, DATA_DIR)
            tagged = tag_bars(load_ohlc_csv(path))
        CACHE_DIR.mkdir(exist_ok=True)
        tagged.to_csv(CACHE_DIR / f"{path.stem}_tags.csv", index=False)
    except Exception as exc:
        st.session_state["error"] = f"Gagal download **{code}** dari Yahoo Finance: {exc}"
        return
    st.session_state.update(df=tagged, name=path.stem, market="ihsg", nav_sel="backtest",
                            nav_open_astro=True, bt_autorun=True)
    st.session_state.pop("error", None)


BRIDGE_CSS = "<style>.st-key-cg_bridge { display:none !important; }</style>"


# Data loaded before the market choice existed: make the user load it again
# rather than guess its market.
if "df" in st.session_state and "market" not in st.session_state:
    del st.session_state["df"]

with st.sidebar:
    st.markdown(BRIDGE_CSS, unsafe_allow_html=True)
    with st.container(key="cg_bridge"):
        st.text_input("bridge", key="cg_bridge_in", on_change=open_stock_from_calendar,
                      label_visibility="collapsed")
    loaded = "df" in st.session_state
    with st.expander("📂 Load Data", expanded=not loaded):
        load_data_menu()

    if "error" in st.session_state:
        st.error(st.session_state["error"])

    if loaded:
        df = st.session_state["df"]
        counts = df["Tag"].value_counts()
        st.markdown(f"**{st.session_state['name']}** · {MARKETS[st.session_state['market']]}")
        st.caption(f"{idn(len(df), '{:,}')} bar · {df['Date'].iloc[0]:%d/%m/%y} → {df['Date'].iloc[-1]:%d/%m/%y}  \n"
                   f"^ {counts.get(TAG_SWING_HIGH, 0)} swing high · v {counts.get(TAG_SWING_LOW, 0)} swing low")

    st.divider()
    nav, nav_view, nav_view_label = nav_tree()

# ---------------------------------------------------------------- main
if "df" not in st.session_state:
    st.title("ChronoGaze")
    st.write("Buka **📂 Load Data** di sidebar kiri, pilih file CSV, lalu klik "
             "**Load Saham IHSG** untuk emiten BEI atau **Load Komoditas Global** untuk emas, forex, crypto.")
else:
    df = st.session_state["df"]
    render_chart(df, st.session_state["name"])
    with st.expander("Lihat data tabel"):
        prices = {c: "{:,.2f}" for c in ("Open", "High", "Low", "Close")}
        st.dataframe(idn_styler(df.drop(columns="Tag").iloc[::-1], {**prices, "Volume": "{:,.0f}"}),
                     use_container_width=True, hide_index=True,
                     column_config={"Date": st.column_config.DatetimeColumn(format="DD/MM/YY")})

# ---------------------------------------------------------------- chosen tool
st.divider()
page = TIME_GEOMETRY_PAGE if nav == NAV_TIME_GEOMETRY else ASTRONOMY_PAGE
st.subheader(f"{nav} · {nav_view_label}" if nav_view_label else nav)
if nav_view in COMING_SOON:
    st.markdown('<div style="display:flex;align-items:center;justify-content:center;min-height:420px">'
                '<span style="font-size:64px;font-weight:700;letter-spacing:.02em;opacity:.75">Coming Soon</span>'
                '</div>', unsafe_allow_html=True)
elif nav_view == "tg_backtest":
    render_tg_backtest()
elif not page.exists():
    st.error(f"File tidak ditemukan: `{page}`")
elif page == TIME_GEOMETRY_PAGE:
    html = page.read_text(encoding="utf-8")
    # IHSG holidays come from db/ihsg_holidays.csv; the page has no holiday input.
    html = inject_before_first_script(html, load_ihsg_holidays(), "CHRONOGAZE_HOLIDAYS")
    weights = st.session_state.get("tg_weights")
    if weights:
        html = inject_before_first_script(html, weights, "CHRONOGAZE_WEIGHTS")
        if st.session_state.pop("tg_weights_notice", False):
            tol = "ON" if weights.get("tolOn") else "OFF"
            st.success(f"Setting dari backtest **{weights['label']}** sudah diterapkan ke Calculator: "
                       f"bobot var F, faktor silang, dan ±1 hari {tol}. Var F atau faktor silang dengan "
                       "bobot 0 dimatikan. Semuanya masih bisa diubah manual di panel kiri Calculator.")
    if "df" in st.session_state:
        df = st.session_state["df"]
        if is_daily(df):
            market = st.session_state["market"]
            payload = time_geometry_payload(df, st.session_state["name"], market, TG_LAST_N)
            html = inject_before_first_script(html, payload)
            if market == "global":
                calendar = (" Data ini ada perdagangan Sabtu dan Minggu (crypto), jadi semua hari dihitung "
                            "tanpa hari libur." if payload["weekend"] else
                            " Data ini tidak ada perdagangan Sabtu dan Minggu, jadi hanya Sabtu dan Minggu "
                            "yang libur; Senin sampai Jumat semuanya dihitung, tanpa libur bursa.")
            else:
                calendar = " Kalender IHSG: weekend dan libur BEI dari database dilewati."
            st.caption(f"{TG_LAST_N} swing high dan {TG_LAST_N} swing low terakhir sudah diisi ke "
                       f"profil **{payload['name']}** (pasar {MARKETS[market]}), dari indikator swing "
                       "yang sedang aktif di chart (Swing atau Denoised Swing). Profil ini ditimpa "
                       "ulang setiap kali data di-load atau indikator swing diubah." + calendar)
        else:
            st.caption("Data intraday: swing tidak dikirim ke Time Geometry (alat ini memakai tanggal harian).")
    components.html(html, height=TOOL_HEIGHT, scrolling=True)
else:
    _, view, height, css = next(v for v in ASTRO_VIEWS if v[1] == nav_view)
    if view == "backtest":
        render_backtest()
    else:
        html = page.read_text(encoding="utf-8")
        components.html(astronomy_view(html, view, css), height=height, scrolling=True)
