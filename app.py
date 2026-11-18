"""Stargazer chart viewer.

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

from shared.csv_loader import load_ohlc_csv
from shared.moon_phases import EMOJI, load_moon_db, load_sign_sectors, nearest_bar_dates
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

# The Astronomy page is shown twice, each time trimmed by CSS to one job.
# The calculations still run in full; only what is displayed changes.
_ASTRO_COMMON_CSS = """
[hidden] { display:none !important; }  /* the artifact wrapper used to supply this */
.side, footer { display:none !important; }
.shell { grid-template-columns:1fr !important; }
"""
ASTRO_VIEWS = [
    ("🧮 Kalkulator", "calculator", 1100, _ASTRO_COMMON_CSS + """
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
    ("🔍 Aspect Seeker", "seeker", 900, _ASTRO_COMMON_CSS),
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


def astronomy_view(html: str, page: str, css: str) -> str:
    """Add view CSS and open `page` ("calculator" or "seeker") once loaded."""
    extra = f"<script>{ASTRO_PATCH_DATES}</script>"
    if page == "seeker":
        data = json.dumps(seeker_swing_payload()).replace("</", "<\\/")
        extra += SEEKER_SWING_JS.replace("__SWINGS__", data)
    else:
        sectors = json.dumps(load_sign_sectors()).replace("</", "<\\/")
        extra += f"<script>window.STARGAZER_SECTORS={sectors};{ASTRO_PATCH_MOON_SECTORS}</script>"
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
    """Define window.STARGAZER_SWINGS before the page's own script runs."""
    data = json.dumps(payload).replace("</", "<\\/")
    return html.replace("<script>", f"<script>window.STARGAZER_SWINGS={data};</script>\n<script>", 1)
LWC_URL = "https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"
CHART_HEIGHT = 640

st.set_page_config(page_title="Stargazer Chart", layout="wide")


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


@st.cache_data
def moon_db() -> pd.DataFrame:
    return load_moon_db()


