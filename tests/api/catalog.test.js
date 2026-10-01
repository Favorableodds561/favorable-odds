'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { CATALOG } = require('../../api/_catalog');

// Pull IS_SERVICES out of the real pages so the price list can never silently drift from what customers see.
function pageServices(file) {
  const html = fs.readFileSync(path.join(__dirname, '..', '..', file), 'utf8');
  const m = html.match(/var IS_SERVICES = \{[\s\S]*?\n\};/);
  assert.ok(m, 'IS_SERVICES not found in ' + file);
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(m[0].replace(/^var /, 'this.'), ctx);
  return ctx.IS_SERVICES;
}

// Everything sold online: all services.html entries, and every bookkeeping.html entry that is not quote-only.
function onlineItems() {
  const out = {};
  for (const [file, group] of [['services.html', 'services'], ['bookkeeping.html', 'bookkeeping']]) {
    for (const [key, p] of Object.entries(pageServices(file))) if (!p.quote) out[key] = Object.assign({ group }, p);
  }
  return out;
}

test('server catalog has exactly the services shown on the page', () => {
  assert.deepStrictEqual(Object.keys(CATALOG).sort(), Object.keys(onlineItems()).sort());
});

test('server amounts, titles and billing type match the page', () => {
  const page = onlineItems();
  for (const [key, item] of Object.entries(CATALOG)) {
    const p = page[key];
    assert.strictEqual(item.cents, Math.round(parseFloat(p.amount) * 100), key + ' amount');
    assert.strictEqual(item.title, p.title, key + ' title');
    assert.strictEqual(item.recurring, /\/mo$/.test(p.price), key + ' billing type');
    assert.strictEqual(item.group, p.group, key + ' page');
    assert.strictEqual(p.price, '$' + (item.cents / 100) + (item.recurring ? '/mo' : ''), key + ' price label');
  }
});

test('every amount is a positive whole number of cents', () => {
  for (const [key, item] of Object.entries(CATALOG)) {
    assert.ok(Number.isInteger(item.cents) && item.cents >= 50, key);
  }
});

test('quote-only plans are never sold online', () => {
  const quotes = Object.entries(pageServices('bookkeeping.html')).filter(([, p]) => p.quote).map(([k]) => k);
  assert.deepStrictEqual(quotes, ['books-cleanup']);
  for (const k of quotes) assert.ok(!(k in CATALOG), k);
});
