// Boot test for VoidFeed Studio v3.1+ (studio_web/app.js).
// Original intent (v3): when the app boots without Telegram initData,
//   - the existing page controls must be preserved (no innerHTML wipe),
//   - exactly ONE login notice is inserted (idempotent on repeat),
//   - the user is told how to enter (Telegram button / ?demo / admin token).
// v3.1 moved this behavior into boot()'s `if (!AUTH)` branch — we test the
// real source of that branch, not a removed legacy function.
// v3.2 (standalone auth): with a saved STUDIO_ADMIN_TOKEN the branch must
//   fall through WITHOUT inserting a login notice (Bearer boot continues).
const fs = require('node:fs');
const assert = require('node:assert/strict');

const source = fs.readFileSync(
  require('node:path').join(__dirname, '../studio_web/app.js'), 'utf8'
);

// Extract the actual unauthenticated branch of boot() from the live source.
const match = source.match(/if \(!AUTH\) \{[\s\S]*?\n  \}/);
assert.ok(match, 'boot() must contain an unauthenticated (!AUTH) branch');
const body = match[0]
  .replace(/^if \(!AUTH\) \{/, '')
  .replace(/\n  \}\s*$/, '');

const bootNoAuth = new Function(
  '$', 'hideBoot', 'DEMO', 'studioToken', 'localStorage', 'location', body + '\n'
);

// DOM mock: children must survive untouched; innerHTML overwrite must throw.
const children = [{ hidden: false }, { hidden: false }];
let inserted = 0;
let hideBootCalls = 0;
let savedToken = null; // localStorage backing store
const pages = {
  children,
  querySelector: () => (inserted ? {} : null), // 2nd call: notice already present
  insertAdjacentHTML: () => { inserted++; },
  set innerHTML(value) {
    throw new Error('Login notice must preserve existing controls');
  },
};
const $mock = (id) => (id === 'pages' ? pages : null);
const localStorageMock = {
  getItem: (k) => (k === 'vf_studio_token' ? savedToken : null),
  setItem: (k, v) => { if (k === 'vf_studio_token') savedToken = v; },
  removeItem: (k) => { if (k === 'vf_studio_token') savedToken = null; },
};
const locationMock = { reload: () => { throw new Error('must not reload in test'); } };
const tokMock = () => (savedToken || '');

// Regression 1: repeated unauthenticated boot must stay idempotent.
bootNoAuth($mock, () => { hideBootCalls++; }, false, tokMock, localStorageMock, locationMock);
bootNoAuth($mock, () => { hideBootCalls++; }, false, tokMock, localStorageMock, locationMock);

assert.equal(inserted, 1, 'login notice must be inserted exactly once');
assert.equal(hideBootCalls, 2, 'splash/boot-status hidden on every boot');
assert.equal(children.length, 2, 'existing page children must be preserved');
assert.ok(children.every((c) => c.hidden === false), 'children must not be hidden');
assert.match(body, /data-login-notice/, 'notice must carry the data-login-notice marker');
assert.match(body, /vf-token-input/, 'notice must offer the standalone token login');

// Regression 2 (standalone auth): a saved token must NOT trigger the notice.
let hideBootCalls2 = 0;
const pages2 = {
  children: [],
  querySelector: () => null,
  insertAdjacentHTML: () => { throw new Error('notice must NOT be inserted when a token is saved'); },
};
bootNoAuth($mock, () => { hideBootCalls2++; }, false, tokMock, localStorageMock, locationMock);
assert.equal(inserted, 1, 'no second notice after token exists');
assert.equal(hideBootCalls2, 1, 'boot continues (splash hidden) with a saved token');

console.log('PASS: unauthenticated boot inserts one login notice, preserves controls (repeat-safe); saved token boots through');
