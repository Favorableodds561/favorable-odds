'use strict';
const test = require('node:test');
const assert = require('node:assert');
const session = require('../../api/checkout-session');
const billing = require('../../api/billing-portal');
const { handler: checkout } = require('../../api/create-checkout-session');

function fakeRes() {
  return { statusCode: 0, headers: {}, body: '', setHeader(k, v) { this.headers[k] = v; }, end(b) { this.body = b || ''; }, json() { return JSON.parse(this.body); } };
}
const KEY = { STRIPE_SECRET_KEY: 'sk_test_' + 'x'.repeat(24) };
const ID = 'cs_test_a1B2c3D4e5F6g7H8';
function stripeReturning(status, body) {
  const calls = [];
  const fn = async (u, init) => { calls.push({ u, method: init.method }); return { ok: status === 200, status, json: async () => body }; };
  fn.calls = calls;
  return fn;
}
async function lookup(fetch, id = ID, env = KEY) {
  const res = fakeRes();
  await session.handler({ method: 'GET', url: '/api/checkout-session?id=' + id, query: { id } }, res, { env, fetch });
  return res;
}

test('paid, processing and unfinished checkouts are reported, with no customer data', async () => {
  const paid = await lookup(stripeReturning(200, { status: 'complete', payment_status: 'paid', mode: 'payment', customer_details: { email: 'x@y.z' }, amount_total: 100, metadata: { source: 'favorableodds.io/shop' } }));
  assert.deepStrictEqual(paid.json(), { state: 'paid', kind: 'shop', subscription: false });
  assert.ok(!paid.body.includes('x@y.z'));
  const sub = await lookup(stripeReturning(200, { status: 'complete', payment_status: 'paid', mode: 'subscription', metadata: { source: 'favorableodds.io/bookkeeping' } }));
  assert.deepStrictEqual(sub.json(), { state: 'paid', kind: 'bookkeeping', subscription: true });
  const bank = await lookup(stripeReturning(200, { status: 'complete', payment_status: 'unpaid', metadata: {} }));
  assert.strictEqual(bank.json().state, 'processing');
  const open = await lookup(stripeReturning(200, { status: 'open', payment_status: 'unpaid', metadata: {} }));
  assert.strictEqual(open.json().state, 'not_completed');
});

test('lookups are read-only GETs to the right session', async () => {
  const f = stripeReturning(200, { status: 'complete', payment_status: 'paid', metadata: {} });
  await lookup(f);
  assert.deepStrictEqual(f.calls, [{ u: 'https://api.stripe.com/v1/checkout/sessions/' + ID, method: 'GET' }]);
});

test('malformed ids never reach Stripe; Stripe errors are reported as unknown or not found', async () => {
  for (const bad of ['', 'pi_123', 'cs_test_../account', 'cs_test_abc', 'cs_live_' + 'a'.repeat(300)]) {
    const f = stripeReturning(200, {});
    const res = await lookup(f, bad);
    assert.strictEqual(res.statusCode, 400, bad);
    assert.strictEqual(f.calls.length, 0);
  }
  assert.strictEqual((await lookup(stripeReturning(404, {}))).json().state, 'not_found');
  assert.strictEqual((await lookup(stripeReturning(500, {}))).json().state, 'unknown');
  assert.strictEqual((await lookup(stripeReturning(200, {}), ID, {})).statusCode, 503);
});

test('/billing goes to the Stripe portal when configured, otherwise to /manage-plan', () => {
  const go = (env) => { const res = fakeRes(); billing.handler({ method: 'GET' }, res, { env }); return res; };
  const on = go({ STRIPE_PORTAL_LOGIN_URL: 'https://billing.stripe.com/p/login/test_abc123' });
  assert.strictEqual(on.statusCode, 302);
  assert.strictEqual(on.headers.Location, 'https://billing.stripe.com/p/login/test_abc123');
  for (const env of [{}, { STRIPE_PORTAL_LOGIN_URL: 'https://evil.example/login' }, { STRIPE_PORTAL_LOGIN_URL: 'javascript:alert(1)' }]) {
    assert.strictEqual(go(env).headers.Location, '/manage-plan');
  }
});

// ---- annual care plans --------------------------------------------------------

function stripeOk() {
  const calls = [];
  const fn = async (u, init) => { calls.push(new URLSearchParams(init.body)); return { ok: true, status: 200, json: async () => ({ id: 'cs_test_1', url: 'https://checkout.stripe.com/c/pay/cs_test_1' }) }; };
  fn.calls = calls;
  return fn;
}
const ORDER = { name: 'Pat', email: 'pat@example.com', business: 'Acme', details: 'x' };
async function buy(body) {
  const f = stripeOk();
  const res = fakeRes();
  await checkout({ method: 'POST', headers: {}, body: { ...ORDER, ...body } }, res, { env: KEY, fetch: f });
  return { res, p: f.calls[0] };
}

test('annual care plans charge 10 months once a year', async () => {
  const { res, p } = await buy({ service: 'care-growth', billing: 'year' });
  assert.strictEqual(res.statusCode, 200);
  assert.strictEqual(p.get('mode'), 'subscription');
  assert.strictEqual(p.get('line_items[0][price_data][unit_amount]'), '99000');
  assert.strictEqual(p.get('line_items[0][price_data][recurring][interval]'), 'year');
  assert.strictEqual(p.get('line_items[0][price_data][product_data][name]'), 'Care Plan: Growth (annual)');
  assert.strictEqual(p.get('metadata[billing]'), 'annual');
});

test('monthly stays the default, and annual is refused where it is not offered', async () => {
  const m = await buy({ service: 'care-pro' });
  assert.strictEqual(m.p.get('line_items[0][price_data][recurring][interval]'), 'month');
  assert.strictEqual(m.p.get('metadata[billing]'), 'monthly');
  for (const service of ['books-starter', 'data-rescue', 'books-newllc']) {
    const r = await buy({ service, billing: 'year' });
    assert.strictEqual(r.res.statusCode, 400, service);
    assert.strictEqual(r.res.json().error, 'annual_not_available');
  }
  const odd = await buy({ service: 'care-pro', billing: 'weekly' });
  assert.strictEqual(odd.p.get('line_items[0][price_data][recurring][interval]'), 'month');
});
