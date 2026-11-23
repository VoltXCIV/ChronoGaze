"""ChronoGaze chart viewer.

Run:  streamlit run app.py

Sidebar "Load Data" menu picks a CSV (from the data/ folder or an upload)
and shows it as an interactive candlestick chart drawn with TradingView's
open-source Lightweight Charts library.
"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from shared.backtest import DB_PATH as BACKTEST_DB, run_backtest, save_run
from shared.csv_loader import load_ohlc_csv
from shared.ephemeris import DB_PATH as EPHEMERIS_DB, load_ephemeris
from shared.moon_phases import EMOJI, load_moon_db, load_sign_sectors, nearest_bar_dates
from shared.tag_db import load_idx_tags, load_moon_sign_tags, load_planet_sign_tags
from shared.sun_signs import SYMBOLS as SUN_SYMBOLS, TAG_DB_PATH, load_sun_ingress_db, load_sun_sign_tags, sun_sign_segments
from shared.swing_detector import TAG_SWING_HIGH, TAG_SWING_LOW, swing_moves, tag_bars

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
    """IDX stocks and their tags, from the "IDX Tag" sheet of Tag DB.xlsx."""
    return load_idx_tags() if mtime else []


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
        extra += f"<script>window.CHRONOGAZE_PLANET_SIGNS={rules};window.CHRONOGAZE_IDX={stocks};{ASTRO_PATCH_ASPECT_CALENDAR}</script>"
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


def time_geometry_payload(df: pd.DataFrame, name: str, market: str, last_n: int) -> dict:
    """Most recent `last_n` swing highs and lows as DD-MM-YY strings."""
    def dates(tag: str) -> list[str]:
        picked = df.loc[df["Tag"] == tag, "Date"].tail(last_n)
        return picked.dt.strftime("%d-%m-%y").tolist()

    return {"name": f"{name} · chart", "market": market,
            "high": dates(TAG_SWING_HIGH), "low": dates(TAG_SWING_LOW)}


def inject_before_first_script(html: str, payload: dict) -> str:
    """Define window.CHRONOGAZE_SWINGS before the page's own script runs."""
    data = json.dumps(payload).replace("</", "<\\/")
    return html.replace("<script>", f"<script>window.CHRONOGAZE_SWINGS={data};</script>\n<script>", 1)
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

    markers = []
    if "Tag" in df.columns:
        for t, tag in zip(times, df["Tag"]):
            if tag == TAG_SWING_HIGH:
                markers.append({"time": t, "position": "aboveBar", "color": "#f0b90b",
                                "shape": "circle", "size": 0, "text": "^"})
            elif tag == TAG_SWING_LOW:
                markers.append({"time": t, "position": "belowBar", "color": "#2196f3",
                                "shape": "circle", "size": 0, "text": "v"})
    return candles, volumes, markers


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


