'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..', '..');
const files = ['api/_catalog.js', 'api/_shop.js', 'api/_stripe.js', 'api/create-checkout-session.js', 'api/create-shop-checkout.js', 'api/README.md',
  'services.html', 'bookkeeping.html', 'shop.html', 'services-thanks.html', 'shop-thanks.html', 'vercel.json'];

test('no Stripe secret, restricted or webhook keys are committed', () => {
  for (const f of files) {
    const text = fs.readFileSync(path.join(root, f), 'utf8');
    assert.doesNotMatch(text, /\b(sk|rk)_(live|test)_[A-Za-z0-9]{10,}/, f);
    assert.doesNotMatch(text, /\bwhsec_[A-Za-z0-9]{10,}/, f);
  }
});

test('the Stripe key is read only from the environment', () => {
  const src = fs.readFileSync(path.join(root, 'api/_stripe.js'), 'utf8');
  assert.match(src, /env\.STRIPE_SECRET_KEY/);
});

test('the browser never sends an amount to the server', () => {
  for (const f of ['services.html', 'bookkeeping.html']) {
    const html = fs.readFileSync(path.join(root, f), 'utf8');
    const body = html.match(/body: JSON\.stringify\(\{([^}]*)\}\)/);
    assert.ok(body, f + ': checkout request body not found');
    assert.doesNotMatch(body[1], /amount|price|cents/i, f);
  }
  const shop = fs.readFileSync(path.join(root, 'shop.html'), 'utf8');
  const m = shop.match(/body:JSON\.stringify\(\{items:cart\.map\(i=>\(\{([^}]*)\}\)\)\}\)/);
  assert.ok(m, 'shop checkout request body not found');
  assert.doesNotMatch(m[1], /amount|price|cents/i);
});
