'use strict';
const test = require('node:test');
const assert = require('node:assert');
const status = require('../../api/checkout-status');
const { handler, keyState } = status;
const { allowedOrigins } = require('../../api/_stripe');

function fakeRes() {
  return { statusCode: 0, headers: {}, body: '', setHeader(k, v) { this.headers[k] = v; }, end(b) { this.body = b; }, json() { return JSON.parse(this.body); } };
}
const KEY = 'sk_test_' + 'x'.repeat(24);
// Fake Stripe: account and tax settings responses can be overridden.
function stripe({ account = { ok: true, status: 200, body: { charges_enabled: true } }, tax = { ok: true, status: 200, body: { status: 'active' } } } = {}) {
  const calls = [];
  const fn = async (u, init) => {
    calls.push({ u, method: init.method });
    const r = u.endsWith('/account') ? account : tax;
    return { ok: r.ok, status: r.status, json: async () => r.body };
  };
  fn.calls = calls;
  return fn;
}
async function call(deps, req = {}) {
  if (!deps.now) status._resetCache();   // each case starts cold unless it is testing the cache
  const res = fakeRes();
  await handler(Object.assign({ method: 'GET', headers: { host: 'favorableodds.io' } }, req), res, deps);
  return res;
}

test('key states are classified without exposing the key', () => {
  assert.strictEqual(keyState(''), 'missing');
  assert.strictEqual(keyState('pk_live_abc'), 'publishable_key_in_secret_slot');
  assert.strictEqual(keyState('sk_test_abc'), 'test');
  assert.strictEqual(keyState('rk_live_abc'), 'live');
  assert.strictEqual(keyState('hello'), 'invalid_format');
});

test('a missing key is reported with a hint and Stripe is never called', async () => {
  const f = stripe();
  const res = await call({ env: {}, fetch: f });
  const body = res.json();
  assert.strictEqual(body.stripeKey, 'missing');
  assert.strictEqual(body.ready, false);
  assert.match(body.hints.join(' '), /STRIPE_SECRET_KEY is not set/);
  assert.strictEqual(f.calls.length, 0);
});

test('a fully configured account reports ready, creates nothing, and leaks nothing', async () => {
  const f = stripe();
  const res = await call({ env: { STRIPE_SECRET_KEY: KEY }, fetch: f });
  const body = res.json();
  assert.strictEqual(body.ready, true);
  assert.strictEqual(body.stripeKey, 'test');
  assert.strictEqual(body.chargesEnabled, true);
  assert.strictEqual(body.shopTax.stripeTaxStatus, 'active');
  assert.ok(f.calls.every((c) => c.method === 'GET'), 'read-only');
  assert.ok(!res.body.includes(KEY));
  assert.strictEqual(res.headers['Cache-Control'], 'no-store');
});

test('inactive Stripe Tax is explained, with the missing items', async () => {
  const tax = { ok: true, status: 200, body: { status: 'pending', status_details: { pending: { missing_fields: ['head_office'] } } } };
  const body = (await call({ env: { STRIPE_SECRET_KEY: KEY }, fetch: stripe({ tax }) })).json();
  assert.strictEqual(body.ready, false);
  assert.deepStrictEqual(body.shopTax.missing, ['head_office']);
  assert.match(body.hints.join(' '), /Stripe Tax is not active/);
});

test('SHOP_AUTOMATIC_TAX=off skips the tax check', async () => {
  const f = stripe({ tax: { ok: false, status: 403, body: {} } });
  const body = (await call({ env: { STRIPE_SECRET_KEY: KEY, SHOP_AUTOMATIC_TAX: 'off' }, fetch: f })).json();
  assert.strictEqual(body.shopTax.setting, 'off');
  assert.ok(!f.calls.some((c) => c.u.endsWith('/tax/settings')));
  assert.strictEqual(body.ready, true);
});

