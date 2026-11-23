// ChronoGaze patch: show the page's date inputs as DD/MM/YY (24-hour time).
// The browser's own date fields follow the OS locale (MM/DD/YYYY here), so
// each one is hidden and a text field takes its place. The original input
// stays the source of truth: the page's code keeps reading and writing it,
// and every write is mirrored into the text field.
(function () {
  const pad = n => String(n).padStart(2, '0');
  const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');

  function toText(v, withTime) {
    const m = (v || '').match(/^(-?\d{4,6})-(\d\d)-(\d\d)(?:T(\d\d):(\d\d))?/);
    if (!m) return '';
    return `${m[3]}/${m[2]}/${m[1].slice(-2)}` + (withTime && m[4] ? ` ${m[4]}:${m[5]}` : '');
  }

  // "DD/MM/YY", "D/M/YYYY", optional " HH:MM". Two-digit years: 00-69 -> 20xx, 70-99 -> 19xx.
  function fromText(s, withTime, current) {
    const m = s.trim().match(/^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2}|\d{4})(?:\s+(\d{1,2})[:.](\d{2}))?$/);
    if (!m) return null;
    let y = +m[3];
    if (m[3].length === 2) y += y < 70 ? 2000 : 1900;
    const mo = +m[2], d = +m[1];
    const dt = new Date(Date.UTC(y, mo - 1, d));
    if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return null;
    const date = `${y}-${pad(mo)}-${pad(d)}`;
    if (!withTime) return date;
    let hh, mm;
    if (m[4] !== undefined) { hh = +m[4]; mm = +m[5]; }
    else { const t = (current || '').match(/T(\d\d):(\d\d)/); hh = t ? +t[1] : 0; mm = t ? +t[2] : 0; }
    if (hh > 23 || mm > 59) return null;
    return `${date}T${pad(hh)}:${pad(mm)}`;
  }

  function proxy(id, withTime) {
    const el = document.getElementById(id);
    if (!el || el.dataset.sgProxy) return;
    el.dataset.sgProxy = '1';
    const wrap = document.createElement('div');
    wrap.className = 'sg-date-wrap';
    const txt = document.createElement('input');
    txt.type = 'text';
    txt.className = 'sg-date';
    txt.placeholder = withTime ? 'DD/MM/YY HH:MM' : 'DD/MM/YY';
    txt.autocomplete = 'off';
    txt.setAttribute('aria-label', (el.labels && el.labels[0] ? el.labels[0].textContent : id) + ' (DD/MM/YY)');
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'sg-cal';
    btn.textContent = '📅';
    btn.setAttribute('aria-label', 'Buka kalender');
    el.parentNode.insertBefore(wrap, el);
    wrap.append(txt, btn, el);
    el.classList.add('sg-native');
    el.tabIndex = -1;

    const sync = () => { txt.value = toText(desc.get.call(el), withTime); txt.classList.remove('bad'); };
    Object.defineProperty(el, 'value', {
      configurable: true,
      get() { return desc.get.call(el); },
      set(v) { desc.set.call(el, v); sync(); },
    });
    sync();

    const commit = () => {
      const v = fromText(txt.value, withTime, desc.get.call(el));
      if (v === null) { txt.classList.add('bad'); return; }
      if (v !== desc.get.call(el)) {
        desc.set.call(el, v);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      }
      sync();
    };
    txt.addEventListener('change', commit);
    txt.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); commit(); } });
    el.addEventListener('change', sync);              // picked from the native calendar
    btn.addEventListener('click', () => { try { el.showPicker(); } catch (e) { el.focus(); } });
  }

  const css = document.createElement('style');
  css.textContent = `
    .sg-date-wrap{position:relative;display:flex;gap:6px;align-items:stretch}
    .sg-date-wrap .sg-date{flex:1;min-width:0}
    .sg-date-wrap .sg-date.bad{border-color:var(--retro);outline:1px solid var(--retro)}
    .sg-date-wrap .sg-cal{padding:4px 9px;line-height:1}
    .sg-date-wrap .sg-native{position:absolute;right:0;bottom:0;width:1px;height:1px;opacity:0;pointer-events:none;border:0;padding:0}`;
  document.head.appendChild(css);

  window.CG_PROXY_DATE = proxy;   // reused by patch_retrograde.js for its own date fields
  proxy('dt', true);
  proxy('skStart', false);
  proxy('skEnd', false);
})();