def render_chart(df: pd.DataFrame, title: str) -> None:
    candles, volumes, markers = to_chart_records(df)
    moon_series, moon_markers = moon_records(df)
    sun_segs, sun_info = sun_sign_records(df)
    payload = json.dumps(
        {"candles": candles, "volumes": volumes, "markers": markers, "title": title,
         "moonSeries": moon_series, "moonMarkers": moon_markers,
         "sunSegs": sun_segs, "sunInfo": sun_info}
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
        st.info("Load data dulu di sidebar (**Load Data**). Backtest memakai data chart yang sedang ditampilkan.")
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
            except Exception as exc:
                st.error(f"Backtest gagal: {exc}")
                return
        st.session_state["backtest"] = {"name": name, "result": result, "run_id": run_id}
    bt = st.session_state.get("backtest")
    if not bt or bt["name"] != name:
        st.caption("Atur rentang dan filter, lalu tekan **Backtest**. Hasil setiap run otomatis disimpan "
                   f"di `{BACKTEST_DB.relative_to(ROOT).as_posix()}`.")
        return
    show_backtest_report(bt["result"], bt["run_id"], name)


def _pct_col(label: str, fmt: str = "%.1f%%", help: str | None = None):
    return st.column_config.NumberColumn(label, format=fmt, help=help)


def show_backtest_report(result: dict, run_id: int, name: str) -> None:
    m, summary, hits, retro = result["meta"], result["summary"], result["hits"], result["retro"]
    st.divider()
    st.markdown(f"##### Laporan backtest · {name}")
    st.caption(f"Run #{run_id} · {_dmy(m['start'])} – {_dmy(m['end'])} · {m['bars']:,} bar · {m['swings']:,} swing · "
               f"jendela ±{m['window']} hari · filter ≥{m['threshold']:g}% swing dan ≥{m['min_samples']} sampel · "
               f"tersimpan di `{BACKTEST_DB.relative_to(ROOT).as_posix()}`")
    k = st.columns(4)
    k[0].metric("Baseline acak", f"{m['baseline'] * 100:.1f}%",
                help=f"Peluang hari kalender acak punya swing dalam ±{m['window']} hari "
                     f"(dari {m['baseline_days']:,} hari). Event baru berarti bila jelas di atas angka ini.")
    k[1].metric("Jenis event diuji", f"{m['event_types']:,}")
    k[2].metric("Kejadian diuji", f"{m['occurrences']:,}")
    k[3].metric("Lolos filter", f"{m['passed']:,}")

    # ---- events
    st.markdown("**Event dengan swing ≥ filter** · aspek planet, fase bulan, stasiun Mercury/Venus")
    show_all = st.toggle("Tampilkan semua event (termasuk yang tidak lolos)", key=f"bt_all_{run_id}")
    table = summary if show_all else summary[summary["passed"]]
    if table.empty:
        st.info("Tidak ada event yang lolos filter. Coba turunkan filter % swing atau sampel minimal.")
    else:
        sh_sl, sl_sh = "Rata² SH → SL berikutnya", "Rata² SL → SH berikutnya"
        view = pd.DataFrame({
            "Event": table["event"], "Jenis": table["kind"], "Sampel": table["samples"],
            "Swing": table["swings"], "% Swing": table["pct_swing"], "% High": table["pct_high"],
            "% Low": table["pct_low"], sh_sl: table["avg_move_high"], sl_sh: table["avg_move_low"],
            "Lift": table["lift"], "Lolos": table["passed"]})
        st.dataframe(view, hide_index=True, use_container_width=True, column_config={
            "Sampel": st.column_config.NumberColumn("Sampel", help="Berapa kali event ini terjadi dan diuji."),
            "% Swing": _pct_col("% Swing"), "% High": _pct_col("% High"), "% Low": _pct_col("% Low"),
            sh_sl: _pct_col(sh_sl, "%+.2f%%"), sl_sh: _pct_col(sl_sh, "%+.2f%%"),
            "Lift": _pct_col("Lift", "%.2f×", "% Swing dibagi baseline acak. Di atas 1 = lebih sering dari kebetulan.")})
        st.caption("% High / % Low = porsi swing high / swing low di antara swing yang terjadi. "
                   "SH → SL = perubahan dari High swing high ke Low swing low berikutnya; "
                   "SL → SH = dari Low swing low ke High swing high berikutnya.")
        pick = st.selectbox("Rincian kejadian untuk event", table["event"].tolist(), key=f"bt_pick_{run_id}")
        occ = hits[hits["event"] == pick]
        sw_label = {TAG_SWING_HIGH: "^ Swing high", TAG_SWING_LOW: "v Swing low", "": "—"}
        # text columns so a missing value reads "—" instead of "None"
        num = lambda x, fmt="{:,.2f}": "—" if x is None or pd.isna(x) else fmt.format(x)
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

    # ---- retrograde
    st.markdown("**Periode retrograde Mercury & Venus**")
    if retro.empty:
        st.info("Tidak ada periode retrograde yang utuh di dalam rentang ini.")
        return
    planets = retro["planet"].unique().tolist()
    for col, planet in zip(st.columns(len(planets)), planets):
        g = retro[retro["planet"] == planet]
        col.metric(f"{planet} ℞ · {len(g)} periode · rata-rata perubahan", f"{g['change_pct'].mean():+.2f}%",
                   help="Rata-rata perubahan Close dari bar pertama ke bar terakhir periode retrograde.")
        col.caption(f"Naik {100 * (g['change_pct'] > 0).mean():.0f}% · turun {100 * (g['change_pct'] < 0).mean():.0f}% · "
                    f"trend berubah {100 * g['trend_changed'].mean():.0f}% periode")
    tl = lambda x: TREND_LABEL.get(x, x)
    st.dataframe(pd.DataFrame({
        "Planet": retro["planet"],
        "Mulai (WIB)": [_dmy(t, True) for t in retro["start"]],
        "Selesai (WIB)": [_dmy(t, True) for t in retro["end"]],
        "Bar": retro["bars"], "Close awal": retro["close_start"], "Close akhir": retro["close_end"],
        "Perubahan": retro["change_pct"],
        "Trend awal": retro["trend_start"].map(tl), "Trend akhir": retro["trend_end"].map(tl),
        "Perjalanan trend": [" → ".join(tl(x) for x in p) for p in retro["trend_path"]],
        "Trend berubah": retro["trend_changed"].map({True: "Ya", False: "Tidak"})}).iloc[::-1],
        hide_index=True, use_container_width=True,
        column_config={"Perubahan": _pct_col("Perubahan", "%+.2f%%"),
                       "Close awal": st.column_config.NumberColumn(format="%.2f"),
                       "Close akhir": st.column_config.NumberColumn(format="%.2f")})
    st.caption("Trend: Uptrend = 2× Higher High dan 2× Higher Low berturut-turut; Downtrend = 2× Lower High dan "
               "2× Lower Low; Sideways = swing high dan swing low masing-masing dalam rentang ≤3% selama lebih "
               "dari 7 bar. Trend di suatu bar hanya memakai swing yang sudah terbentuk sebelum bar itu.")


# ---------------------------------------------------------------- sidebar
# Data loaded before the market choice existed: make the user load it again
# rather than guess its market.
if "df" in st.session_state and "market" not in st.session_state:
    del st.session_state["df"]

with st.sidebar:
    st.header("📂 Load Data")
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

    if chosen is not None:
        name, content, market = chosen
        try:
            tagged = tag_bars(load_ohlc_csv(content))
            CACHE_DIR.mkdir(exist_ok=True)
            tagged.to_csv(CACHE_DIR / f"{name}_tags.csv", index=False)
            st.session_state["df"] = tagged
            st.session_state["name"] = name
            st.session_state["market"] = market
            st.session_state.pop("error", None)
        except Exception as exc:  # show the reason instead of crashing the app
            st.session_state["error"] = f"Gagal load **{name}**: {exc}"

    if "error" in st.session_state:
        st.error(st.session_state["error"])

    if "df" in st.session_state:
        df = st.session_state["df"]
        st.divider()
        st.caption("Data aktif")
        st.markdown(f"**{st.session_state['name']}** · {MARKETS[st.session_state['market']]}")
        st.write(f"{len(df):,} bar")
        st.write(f"{df['Date'].iloc[0]:%d %b %Y} → {df['Date'].iloc[-1]:%d %b %Y}")
        counts = df["Tag"].value_counts()
        st.write(f"Swing high: {counts.get(TAG_SWING_HIGH, 0)} · Swing low: {counts.get(TAG_SWING_LOW, 0)}")
        st.caption(f"Tag tersimpan di `cache/{st.session_state['name']}_tags.csv`")

# ---------------------------------------------------------------- main
if "df" not in st.session_state:
    st.title("ChronoGaze")
    st.write("Pilih file CSV di menu **Load Data** (sidebar kiri), lalu klik "
             "**Load Saham IHSG** untuk emiten BEI atau **Load Komoditas Global** untuk emas, forex, crypto.")
    st.caption("Kolom yang dibutuhkan: Date, Open, High, Low, Close (Volume opsional).")
else:
    df = st.session_state["df"]
    render_chart(df, st.session_state["name"])
    with st.expander("Lihat data tabel"):
        st.dataframe(df.drop(columns="Tag").iloc[::-1], use_container_width=True, hide_index=True)

# ---------------------------------------------------------------- tools
st.divider()
for tab, (label, page) in zip(st.tabs([label for label, _ in TOOLS]), TOOLS):
    with tab:
        if page.exists():
            html = page.read_text(encoding="utf-8")
            if page == TIME_GEOMETRY_PAGE and "df" in st.session_state:
                df = st.session_state["df"]
                if (df["Date"].dt.normalize() == df["Date"]).all():
                    market = st.session_state["market"]
                    payload = time_geometry_payload(df, st.session_state["name"], market, TG_LAST_N)
                    html = inject_before_first_script(html, payload)
                    st.caption(f"{TG_LAST_N} swing high dan {TG_LAST_N} swing low terakhir sudah diisi ke "
                               f"profil **{payload['name']}** (pasar {MARKETS[market]}). "
                               "Profil ini ditimpa ulang setiap kali data di-load.")
                else:
                    st.caption("Data intraday: swing tidak dikirim ke Time Geometry (alat ini memakai tanggal harian).")
            if page == ASTRONOMY_PAGE:
                for sub, (_, view, height, css) in zip(st.tabs([v[0] for v in ASTRO_VIEWS]), ASTRO_VIEWS):
                    with sub:
                        if view == "backtest":
                            render_backtest()
                        else:
                            components.html(astronomy_view(html, view, css), height=height, scrolling=True)
                continue
            components.html(html, height=TOOL_HEIGHT, scrolling=True)
        else:
            st.error(f"File tidak ditemukan: `{page}`")
