// ChronoGaze patch: under "Upcoming moon phases", show the zodiac sign the
// Moon is in now and the sign it enters next, with the sectors each boosts.
// A period runs from the moment the Moon enters a sign (its tropical ecliptic
// longitude crosses a multiple of 30°) to the moment it leaves, about 2.5
// days. "Now" is the date, time and UTC offset chosen in the input panel.
(function () {
  const A = window.Astronomy;
  const phases = document.getElementById('phases');
  if (!A || !phases) return;
  const SECTORS = window.CHRONOGAZE_SECTORS || {};
  const SIGNS = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
                 'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces'];
  const DAY = 864e5;
  const pad = n => String(n).padStart(2, '0');

  const box = document.createElement('ul');
  box.className = 'sg-moonsec';
  phases.insertAdjacentElement('afterend', box);
  const css = document.createElement('style');
  css.textContent = `
    .sg-moonsec{list-style:none;margin:0;padding:12px 14px;border-radius:8px;background:var(--surface2);display:grid;gap:12px;font-size:13.5px}
    .sg-moonsec li{display:grid;gap:6px}
    .sg-moonsec .hd{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline}
    .sg-moonsec .p{font-family:var(--mono);font-size:12px;color:var(--muted);white-space:nowrap}
    .sg-moonsec b{color:var(--accent);font-weight:600}
    .sg-moonsec .chips{display:flex;flex-wrap:wrap;gap:6px}
    .sg-moonsec .chips span{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:3px 9px;font-size:12px;font-weight:600}
    .sg-moonsec .none{color:var(--muted)}`;
  document.head.appendChild(css);

  const tz = () => parseFloat(document.getElementById('tz').value) || 0;
  function selectedMoment() {
    const v = document.getElementById('dt').value;
    const m = v && v.match(/^(-?\d{4,6})-(\d\d)-(\d\d)T(\d\d):(\d\d)/);
    if (!m) return new Date();
    return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) - tz() * 3600e3);
  }
  function fmt(date) {
    const l = new Date(date.getTime() + tz() * 3600e3);
    return `${pad(l.getUTCDate())}/${pad(l.getUTCMonth() + 1)}/${String(l.getUTCFullYear()).slice(-2)} ` +
           `${pad(l.getUTCHours())}:${pad(l.getUTCMinutes())}`;
  }
  // Moon's tropical ecliptic longitude, computed as the rest of the page does.
  const moonLon = t => ((A.Ecliptic(A.GeoVector('Moon', t, true)).elon % 360) + 360) % 360;
  // When the Moon's longitude crosses `deg` between t1 and t2 (it only moves forward).
  function crossing(deg, t1, t2) {
    const f = t => ((moonLon(t) - deg + 540) % 360) - 180;
    const hit = A.Search(f, A.MakeTime(t1), A.MakeTime(t2), { dt_tolerance_seconds: 1 });
    if (!hit) throw new Error('perpindahan rasi tidak ditemukan');
    return hit.date;
  }

  function render() {
    try {
      const t = selectedMoment();
      const s = Math.floor(moonLon(t) / 30);
      // The Moon stays in one sign at most ~2.8 days, so 3-day windows always hold the crossing.
      const start = crossing(s * 30, new Date(t.getTime() - 3 * DAY), t);
      const end = crossing(((s + 1) % 12) * 30, t, new Date(t.getTime() + 3 * DAY));
      const after = crossing(((s + 2) % 12) * 30, new Date(end.getTime() + 60e3), new Date(end.getTime() + 3 * DAY));
      const tags = sign => (SECTORS[sign] || '').split(';').map(x => x.trim()).filter(Boolean);
      const line = (from, to, sign, lead) => {
        const t = tags(sign);
        return `<li><div class="hd"><span>${lead} <b>${sign}</b> — favoured sectors:</span>` +
          `<span class="p">${fmt(from)} – ${fmt(to)}</span></div>` +
          (t.length ? `<div class="chips">${t.map(x => `<span>${x}</span>`).join('')}</div>`
                    : '<div class="none">No sectors listed for this sign.</div>') + '</li>';
      };
      box.innerHTML = line(start, end, SIGNS[s], 'The Moon is in') +
                      line(end, after, SIGNS[(s + 1) % 12], 'Next, the Moon enters');
    } catch (e) {
      box.innerHTML = `<li>Gagal menghitung posisi bulan: ${e.message}</li>`;
    }
  }
  new MutationObserver(render).observe(phases, { childList: true });
  render();
})();
