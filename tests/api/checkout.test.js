'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { handler, buildParams } = require('../../api/create-checkout-session');
const { CATALOG } = require('../../api/_catalog');

const GOOD = { service: 'data-rescue', name: 'Pat Doe', email: 'pat@example.com', business: 'Acme — Insurance', details: 'File type:\nxlsx', notes: '' };
const ENV = { STRIPE_SECRET_KEY: 'sk_test_' + 'x'.repeat(24) };

function fakeRes() {
  return { statusCode: 0, headers: {}, body: '', setHeader(k, v) { this.headers[k] = v; }, end(b) { this.body = b; }, json() { return JSON.parse(this.body); } };
}
function stripeOk(url = 'https://checkout.stripe.com/c/pay/cs_test_123') {
  const calls = [];
  const fn = async (u, init) => { calls.push({ u, init }); return { ok: true, status: 200, json: async () => ({ id: 'cs_test_123', url }) }; };
  fn.calls = calls;
  return fn;
}
async function call(req, deps) {
  const res = fakeRes();
  await handler(Object.assign({ method: 'POST', headers: {}, body: GOOD }, req), res, deps);
  return res;
}
const form = (c) => new URLSearchParams(c.init.body);

test('rejects non-POST methods', async () => {
  const res = await call({ method: 'GET' }, { env: ENV, fetch: stripeOk() });
  assert.strictEqual(res.statusCode, 405);
  assert.strictEqual(res.headers.Allow, 'POST');
});

test('503 when STRIPE_SECRET_KEY is missing, so the page can fall back to the email flow', async () => {
  const f = stripeOk();
  const res = await call({}, { env: {}, fetch: f });
  assert.strictEqual(res.statusCode, 503);
  assert.strictEqual(f.calls.length, 0);
});

test('a publishable key in the secret slot is refused, not sent to Stripe', async () => {
  const f = stripeOk();
  const res = await call({}, { env: { STRIPE_SECRET_KEY: 'pk_live_abc123' }, fetch: f });
  assert.strictEqual(res.statusCode, 503);
  assert.strictEqual(f.calls.length, 0);
});

test('one-time service creates a payment-mode session with the catalog price', async () => {
  const f = stripeOk();
  const res = await call({}, { env: ENV, fetch: f });
  assert.strictEqual(res.statusCode, 200);
  assert.strictEqual(res.json().url, 'https://checkout.stripe.com/c/pay/cs_test_123');
  assert.strictEqual(f.calls.length, 1);
  const c = f.calls[0];
  assert.strictEqual(c.u, 'https://api.stripe.com/v1/checkout/sessions');
  assert.strictEqual(c.init.headers.Authorization, 'Bearer ' + ENV.STRIPE_SECRET_KEY);
  const p = form(c);
  assert.strictEqual(p.get('mode'), 'payment');
  assert.strictEqual(p.get('line_items[0][price_data][unit_amount]'), '3700');
  assert.strictEqual(p.get('line_items[0][price_data][currency]'), 'usd');
  assert.strictEqual(p.get('line_items[0][quantity]'), '1');
  assert.strictEqual(p.get('line_items[0][price_data][recurring][interval]'), null);
  assert.strictEqual(p.get('customer_email'), 'pat@example.com');
  assert.strictEqual(p.get('success_url'), 'https://favorableodds.io/services/thanks?session_id={CHECKOUT_SESSION_ID}&from=services');
  assert.strictEqual(p.get('cancel_url'), 'https://favorableodds.io/services?checkout=cancelled');
  assert.strictEqual(p.get('metadata[service_key]'), 'data-rescue');
  assert.strictEqual(p.get('payment_intent_data[metadata][service_key]'), 'data-rescue');
});

test('care plan creates a monthly subscription', async () => {
  const f = stripeOk();
  const res = await call({ body: { ...GOOD, service: 'care-growth' } }, { env: ENV, fetch: f });
  assert.strictEqual(res.statusCode, 200);
  const p = form(f.calls[0]);
  assert.strictEqual(p.get('mode'), 'subscription');
  assert.strictEqual(p.get('line_items[0][price_data][unit_amount]'), '9900');
  assert.strictEqual(p.get('line_items[0][price_data][recurring][interval]'), 'month');
  assert.strictEqual(p.get('subscription_data[metadata][service_key]'), 'care-growth');
  assert.strictEqual(p.get('payment_intent_data[metadata][service_key]'), null);
});

test('client-supplied prices and extra fields are ignored', async () => {
  const f = stripeOk();
  await call({ body: { ...GOOD, amount: 1, price: '$0.01', cents: 1, unit_amount: 1, mode: 'setup' } }, { env: ENV, fetch: f });
  const p = form(f.calls[0]);
  assert.strictEqual(p.get('line_items[0][price_data][unit_amount]'), '3700');
  assert.strictEqual(p.get('mode'), 'payment');
});

test('every catalog item can be checked out and uses its own price', async () => {
  for (const [key, item] of Object.entries(CATALOG)) {
    const f = stripeOk();
    const res = await call({ body: { ...GOOD, service: key } }, { env: ENV, fetch: f });
    assert.strictEqual(res.statusCode, 200, key);
    const p = form(f.calls[0]);
    assert.strictEqual(p.get('line_items[0][price_data][unit_amount]'), String(item.cents), key);
    assert.strictEqual(p.get('mode'), item.recurring ? 'subscription' : 'payment', key);
  }
});

test('unknown services and prototype keys are rejected', async () => {
  for (const service of ['nope', '', '__proto__', 'constructor', 'toString', 5, null, undefined]) {
    const f = stripeOk();
    const res = await call({ body: { ...GOOD, service } }, { env: ENV, fetch: f });
    assert.strictEqual(res.statusCode, 400, String(service));
    assert.strictEqual(f.calls.length, 0);
  }
});

