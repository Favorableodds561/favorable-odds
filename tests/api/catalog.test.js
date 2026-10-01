'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { CATALOG } = require('../../api/_catalog');

// Pull IS_SERVICES out of the real page so the price list can never silently drift from what customers see.
function pageServices() {
  const html = fs.readFileSync(path.join(__dirname, '..', '..', 'services.html'), 'utf8');
  const m = html.match(/var IS_SERVICES = \{[\s\S]*?\n\};/);
  assert.ok(m, 'IS_SERVICES not found in services.html');
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(m[0].replace(/^var /, 'this.') , ctx);
  return ctx.IS_SERVICES;
}

test('server catalog has exactly the services shown on the page', () => {
  assert.deepStrictEqual(Object.keys(CATALOG).sort(), Object.keys(pageServices()).sort());
});

test('server amounts, titles and billing type match the page', () => {
  const page = pageServices();
  for (const [key, item] of Object.entries(CATALOG)) {
    const p = page[key];
    assert.strictEqual(item.cents, Math.round(parseFloat(p.amount) * 100), key + ' amount');
    assert.strictEqual(item.title, p.title, key + ' title');
    assert.strictEqual(item.recurring, /\/mo$/.test(p.price), key + ' billing type');
    assert.strictEqual(p.price, '$' + (item.cents / 100) + (item.recurring ? '/mo' : ''), key + ' price label');
  }
});

test('every amount is a positive whole number of cents', () => {
  for (const [key, item] of Object.entries(CATALOG)) {
    assert.ok(Number.isInteger(item.cents) && item.cents >= 50, key);
  }
});
