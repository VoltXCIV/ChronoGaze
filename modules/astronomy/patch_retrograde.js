// ChronoGaze patch: "Retrograde" page.
// The user picks a date range and one or more planets; every change reruns the
// search at once (no Search button). For each planet it lists the retrograde
// periods that overlap the range: station retrograde (geocentric ecliptic
// longitude stops and turns backwards) to station direct (turns forwards).
// Uses Astronomy Engine, already loaded by the Astronomy page.
(function () {
  const A = window.Astronomy;
  const wrap = document.querySelector('.wrap');
  if (!A || !wrap) return;

  const PLANETS = ['Mercury', 'Venus', 'Mars', 'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'];
  const SIGNS = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
                 'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces'];
  const DAY = 864e5;
  const MAX_YEARS = 50;
  // Longest retrograde (Pluto) lasts ~160 days, so look this far outside the
  // range to catch periods that started before it or end after it.
  const PAD_DAYS = 200;
  const pad = n => String(n).padStart(2, '0');
  const tz = () => { const e = document.getElementById('tz'); return e ? parseFloat(e.value) || 0 : 7; };
  const tzLabel = () => { const z = tz(); return z === 7 ? 'WIB' : z === 8 ? 'WITA' : z === 9 ? 'WIT' : 'UTC' + (z >= 0 ? '+' : '') + z; };

  // ---------- page ----------
  const page = document.createElement('div');
  page.className = 'page';
  page.id = 'page-retro';
  page.innerHTML = `
    <header>
      <h1>Planet <em>Retrograde</em></h1>
      <p class="lede">Retrograde periods of the selected planets that overlap the chosen date range.
        The list updates as soon as you change the dates or the planets.</p>
    </header>
    <section class="panel">
      <form class="seek-form" id="rtForm" onsubmit="return false">
        <div class="field"><label class="label" for="rtStart">Start date</label><input id="rtStart" type="date"></div>
        <div class="field"><label class="label" for="rtEnd">End date</label><input id="rtEnd" type="date"></div>
      </form>
      <fieldset class="rt-planets">
        <legend class="label">Planet</legend>
        ${PLANETS.map(p => `<label class="rt-chk"><input type="checkbox" value="${p}" checked> ${p}</label>`).join('')}
        <span class="rt-all">
          <button type="button" data-all="1">Semua</button>
          <button type="button" data-all="0">Kosongkan</button>
        </span>
      </fieldset>
      <div class="seekmsg" id="rtMsg"></div>
      <div class="tbl-wrap"><table id="rtResults"></table></div>
      <p class="note"><b>Mulai</b> = station retrograde: the planet's geocentric ecliptic longitude stops and starts
        moving backwards. <b>Selesai</b> = station direct: it stops and moves forwards again.
        <b>Puncak retrograde</b> = the moment of fastest backward motion, near the middle of the period, when the
        planet is closest to Earth. <b>Durasi</b> = Selesai minus Mulai. Rows sorted by Mulai; a highlighted row
        with ℞ is retrograde right now. Positions use the tropical zodiac; times use the UTC offset chosen on the
        Calculator tab.</p>
    </section>`;
  wrap.insertBefore(page, wrap.firstChild);

  const css = document.createElement('style');
  css.textContent = `
    .rt-planets{border:0;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center}
    .rt-planets legend{margin-bottom:6px;padding:0}
    .rt-chk{display:inline-flex;align-items:center;gap:6px;font-size:14px;cursor:pointer;min-height:32px}
    .rt-chk input{width:18px;height:18px;accent-color:var(--accent);margin:0}
    .rt-all{display:inline-flex;gap:6px;margin-left:auto}
    .rt-all button{padding:4px 10px;font-size:12.5px}
    #rtResults tr.now td{background:var(--accent-soft)}
    #rtResults td.st{font-family:var(--sans)}`;
  document.head.appendChild(css);

  // ---------- astronomy ----------
  const lon = (body, t) => A.Ecliptic(A.GeoVector(body, t, true)).elon;
  // degrees per day, central difference over ±0.25 day
  function speed(body, t) {
    let d = lon(body, t.AddDays(0.25)) - lon(body, t.AddDays(-0.25));
    if (d > 180) d -= 360; if (d < -180) d += 360;
    return d / 0.5;
  }
  function stations(body, t0, t1) {
    const out = [];
    let t = A.MakeTime(t0), v = speed(body, t);
    const end = A.MakeTime(t1);
    while (t.ut < end.ut) {
      const n = t.AddDays(1), w = speed(body, n);
      if ((v > 0) !== (w > 0)) {
        const dir = v > 0 ? 'R' : 'D';                       // + -> - is station retrograde
        const f = dir === 'R' ? (x => -speed(body, x)) : (x => speed(body, x));
        const hit = A.Search(f, t, n, { dt_tolerance_seconds: 60 }) || t;
        out.push({ type: dir, time: hit, lon: lon(body, hit) });
      }
      t = n; v = w;
    }
    return { list: out, retroAtStart: speed(body, A.MakeTime(t0)) < 0 };
  }
  function periods(body, start, end) {
    const s0 = new Date(start.getTime() - PAD_DAYS * DAY), s1 = new Date(end.getTime() + PAD_DAYS * DAY);
    const { list, retroAtStart } = stations(body, s0, s1);
    const res = [];
    let open = null;
    if (retroAtStart) open = { body, sr: null };
    for (const st of list) {
      if (st.type === 'R') open = { body, sr: st };
      else if (open) { res.push(Object.assign(open, { sd: st })); open = null; }
    }
    if (open) res.push(Object.assign(open, { sd: null }));
    // keep periods that overlap [start, end]
    const kept = res.filter(p => (!p.sd || p.sd.time.date >= start) && (!p.sr || p.sr.time.date <= end));
    kept.forEach(p => { p.peak = peak(body, p); });
    return kept;
  }
  // Peak of a retrograde: the moment of fastest backward motion, where the
  // speed stops falling and starts rising again (acceleration crosses zero).
  // It falls near the middle of the period, when the planet is closest to Earth.
  function peak(body, p) {
    if (!p.sr || !p.sd) return null;
    const accel = t => speed(body, t.AddDays(0.5)) - speed(body, t.AddDays(-0.5));
    const hit = A.Search(accel, p.sr.time, p.sd.time, { dt_tolerance_seconds: 60 });
    return hit ? { time: hit, lon: lon(body, hit), speed: speed(body, hit) } : null;
  }

  // ---------- formatting ----------
  function fmt(t) {
    const l = new Date(t.date.getTime() + tz() * 3600e3);
    return `${pad(l.getUTCDate())}/${pad(l.getUTCMonth() + 1)}/${String(l.getUTCFullYear()).slice(-2)} ${pad(l.getUTCHours())}:${pad(l.getUTCMinutes())}`;
  }
  function pos(x) {
    const v = ((x % 360) + 360) % 360, i = Math.floor(v / 30), d = v - i * 30;
    let deg = Math.floor(d), min = Math.round((d - deg) * 60);
    if (min === 60) { deg++; min = 0; }
    return `${pad(deg)}°${pad(min)}′ ${SIGNS[i]}`;
  }
  const cell = st => st ? `${fmt(st.time)}<br><span style="color:var(--muted)">${pos(st.lon)}</span>` : '<span style="color:var(--muted)">di luar jangkauan</span>';

  // ---------- run ----------
  const $ = id => document.getElementById(id);
  const parse = v => { const m = (v || '').match(/^(\d{4})-(\d\d)-(\d\d)$/); return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]) - tz() * 3600e3) : null; };
  function run() {
    const msg = h => { $('rtMsg').innerHTML = h; };
    const start = parse($('rtStart').value), endDay = parse($('rtEnd').value);
    const chosen = [...page.querySelectorAll('.rt-chk input:checked')].map(c => c.value);
    if (!start || !endDay) { msg('<span class="err">Isi tanggal mulai dan tanggal akhir.</span>'); $('rtResults').innerHTML = ''; return; }
    const end = new Date(endDay.getTime() + DAY - 1);       // include the whole end day
    if (end <= start) { msg('<span class="err">Tanggal akhir harus setelah tanggal mulai.</span>'); $('rtResults').innerHTML = ''; return; }
    if (end - start > MAX_YEARS * 365.25 * DAY) { msg(`<span class="err">Rentang maksimal ${MAX_YEARS} tahun.</span>`); $('rtResults').innerHTML = ''; return; }
    if (!chosen.length) { msg('Pilih minimal satu planet.'); $('rtResults').innerHTML = ''; return; }
    const t0 = performance.now();
    let rows = [];
    try { chosen.forEach(b => { rows = rows.concat(periods(b, start, end)); }); }
    catch (e) { msg(`<span class="err">Pencarian gagal: ${e.message}</span>`); return; }
    // ascending by start time (a period already under way before the search window comes first)
    rows.sort((a, b) => (a.sr ? a.sr.time.ut : -1e9) - (b.sr ? b.sr.time.ut : -1e9));
    const now = Date.now();
    const dur = (a, b) => {
      const h = Math.round((b - a) / 36e5);
      return `${Math.floor(h / 24)} hari ${h % 24} jam`;
    };
    $('rtResults').innerHTML = rows.length
      ? `<thead><tr><th>Planet</th><th class="l">Mulai (${tzLabel()})</th><th class="l">Selesai (${tzLabel()})</th><th class="l">Puncak retrograde (${tzLabel()})</th><th>Durasi</th></tr></thead><tbody>` +
        rows.map(p => {
          const a = p.sr ? p.sr.time.date.getTime() : -Infinity, b = p.sd ? p.sd.time.date.getTime() : Infinity;
          const active = now >= a && now <= b;
          return `<tr${active ? ' class="now" title="Sedang retrograde"' : ''}><td>${p.body}${active ? ' ℞' : ''}</td>` +
            `<td class="l">${cell(p.sr)}</td><td class="l">${cell(p.sd)}</td><td class="l">${cell(p.peak)}</td>` +
            `<td>${p.sr && p.sd ? dur(a, b) : '—'}</td></tr>`;
        }).join('') + '</tbody>'
      : `<tbody><tr><td style="font-family:var(--sans);color:var(--muted)">Tidak ada retrograde untuk planet terpilih dalam rentang ini.</td></tr></tbody>`;
    msg(`<b>${rows.length}</b> periode retrograde · ${chosen.length} planet · ${Math.round(performance.now() - t0)} ms`);
  }
  let timer = null;
  const runSoon = () => { clearTimeout(timer); timer = setTimeout(run, 120); };

  // defaults: today .. +1 year (local date at the chosen UTC offset)
  const today = new Date(Date.now() + tz() * 3600e3);
  const iso = d => d.toISOString().slice(0, 10);
  $('rtStart').value = iso(today);
  const yr = new Date(today); yr.setUTCFullYear(yr.getUTCFullYear() + 1);
  $('rtEnd').value = iso(yr);
  if (window.CG_PROXY_DATE) { window.CG_PROXY_DATE('rtStart', false); window.CG_PROXY_DATE('rtEnd', false); }

  ['rtStart', 'rtEnd'].forEach(id => { $(id).addEventListener('change', runSoon); $(id).addEventListener('input', runSoon); });
  page.querySelectorAll('.rt-chk input').forEach(c => c.addEventListener('change', runSoon));
  page.querySelectorAll('.rt-all button').forEach(b => b.addEventListener('click', () => {
    page.querySelectorAll('.rt-chk input').forEach(c => { c.checked = b.dataset.all === '1'; });
    runSoon();
  }));
  run();
})();