test('required fields and email format are validated', async () => {
  const cases = [{ name: '' }, { name: 'x'.repeat(101) }, { email: 'not-an-email' }, { email: 'a@b' }, { business: ' ' }, { email: 7 }];
  for (const bad of cases) {
    const f = stripeOk();
    const res = await call({ body: { ...GOOD, ...bad } }, { env: ENV, fetch: f });
    assert.strictEqual(res.statusCode, 400, JSON.stringify(bad));
    assert.strictEqual(f.calls.length, 0);
  }
});

test('malformed bodies are rejected', async () => {
  for (const body of [undefined, null, '{oops', 42]) {
    const res = await call({ body }, { env: ENV, fetch: stripeOk() });
    assert.strictEqual(res.statusCode, 400);
  }
});

test('a JSON string body is accepted', async () => {
  const res = await call({ body: JSON.stringify(GOOD) }, { env: ENV, fetch: stripeOk() });
  assert.strictEqual(res.statusCode, 200);
});

test('long intake details are split into <=500 char metadata values and capped', async () => {
  const f = stripeOk();
  await call({ body: { ...GOOD, details: 'a'.repeat(9000), notes: 'n'.repeat(900) } }, { env: ENV, fetch: f });
  const p = form(f.calls[0]);
  const meta = [...p.entries()].filter(([k]) => /^metadata\[/.test(k));
  assert.ok(meta.length <= 50);
  for (const [k, v] of meta) assert.ok(v.length <= 500, k);
  assert.strictEqual(p.get('metadata[details_8]').length, 500);
  assert.strictEqual(p.get('metadata[details_9]'), null);
  assert.strictEqual(p.get('metadata[notes]').length, 500);
});

test('other origins are refused; the site, www and Vercel preview origins are accepted', async () => {
  const f = stripeOk();
  const bad = await call({ headers: { origin: 'https://evil.example' } }, { env: ENV, fetch: f });
  assert.strictEqual(bad.statusCode, 403);
  assert.strictEqual(f.calls.length, 0);
  const www = await call({ headers: { origin: 'https://www.favorableodds.io' } }, { env: ENV, fetch: f });
  assert.strictEqual(www.statusCode, 200);
  assert.ok(form(f.calls[0]).get('success_url').startsWith('https://www.favorableodds.io/'));
  const prev = await call({ headers: { origin: 'https://fo-abc.vercel.app' } }, { env: { ...ENV, VERCEL_URL: 'fo-abc.vercel.app' }, fetch: f });
  assert.strictEqual(prev.statusCode, 200);
});

test('SITE_URL controls where customers come back to', async () => {
  const f = stripeOk();
  await call({}, { env: { ...ENV, SITE_URL: 'https://example.test/' }, fetch: f });
  assert.ok(form(f.calls[0]).get('cancel_url').startsWith('https://example.test/services'));
});

test('Stripe errors become a generic 502 with no details leaked', async () => {
  const f = async () => ({ ok: false, status: 400, json: async () => ({ error: { type: 'invalid_request_error', message: 'secret internal detail' } }) });
  const res = await call({}, { env: ENV, fetch: f });
  assert.strictEqual(res.statusCode, 502);
  assert.ok(!res.body.includes('secret'));
});

test('network failures and non-Stripe redirect URLs are treated as failures', async () => {
  const boom = async () => { throw new Error('down'); };
  assert.strictEqual((await call({}, { env: ENV, fetch: boom })).statusCode, 502);
  const res = await call({}, { env: ENV, fetch: stripeOk('https://evil.example/pay') });
  assert.strictEqual(res.statusCode, 502);
});

test('responses are never cached and the key never appears in them', async () => {
  const res = await call({}, { env: ENV, fetch: stripeOk() });
  assert.strictEqual(res.headers['Cache-Control'], 'no-store');
  assert.ok(!res.body.includes(ENV.STRIPE_SECRET_KEY));
});

test('buildParams is deterministic for a given order', () => {
  const a = buildParams({ ...GOOD, notes: '' }, CATALOG['data-rescue'], 'https://favorableodds.io').toString();
  const b = buildParams({ ...GOOD, notes: '' }, CATALOG['data-rescue'], 'https://favorableodds.io').toString();
  assert.strictEqual(a, b);
});

test('bookkeeping plans check out and return to the bookkeeping page', async () => {
  const f = stripeOk();
  const res = await call({ body: { ...GOOD, service: 'books-standard' } }, { env: ENV, fetch: f });
  assert.strictEqual(res.statusCode, 200);
  const p = form(f.calls[0]);
  assert.strictEqual(p.get('mode'), 'subscription');
  assert.strictEqual(p.get('line_items[0][price_data][unit_amount]'), '34900');
  assert.strictEqual(p.get('cancel_url'), 'https://favorableodds.io/bookkeeping?checkout=cancelled');
  assert.ok(p.get('success_url').endsWith('&from=bookkeeping'));
  assert.strictEqual(p.get('metadata[source]'), 'favorableodds.io/bookkeeping');
  const once = stripeOk();
  await call({ body: { ...GOOD, service: 'books-newllc' } }, { env: ENV, fetch: once });
  assert.strictEqual(form(once.calls[0]).get('mode'), 'payment');
});

test('the quoted Catch-Up Cleanup cannot be bought online', async () => {
  const f = stripeOk();
  const res = await call({ body: { ...GOOD, service: 'books-cleanup' } }, { env: ENV, fetch: f });
  assert.strictEqual(res.statusCode, 400);
  assert.strictEqual(f.calls.length, 0);
});
