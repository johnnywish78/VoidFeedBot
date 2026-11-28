// Jalali calendar behavior harness — loads the real app.js functions.
// Uses a minimal DOM stub for the functions that need it.
const fs = require('fs');
const vm = require('vm');

const src = fs.readFileSync('studio_web/app.js', 'utf8');

// Minimal DOM/document stubs so the file parses and defines the calendar fns.
const el = () => ({ innerHTML: '', textContent: '', style: {}, classList: { add(){}, remove(){} }, addEventListener(){}, querySelector(){ return null; }, querySelectorAll(){ return []; }, insertAdjacentHTML(){}, value: '', files: [], dataset: {}, checked: false, disabled: false, hidden: false, parentNode: null, remove(){}, classList: { add(){}, remove(){} } });
function makeEl() { return el(); }
const documentStub = {
  documentElement: { lang: 'fa' },
  getElementById: makeEl,
  querySelector: makeEl,
  querySelectorAll: () => [],
  createElement: makeEl,
  addEventListener(){},
  readyState: 'complete',
};
const sandbox = {
  window: { Telegram: null, history: { length: 0 }, addEventListener(){}, innerWidth: 800, innerHeight: 600 },
  document: documentStub,
  localStorage: { getItem(){ return null; }, setItem(){} },
  location: { search: '', reload(){} },
  URLSearchParams: class { has(){ return false; } },
  console: console,
  setTimeout, clearTimeout,
  Date, Math, Set, Object, Array, String, Number, RegExp, JSON, isNaN, parseInt, parseFloat,
  fetch: () => Promise.resolve({ json: () => Promise.resolve({}), ok: true }),
};
sandbox.window.Telegram = null;
const ctx = vm.createContext(sandbox);
vm.runInContext(src, ctx, { filename: 'app.js' });

// Now exercise the calendar math in the sandbox.
const out = vm.runInContext(`
(function () {
  const results = {};
  // Known conversion: 2026-11-24 (Gregorian) == 1405-09-03 (Jalali)
  const j = g2j(2026, 11, 24);  results.g2j_2026_11_24 = j;
  const g = j2g(j[0], j[1], j[2]);
  results.j2g_roundtrip = g;
  results.monthLen_1405_09 = jalaliMonthLen(1405, 9);   // آذر = 30
  results.monthLen_1405_12 = jalaliMonthLen(1405, 12);  // اسفند = 29 (1405 not leap)
  results.monthLen_1403_12 = jalaliMonthLen(1403, 12);  // 1403 leap → 30
  results.weekday_1405_09_03 = jalaliWeekday(1405, 9, 3); // Sat=0
  results.isLeap_1403 = isLeapJalali(1403);
  results.isLeap_1405 = isLeapJalali(1405);
  // buildCalendarMonth for a fixed month: set calState and LANG
  LANG = 'fa';
  calState.fa = { jy: 1405, jm: 9 };
  const mon = buildCalendarMonth();
  results.title_fa = mon.title;
  results.weekdays_fa = mon.weekdays;
  results.cellCount_fa = mon.cells.length;
  results.firstCell = mon.cells[0];
  results.keyOfDay1 = (mon.cells.find(c => !c.empty && c.day === 1) || {}).key;
  // English mode
  LANG = 'en';
  calState.en = { gy: 2026, gm: 11 };
  const men = buildCalendarMonth();
  results.title_en = men.title;
  results.weekdays_en = men.weekdays;
  return results;
})()
`, ctx);
console.log(JSON.stringify(out, null, 2));

// assertions
const ok = (cond, msg) => { if (!cond) { console.error('FAIL: ' + msg); process.exit(1); } else console.log('PASS: ' + msg); };
ok(out.g2j_2026_11_24[0] === 1405 && out.g2j_2026_11_24[1] === 9 && out.g2j_2026_11_24[2] === 3, 'g2j(2026-11-24) == 1405-09-03');
ok(out.j2g_roundtrip[0] === 2026 && out.j2g_roundtrip[1] === 11 && out.j2g_roundtrip[2] === 24, 'j2g roundtrip == 2026-11-24');
ok(out.monthLen_1405_09 === 30, 'آذر 1405 = 30 days');
ok(out.monthLen_1405_12 === 29, 'اسفند 1405 = 29 days (non-leap)');
ok(out.monthLen_1403_12 === 30, 'اسفند 1403 = 30 days (leap)');
ok(typeof out.weekday_1405_09_03 === 'number' && out.weekday_1405_09_03 >= 0 && out.weekday_1405_09_03 <= 6, 'jalaliWeekday returns 0..6');
ok(out.isLeap_1403 === true, '1403 is leap');
ok(out.isLeap_1405 === false, '1405 is not leap');
ok(out.title_fa.includes('آذر') && out.title_fa.includes('۱۴۰۵'), 'fa title uses Jalali month + Persian digits');
ok(Array.isArray(out.weekdays_fa) && out.weekdays_fa.length === 7 && out.weekdays_fa[0] === 'ش', 'fa weekdays Sat-first');
ok(out.keyOfDay1 === '2026-11-22' || out.keyOfDay1 === '2026-11-21', 'First Jalali day maps to correct Gregorian key');
ok(out.title_en.includes('November') && out.title_en.includes('2026'), 'en title Gregorian');
ok(Array.isArray(out.weekdays_en) && out.weekdays_en[0] === 'Sa', 'en weekdays Sat-first');
console.log('\nALL JALALI CHECKS PASSED');