test('a rejected key and an account that cannot take charges are reported', async () => {
  const rejected = (await call({ env: { STRIPE_SECRET_KEY: KEY }, fetch: stripe({ account: { ok: false, status: 401, body: {} } }) })).json();
  assert.strictEqual(rejected.stripeReachable, false);
  assert.match(rejected.hints.join(' '), /rejected the key/);
  const noCharges = (await call({ env: { STRIPE_SECRET_KEY: KEY }, fetch: stripe({ account: { ok: true, status: 200, body: { charges_enabled: false } } }) })).json();
  assert.match(noCharges.hints.join(' '), /cannot take charges/);
});

test('an address that checkout would refuse is flagged', async () => {
  const body = (await call({ env: { STRIPE_SECRET_KEY: KEY }, fetch: stripe() }, { headers: { host: 'something-else.example' } })).json();
  assert.strictEqual(body.thisAddressAllowed, false);
  assert.match(body.hints.join(' '), /refused/);
});

test('only GET is allowed', async () => {
  const res = await call({ env: {}, fetch: stripe() }, { method: 'POST' });
  assert.strictEqual(res.statusCode, 405);
});

test('Vercel project, branch and deployment addresses are accepted origins', () => {
  const set = allowedOrigins({ VERCEL_URL: 'a-123.vercel.app', VERCEL_BRANCH_URL: 'a-git-x.vercel.app', VERCEL_PROJECT_PRODUCTION_URL: 'a.vercel.app' });
  for (const h of ['a-123.vercel.app', 'a-git-x.vercel.app', 'a.vercel.app', 'favorableodds.io', 'www.favorableodds.io']) assert.ok(set.has('https://' + h), h);
  assert.ok(!set.has('https://evil.vercel.app'));
});

test('order-email, webhook and customer-portal setup is reported separately from payment readiness', async () => {
  const bare = (await call({ env: { STRIPE_SECRET_KEY: KEY }, fetch: stripe() })).json();
  assert.strictEqual(bare.ready, true, 'payments still work without the extras');
  assert.deepStrictEqual(bare.extras, { orderEmails: false, webhookSecret: false, emailjsPrivateKey: false, customerPortal: false });
  assert.strictEqual(bare.recommended.length, 3);
  const full = (await call({ env: { STRIPE_SECRET_KEY: KEY, STRIPE_WEBHOOK_SECRET: 'whsec_abc', EMAILJS_PRIVATE_KEY: 'p', STRIPE_PORTAL_LOGIN_URL: 'https://billing.stripe.com/p/login/x' }, fetch: stripe() })).json();
  assert.deepStrictEqual(full.extras, { orderEmails: true, webhookSecret: true, emailjsPrivateKey: true, customerPortal: true });
  assert.deepStrictEqual(full.recommended, []);
  const raw = JSON.stringify(full);
  assert.ok(!raw.includes('whsec_abc') && !raw.includes('"p"'), 'secrets are never echoed');
});

test('Stripe probes are cached for a minute, so repeated visits do not spend the Stripe rate limit', async () => {
  status._resetCache();
  let t = 1000000;
  const f = stripe();
  for (let i = 0; i < 10; i++) {
    const body = (await call({ env: { STRIPE_SECRET_KEY: KEY }, fetch: f, now: () => t })).json();
    assert.strictEqual(body.ready, true);
  }
  assert.strictEqual(f.calls.length, 2, 'one account and one tax call for ten visits');
  t += 61000;
  await call({ env: { STRIPE_SECRET_KEY: KEY }, fetch: f, now: () => t });
  assert.strictEqual(f.calls.length, 4, 'refreshed after a minute');
  const other = stripe();
  await call({ env: { STRIPE_SECRET_KEY: 'sk_live_' + 'y'.repeat(24) }, fetch: other, now: () => t });
  assert.strictEqual(other.calls.length, 2, 'a different key is never answered from another key\'s cache');
});
