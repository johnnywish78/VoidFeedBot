// Calendar density regression test — verifies the 5-dot cap + "+N" marker
// and that grid tracks never explode. Loads the real app.js in a vm with a
// stubbed DOM and a fake `fetch` that serves seeded /api/plan data.
const fs = require('fs');
const vm = require('vm');

const src = fs.readFileSync('studio_web/app.js', 'utf8');

function makeEl(id) {
  const el = {
    id: id || '', className: '', dataset: {}, style: {}, children: [], _html: '',
    classList: { add(){}, remove(){}, contains(){ return false; } },
    addEventListener(){}, querySelector(){ return null; },
    querySelectorAll(){ return []; },
    insertAdjacentHTML(){},
    appendChild(child){ this.children.push(child); },
    removeChild(child){ const i = this.children.indexOf(child); if (i >= 0) this.children.splice(i,1); },
    set innerHTML(v) {
      this._html = v;
      this.children = [];
      const re = /<span class="cal-cell([^"]*)" data-key="([^"]*)" data-day="([^"]*)">([\s\S]*?)<\/span>/g;
      let m;
      while ((m = re.exec(v))) {
        this.children.push({
          tagName: 'SPAN', className: 'cal-cell' + m[1],
          dataset: { key: m[2], day: m[3] },
          _html: m[4],
          textContent: m[4].replace(/<[^>]*>/g, ''),
          querySelector(sel) {
            // parse dots inside this cell's own content
            const inner = this._html;
            const dotsStart = inner.indexOf('<span class="dots">');
            if (dotsStart < 0) return null;
            const after = inner.slice(dotsStart + 19);
            const dotsEnd = after.indexOf('</span>');
            const dotsHtml = dotsEnd < 0 ? after : after.slice(0, dotsEnd);
            return { children: parseDots(dotsHtml) };
          },
        });
      }
    },
    get innerHTML() { return this._html; },
    getBoundingClientRect() { return { width: 63.4, height: 63.4 }; },
  };
  return el;
}
function parseDots(html) {
  const out = [];
  const re = /<i class="dot-([^"]+)">?([^<]*)<\/?i>/g;
  let m;
  while ((m = re.exec(html))) out.push({ className: 'dot-' + m[1], textContent: m[2] || '' });
  return out;
}

const els = {};
const doc = {
  documentElement: { lang: 'fa' },
  getElementById(id) { if (!els[id]) els[id] = makeEl(id); return els[id]; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement: () => makeEl(),
  addEventListener(){ }, readyState: 'complete',
};

// Seed plan data: Gregorian days 22(1),23(6),24(5),25(1),26(316),27(347)
function buildPlan() {
  return [
    { status: 'published', day: '2026-11-22' },
    ...Array.from({length:6}, () => ({ status: 'published', day: '2026-11-23' })),
    ...Array.from({length:5}, () => ({ status: 'scheduled', day: '2026-11-24' })),
    { status: 'published', day: '2026-11-25' },
    ...Array.from({length:316}, () => ({ status: 'published', day: '2026-11-26' })),
    ...Array.from({length:347}, () => ({ status: 'publish_failed', day: '2026-11-27' })),
  ];
}
const fakeFetch = async (url, opts) => {
  if (String(url).includes('/api/plan')) {
    const m = /month=(\d{4}-\d{2})/.exec(String(url));
    const prefix = m ? m[1] : '';
    const rows = buildPlan().filter(r => r.day.slice(0,7) === prefix);
    return { ok: true, json: async () => rows };
  }
  if (String(url).includes('/api/me')) {
    return { ok: true, json: async () => ({ user: { id: 1 }, stats: {} }) };
  }
  return { ok: true, json: async () => ({}) };
};

const sandbox = {
  window: { Telegram: null, history: { length: 0 }, addEventListener(){}, innerWidth: 800, innerHeight: 600 },
  document: doc,
  localStorage: { getItem(){ return null; }, setItem(){} },
  location: { search: '?demo', reload(){} },
  URLSearchParams: class { has(){ return false; } },
  console, setTimeout, clearTimeout,
  Date, Math, Set, Object, Array, String, Number, RegExp, JSON, isNaN, parseInt, parseFloat,
  fetch: fakeFetch,
};
const ctx = vm.createContext(sandbox);
vm.runInContext(src, ctx, { filename: 'app.js' });

const assert = (cond, msg) => { if (!cond) { console.error('FAIL: ' + msg); process.exit(1); } else console.log('PASS: ' + msg); };

vm.runInContext(`state.planCache = {}; LANG='fa'; calState.fa={jy:1405,jm:9};`, ctx);

(async () => {
  await vm.runInContext(`loadCalendar()`, ctx);
  const grid = els['cal-grid'];
  assert(!!grid, 'cal-grid element exists');
  const cells = grid.children;
  assert(cells.length === 30, 'Jalali month has 30 day cells (got ' + cells.length + ')');

  const dotsOf = (list, day) => {
    const c = list.find(x => x.dataset.day === String(day));
    return c ? c.querySelector('.dots').children : [];
  };

  // day 1 (Gregorian 2026-11-22) → 1 record → 1 dot
  let d = dotsOf(cells, 1);
  assert(d.length === 1 && d[0].textContent === '', 'Jalali day 1 (1 rec) shows exactly 1 dot');

  // day 2 → 6 records → 5 dots + +1
  d = dotsOf(cells, 2);
  assert(d.length === 6, 'Jalali day 2 (6 rec) shows 5 dots + +1 (got ' + d.length + ')');
  assert(d[5].className === 'dot-more' && d[5].textContent === '+1', 'Jalali day 2 +N = +1 (got "' + d[5].textContent + '")');

  // day 3 → exactly 5 records → 5 dots, no marker
  d = dotsOf(cells, 3);
  assert(d.length === 5 && !d.some(x => x.className === 'dot-more'), 'Jalali day 3 (5 rec) exactly 5 dots, no +N');

  // day 4 → 1 record
  d = dotsOf(cells, 4);
  assert(d.length === 1 && d[0].textContent === '', 'Jalali day 4 (1 rec) exactly 1 dot');

  // day 5 → 316 records → 5 dots + +311
  d = dotsOf(cells, 5);
  assert(d.length === 6, 'Jalali day 5 (316 rec) shows 5 + +1 (got ' + d.length + ')');
  assert(d[5].className === 'dot-more' && d[5].textContent === '+311', 'Jalali day 5 +N = +311 (got "' + d[5].textContent + '")');

  // day 6 → 347 records → 5 dots + +342
  d = dotsOf(cells, 6);
  assert(d.length === 6, 'Jalali day 6 (347 rec) shows 5 + +1 (got ' + d.length + ')');
  assert(d[5].className === 'dot-more' && d[5].textContent === '+342', 'Jalali day 6 +N = +342 (got "' + d[5].textContent + '")');

  // 0-record day (day 10) → no dots
  d = dotsOf(cells, 10);
  assert(d.length === 0, 'Jalali day with 0 records shows no dots');

  // Gregorian mode
  await vm.runInContext(`LANG='en'; calState.en={gy:2026,gm:11}; loadCalendar()`, ctx);
  const gcells = grid.children;
  assert(gcells.length === 30, 'Gregorian 2026-11 has 30 cells (got ' + gcells.length + ')');
  d = dotsOf(gcells, 26);
  assert(d.length === 6 && d[5].className === 'dot-more' && d[5].textContent === '+311', 'Gregorian day 26 (316 rec): 5 dots + +311 (got "' + (d[5]||{}).textContent + '")');

  console.log('\nALL CALENDAR DENSITY CHECKS PASSED');
})();