def moon_records(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """Moon series points (incl. empty future bars) and their emoji markers.

    Each new/full moon is drawn on its own date, or on the nearest bar that
    exists: a trading day for past dates, an empty future bar after the data.
    Daily data only.
    """
    if not (df["Date"].dt.normalize() == df["Date"]).all():
        return [], []
    bar_dates = df["Date"].dt.strftime("%Y-%m-%d").tolist()

    # Empty bars after the data, so future moons have somewhere to sit.
    # Data with weekend bars (crypto) gets weekend bars in the future too.
    last = df["Date"].iloc[-1]
    end = max(pd.Timestamp.today().normalize(), last) + pd.Timedelta(days=MOON_FUTURE_DAYS)
    has_weekends = (df["Date"].dt.dayofweek >= 5).any()
    future = pd.date_range(last + pd.Timedelta(days=1), end, freq="D" if has_weekends else "B")
    future_dates = future.strftime("%Y-%m-%d").tolist()

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
    payload = json.dumps(
        {"candles": candles, "volumes": volumes, "markers": markers, "title": title,
         "moonSeries": moon_series, "moonMarkers": moon_markers}
    ).replace("</", "<\\/")
    html = f"""
<div id="wrap" style="position:relative;width:100%;height:{CHART_HEIGHT}px;">
  <div id="legend"></div>
  <div id="chart" style="width:100%;height:100%;"></div>
</div>
<style>
  html, body {{ margin:0; background:#131722; font-family:-apple-system,Segoe UI,Roboto,sans-serif; }}
  #legend {{ position:absolute; top:8px; left:12px; z-index:3; color:#d1d4dc; font-size:13px; pointer-events:none; }}
  #legend .t {{ font-size:15px; font-weight:600; margin-right:10px; }}
  #legend .k {{ color:#787b86; margin-left:8px; }}
</style>
<script src="{LWC_URL}"></script>
<script>
const data = {payload};
const el = document.getElementById('chart');
const chart = LightweightCharts.createChart(el, {{
  autoSize: true,
  layout: {{ background: {{ color: '#131722' }}, textColor: '#d1d4dc' }},
  grid: {{ vertLines: {{ color: '#1f2433' }}, horzLines: {{ color: '#1f2433' }} }},
  crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
  rightPriceScale: {{ borderColor: '#2a2e39', scaleMargins: {{ top: 0.08, bottom: 0.25 }} }},
  timeScale: {{ borderColor: '#2a2e39', rightOffset: 5 }},
}});
const candle = chart.addCandlestickSeries({{
  upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
  wickUpColor: '#26a69a', wickDownColor: '#ef5350',
}});
candle.setData(data.candles);
candle.setMarkers(data.markers);
const vol = chart.addHistogramSeries({{ priceFormat: {{ type: 'volume' }}, priceScaleId: 'vol' }});
chart.priceScale('vol').applyOptions({{ scaleMargins: {{ top: 0.78, bottom: 0.07 }} }});
vol.setData(data.volumes);

// New/full moon row along the bottom of the chart. The series is invisible;
// it only carries the emoji markers and the empty future bars.
const moon = chart.addLineSeries({{
  priceScaleId: 'moon', color: 'rgba(0,0,0,0)', lineVisible: false,
  lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
}});
chart.priceScale('moon').applyOptions({{ visible: false, scaleMargins: {{ top: 0.96, bottom: 0.01 }} }});
moon.setData(data.moonSeries);
moon.setMarkers(data.moonMarkers);
const moonByTime = new Map(data.moonMarkers.map(m => [m.time, m.id.split('|')]));

const byTime = new Map(data.candles.map((c, i) => [JSON.stringify(c.time), i]));
const legend = document.getElementById('legend');
const fmt = (x) => x.toLocaleString('id-ID', {{ maximumFractionDigits: 2 }});
function showLegend(i) {{
  const c = data.candles[i], v = data.volumes[i];
  const chg = i > 0 ? (c.close / data.candles[i-1].close - 1) * 100 : 0;
  const col = c.close >= c.open ? '#26a69a' : '#ef5350';
  legend.innerHTML = `<span class="t">${{data.title}}</span>` +
    `<span class="k">O</span> <span style="color:${{col}}">${{fmt(c.open)}}</span>` +
    `<span class="k">H</span> <span style="color:${{col}}">${{fmt(c.high)}}</span>` +
    `<span class="k">L</span> <span style="color:${{col}}">${{fmt(c.low)}}</span>` +
    `<span class="k">C</span> <span style="color:${{col}}">${{fmt(c.close)}}</span>` +
    `<span style="color:${{col}}"> (${{chg >= 0 ? '+' : ''}}${{chg.toFixed(2)}}%)</span>` +
    `<span class="k">Vol</span> ${{fmt(v.value)}}`;
}}
showLegend(data.candles.length - 1);
chart.subscribeCrosshairMove((p) => {{
  const i = p.time !== undefined ? byTime.get(JSON.stringify(p.time)) : undefined;
  showLegend(i !== undefined ? i : data.candles.length - 1);
  const m = p.time !== undefined ? moonByTime.get(p.time) : undefined;
  if (m) legend.innerHTML += `<span class="k">${{m[0] === 'FULL' ? '🌕 Full moon' : '🌑 New moon'}}</span> ${{m[1].slice(0, 16)}} WIB`;
}});

// Start zoomed on the most recent ~150 bars plus the next few weeks.
const n = data.candles.length;
const ahead = Math.min(25, data.moonSeries.filter(x => !byTime.has(JSON.stringify(x.time))).length);
if (n > 150) chart.timeScale().setVisibleLogicalRange({{ from: n - 150, to: n + Math.max(5, ahead) }});
else chart.timeScale().fitContent();
</script>
"""
    components.html(html, height=CHART_HEIGHT + 4)


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
    st.title("Stargazer")
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
                        components.html(astronomy_view(html, view, css), height=height, scrolling=True)
                continue
            components.html(html, height=TOOL_HEIGHT, scrolling=True)
        else:
            st.error(f"File tidak ditemukan: `{page}`")
