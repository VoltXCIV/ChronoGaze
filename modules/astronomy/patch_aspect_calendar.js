// ChronoGaze patch: "Aspect Calendar" page.
// Uses the "Planet in Sign" sheet of Tag DB.xlsx (window.CHRONOGAZE_PLANET_SIGNS):
// a planet standing in one of its listed signs favours the listed sectors and
// commodities. Container 1 shows one chosen date (arrows step a day, the date
// opens a calendar); container 2 lists the next 30 days from today.
// A planet counts for a day if it is in a listed sign at any time that day
// (local day at the UTC offset chosen on the Calculator tab); when it changes
// sign during the day the time is shown.
(function () {
  const A = window.Astronomy;
  const wrap = document.querySelector('.wrap');
  const RULES = window.CHRONOGAZE_PLANET_SIGNS || [];
  // IDX stocks and their tags ("IDX Tag" sheet); matched case-insensitively.
  const STOCKS = (window.CHRONOGAZE_IDX || []).map(x => Object.assign({ lc: x.tags.map(t => t.toLowerCase()) }, x));
  const EMITEN_SHOWN = 24;   // more are behind a "+N lainnya" button
  if (!A || !wrap) return;

  const SIGNS = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
                 'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces'];
  const SYM = { Sun: '☉', Moon: '☽', Mercury: '☿', Venus: '♀', Mars: '♂', Jupiter: '♃',
                Saturn: '♄', Uranus: '♅', Neptune: '♆', Pluto: '♇' };
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const WD = ['Min', 'Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab'];
  const DAY = 864e5, LIST_DAYS = 30;
  const EMPTY = 'Tidak ada sektor yang diuntungkan pada tanggal ini.';
  const pad = n => String(n).padStart(2, '0');
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const tz = () => { const e = document.getElementById('tz'); return e ? parseFloat(e.value) || 0 : 7; };
  const tzLabel = () => { const z = tz(); return z === 7 ? 'WIB' : z === 8 ? 'WITA' : z === 9 ? 'WIT' : 'UTC' + (z >= 0 ? '+' : '') + z; };

  // ---------- page ----------
  const page = document.createElement('div');
  page.className = 'page';
  page.id = 'page-acal';
  page.innerHTML = `
    <header>
      <h1>Aspect <em>Calendar</em></h1>
    </header>
    <section class="panel ac-one">
      <div class="ac-nav">
        <button type="button" class="ac-step" data-step="-1" aria-label="Hari sebelumnya">‹</button>
        <button type="button" class="ac-date" id="acDateBtn" aria-label="Pilih tanggal"><span id="acDateTxt"></span>
          <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg></button>
        <input type="date" id="acDate" class="ac-native" tabindex="-1" aria-hidden="true">
        <button type="button" class="ac-step" data-step="1" aria-label="Hari berikutnya">›</button>
      </div>
      <div id="acOne"></div>
    </section>
    <section class="panel">
      <div class="sec-head"><h2>Next 30 days</h2></div>
      <p class="ac-sub">Mulai hari ini. Klik tanggal untuk membukanya di atas.</p>
      <div id="acList" class="ac-list"></div>
      <p class="note">Waktu dalam ${'<span id="acTz"></span>'}; posisi memakai zodiak tropis. "mulai"/"hingga" berarti planet
        berpindah rasi pada jam tersebut di hari itu. ℞ = sedang retrograde.
        <span class="ac-key gold">Emas</span> = Mercury retrograde: Emas ikut diuntungkan sepanjang periode retrograde
        (jarang terjadi dan cukup akurat). <span class="ac-key weak">Baja</span> = tag kelas dua: tag Saturn yang
        sama dengan Mars, dorongannya lebih lemah.</p>
    </section>`;
  wrap.insertBefore(page, wrap.firstChild);

  const css = document.createElement('style');
  css.textContent = `
    .ac-nav{display:flex;align-items:center;justify-content:center;gap:6px;position:relative;margin-bottom:14px}
    .ac-step{width:38px;height:38px;padding:0;font-size:22px;line-height:1;background:none;border-color:transparent;color:var(--accent)}
    .ac-step:hover{background:var(--surface2)}
    .ac-date{display:inline-flex;align-items:center;gap:10px;font-size:18px;font-weight:500;color:var(--accent);
             background:none;border-color:transparent;padding:6px 12px;min-height:38px}
    .ac-date:hover{background:var(--surface2)}
    .ac-date svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round}
    .ac-native{position:absolute;left:50%;bottom:0;width:1px;height:1px;opacity:0;pointer-events:none;border:0;padding:0}
    .ac-items{display:grid;gap:10px}
    .ac-item{background:var(--surface2);border-radius:10px;padding:12px 14px;display:grid;gap:8px}
    .ac-head{font-size:14.5px;display:flex;flex-wrap:wrap;align-items:baseline;gap:6px}
    .ac-head .sym{font-size:17px;color:var(--accent);width:20px;text-align:center}
    .ac-head .when{font-family:var(--mono);font-size:12px;color:var(--muted)}
    .ac-head .rx{color:var(--retro);font-weight:700}
    .ac-row{display:grid;grid-template-columns:92px 1fr;gap:8px;align-items:start}
    .ac-lab{font-size:12px;font-weight:600;color:var(--muted);padding-top:5px}
    .ac-chips{display:flex;flex-wrap:wrap;gap:6px}
    .ac-chips span{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:4px 10px;font-size:12.5px;font-weight:600}
    .ac-chips span.gold{background:linear-gradient(135deg,#F6D77A,#D4A22B);border-color:#B8860B;color:#3A2A00}
    .ac-chips span.weak{background:transparent;border-style:dashed;color:var(--muted);font-weight:500}
    .ac-key{display:inline-block;border:1px solid var(--line);border-radius:6px;padding:0 6px;font-weight:600;font-size:11.5px}
    .ac-key.gold{background:linear-gradient(135deg,#F6D77A,#D4A22B);border-color:#B8860B;color:#3A2A00}
    .ac-key.weak{border-style:dashed;color:var(--muted);font-weight:500}
    .ac-note{font-size:12px;color:var(--muted)}
    .ac-lab small{display:block;font-weight:500;font-size:11px}
    .ac-chips.em span{font-family:var(--mono);font-size:12px;letter-spacing:.02em}
    .ac-chips .ac-more{background:none;border:1px dashed var(--line);border-radius:8px;padding:3px 9px;font-size:12px;color:var(--accent);min-height:0}
    .ac-chips .ac-rest{display:contents}
    .ac-empty{color:var(--muted);font-size:13.5px;padding:10px 2px}
    .ac-sub{margin:-6px 0 10px;font-size:12.5px;color:var(--muted)}
    .ac-list{display:grid}
    .ac-day{display:grid;grid-template-columns:118px 1fr;gap:14px;padding:12px 0;border-top:1px solid var(--line)}
    .ac-day:first-child{border-top:0}
    .ac-day .d{background:none;border:0;padding:4px 6px;text-align:left;font-family:var(--mono);font-size:13px;align-self:start;color:var(--ink)}
    .ac-day .d:hover{background:var(--surface2)}
    .ac-day .d small{display:block;font-family:var(--sans);color:var(--muted);font-size:11.5px}
    .ac-day.sel .d{background:var(--accent-soft);color:var(--ink)}
    .ac-day .ac-item{padding:9px 11px;gap:6px}
    .ac-day .ac-row{grid-template-columns:80px 1fr}
    .ac-day .ac-chips span{font-size:12px;padding:3px 8px}
    @media (max-width:560px){ .ac-day{grid-template-columns:1fr;gap:6px} .ac-row,.ac-day .ac-row{grid-template-columns:1fr;gap:4px} .ac-lab{padding-top:0} }`;
  document.head.appendChild(css);

  // ---------- astronomy ----------
  const lon = (body, t) => ((A.Ecliptic(A.GeoVector(body, t, true)).elon % 360) + 360) % 360;
  const wrapDeg = x => ((x + 540) % 360) - 180;
  function retro(body, t) {
    if (body === 'Sun' || body === 'Moon') return false;
    return wrapDeg(lon(body, t.AddDays(0.25)) - lon(body, t.AddDays(-0.25))) < 0;
  }
  // The planet's sign(s) during [t0, t1): one entry, or two when it changes sign.
  function signsDuring(body, t0, t1) {
    const l0 = lon(body, t0), l1 = lon(body, t1);
    const s0 = Math.floor(l0 / 30), s1 = Math.floor(l1 / 30);
    if (s0 === s1) return [{ sign: SIGNS[s0], from: null, to: null }];
    const dir = wrapDeg(l1 - l0) >= 0 ? 1 : -1;
    const boundary = dir > 0 ? s1 * 30 : s0 * 30;
    const hit = A.Search(t => dir * wrapDeg(lon(body, t) - boundary), t0, t1, { dt_tolerance_seconds: 30 });
    if (!hit) return [{ sign: SIGNS[s0], from: null, to: null }];
    return [{ sign: SIGNS[s0], from: null, to: hit.date }, { sign: SIGNS[s1], from: hit.date, to: null }];
  }
  // Day = local calendar day (y, m, d) at the chosen UTC offset.
  function dayStart(y, m, d) { return new Date(Date.UTC(y, m, d) - tz() * 3600e3); }
  // The two notes on the sheet, as rules:
  //  * Mercury: for the whole of a Mercury retrograde, Emas is favoured as well,
  //    whatever sign Mercury is in. Rare and reliable, so its tag is shown in gold.
  //  * Saturn: shares many tags with Mars but moves them less, so a tag Saturn
  //    shares with Mars is shown grey (second-class) on Saturn's card.
  const RETRO_BOOST = { Mercury: ['Emas'] };
  const WEAKER_COPY_OF = { Saturn: 'Mars' };
  const ruleOf = p => RULES.find(r => r.planet === p);
  function weakTags(planet) {
    const strong = ruleOf(WEAKER_COPY_OF[planet]);
    return strong ? new Set([...strong.sector, ...strong.commodity].map(x => x.toLowerCase())) : new Set();
  }

  function entriesFor(y, m, d) {
    const s = dayStart(y, m, d);
    const t0 = A.MakeTime(s), t1 = A.MakeTime(new Date(s.getTime() + DAY));
    const mid = A.MakeTime(new Date(s.getTime() + DAY / 2));
    const out = [];
    for (const r of RULES) {
      const inSign = signsDuring(r.planet, t0, t1).filter(seg => r.signs.includes(seg.sign));
      // retrograde at any moment of the day (a station can fall inside it)
      const rx = retro(r.planet, t0) || retro(r.planet, mid) || retro(r.planet, t1);
      const boost = rx ? (RETRO_BOOST[r.planet] || []) : [];
      for (const seg of inSign) out.push(Object.assign({ rule: r, retro: rx, boost }, seg));
      if (boost.length && !inSign.length) {
        // retrograde outside its listed signs: only the retrograde boost applies
        const sign = SIGNS[Math.floor(lon(r.planet, mid) / 30)];
        out.push({ rule: r, retro: true, boost, sign, from: null, to: null, boostOnly: true });
      }
    }
    return out;
  }

  // ---------- rendering ----------
  const hm = date => { const l = new Date(date.getTime() + tz() * 3600e3); return `${pad(l.getUTCHours())}:${pad(l.getUTCMinutes())}`; };
  // tags: [{t: text, c: '' | 'gold' | 'weak', title}]
  const chips = list => `<div class="ac-chips">${list.map(x =>
    `<span${x.c ? ` class="${x.c}"` : ''}${x.title ? ` title="${esc(x.title)}"` : ''}>${esc(x.t)}</span>`).join('')}</div>`;
  // Stocks with at least one of the card's tags. A stock takes the best colour
  // among its matching tags (gold > normal > grey); stronger and wider matches first.
  const RANK = { gold: 3, '': 2, weak: 1 };
  function emitenFor(tags) {
    const best = new Map();
    for (const x of tags) {
      const k = x.t.toLowerCase(), r = RANK[x.c || ''];
      if (!best.has(k) || best.get(k) < r) best.set(k, r);
    }
    const out = [];
    for (const st of STOCKS) {
      const hit = st.tags.filter((t, i) => best.has(st.lc[i]));
      if (!hit.length) continue;
      const rank = Math.max(...hit.map(t => best.get(t.toLowerCase())));
      out.push({ st, hit, rank });
    }
    return out.sort((a, b) => b.rank - a.rank || b.hit.length - a.hit.length || a.st.code.localeCompare(b.st.code));
  }
  const CLS = { 3: 'gold', 2: '', 1: 'weak' };
  function emitenChips(list) {
    const chip = m => `<span${CLS[m.rank] ? ` class="${CLS[m.rank]}"` : ''} title="${esc(m.st.name)} — ${esc(m.hit.join(', '))}">${esc(m.st.code)}</span>`;
    const head = list.slice(0, EMITEN_SHOWN).map(chip).join('');
    const rest = list.slice(EMITEN_SHOWN);
    return `<div class="ac-chips em">${head}` + (rest.length
      ? `<span class="ac-rest" hidden>${rest.map(chip).join('')}</span><button type="button" class="ac-more">+${rest.length} lainnya</button>`
      : '') + '</div>';
  }
  function itemHtml(e) {
    const r = e.rule;
    const weak = weakTags(r.planet);
    const weakTitle = `Tag yang sama dengan ${WEAKER_COPY_OF[r.planet]}; dorongan dari ${r.planet} lebih lemah`;
    const tag = t => weak.has(t.toLowerCase()) ? { t, c: 'weak', title: weakTitle } : { t };
    const sector = e.boostOnly ? [] : r.sector.map(tag);
    const commodity = e.boostOnly ? [] : r.commodity.map(tag);
    for (const t of e.boost || []) {
      const i = commodity.findIndex(x => x.t.toLowerCase() === t.toLowerCase());
      const g = { t, c: 'gold', title: `${r.planet} retrograde: ${t} ikut diuntungkan sepanjang periode retrograde` };
      if (i >= 0) commodity[i] = g; else commodity.push(g);
    }
    const emiten = emitenFor([...sector, ...commodity]);
    const when = e.from ? `mulai ${hm(e.from)}` : e.to ? `hingga ${hm(e.to)}` : '';
    const head = e.boostOnly
      ? `<b>${esc(r.planet)}</b> <span class="rx">℞ retrograde</span> <span class="when">in ${esc(e.sign)}</span>`
      : `<b>${esc(r.planet)}</b> in <b>${esc(e.sign)}</b> ${e.retro ? '<span class="rx" title="Retrograde">℞</span>' : ''}` +
        (when ? `<span class="when">${when}</span>` : '');
    const note = RETRO_BOOST[r.planet] || WEAKER_COPY_OF[r.planet] ? '' : r.note;   // those two notes are drawn as colours
    return `<div class="ac-item">
      <div class="ac-head"><span class="sym">${SYM[r.planet] || '•'}&#xFE0E;</span>${head}</div>
      ${emiten.length ? `<div class="ac-row"><span class="ac-lab">Emiten<small>${emiten.length}</small></span>${emitenChips(emiten)}</div>` : ''}
      ${sector.length ? `<div class="ac-row"><span class="ac-lab">Sector</span>${chips(sector)}</div>` : ''}
      ${commodity.length ? `<div class="ac-row"><span class="ac-lab">Commodity</span>${chips(commodity)}</div>` : ''}
      ${note ? `<div class="ac-note">Catatan: ${esc(note)}</div>` : ''}
    </div>`;
  }
  const blockHtml = list => list.length ? `<div class="ac-items">${list.map(itemHtml).join('')}</div>` : `<div class="ac-empty">${EMPTY}</div>`;

  const $ = id => document.getElementById(id);
  const label = (y, m, d) => `${pad(d)} ${MON[m]} ${String(y).slice(-2)}`;
  const parts = iso => { const p = iso.split('-').map(Number); return [p[0], p[1] - 1, p[2]]; };
  const isoOf = (y, m, d) => new Date(Date.UTC(y, m, d)).toISOString().slice(0, 10);
  const todayIso = () => new Date(Date.now() + tz() * 3600e3).toISOString().slice(0, 10);

  function showOne() {
    const v = $('acDate').value || todayIso();
    const [y, m, d] = parts(v);
    $('acDateTxt').textContent = label(y, m, d);
    try { $('acOne').innerHTML = blockHtml(entriesFor(y, m, d)); }
    catch (e) { $('acOne').innerHTML = `<div class="ac-empty">Perhitungan gagal: ${esc(e.message)}</div>`; }
    page.querySelectorAll('.ac-day').forEach(el => el.classList.toggle('sel', el.dataset.d === v));
  }
  function showList() {
    $('acTz').textContent = tzLabel();
    const [y, m, d] = parts(todayIso());
    let html = '';
    for (let i = 0; i < LIST_DAYS; i++) {
      const iso = isoOf(y, m, d + i), [yy, mm, dd] = parts(iso);
      const wd = WD[new Date(Date.UTC(yy, mm, dd)).getUTCDay()];
      let body;
      try { body = blockHtml(entriesFor(yy, mm, dd)); } catch (e) { body = `<div class="ac-empty">Perhitungan gagal: ${esc(e.message)}</div>`; }
      html += `<div class="ac-day" data-d="${iso}"><button type="button" class="d" data-d="${iso}">${label(yy, mm, dd)}` +
              `<small>${wd}${i === 0 ? ' · hari ini' : ''}</small></button><div>${body}</div></div>`;
    }
    $('acList').innerHTML = html;
  }
  function setDate(iso) { $('acDate').value = iso; showOne(); }

  page.querySelectorAll('.ac-step').forEach(b => b.addEventListener('click', () => {
    const [y, m, d] = parts($('acDate').value || todayIso());
    setDate(isoOf(y, m, d + +b.dataset.step));
  }));
  $('acDateBtn').addEventListener('click', () => { try { $('acDate').showPicker(); } catch (e) { $('acDate').focus(); } });
  $('acDate').addEventListener('change', showOne);
  page.addEventListener('click', e => {
    const b = e.target.closest('.ac-more');
    if (!b) return;
    const rest = b.previousElementSibling, open = rest.hidden;
    rest.hidden = !open;
    b.textContent = open ? 'Sembunyikan' : `+${rest.children.length} lainnya`;
  });
  $('acList').addEventListener('click', e => {
    const b = e.target.closest('button.d');
    if (!b) return;
    setDate(b.dataset.d);
    page.querySelector('.ac-one').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  $('acDate').value = todayIso();
  showList();
  showOne();
})();
