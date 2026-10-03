'use strict';
const test = require('node:test');
const assert = require('node:assert');
const crypto = require('node:crypto');
const { Readable } = require('node:stream');
const { handler, verifySignature, orderEmail } = require('../../api/stripe-webhook');
const { EMAILJS_URL } = require('../../api/_notify');

const SECRET = 'whsec_' + 'k'.repeat(32);
const ENV = { STRIPE_WEBHOOK_SECRET: SECRET, EMAILJS_PRIVATE_KEY: 'emailjs-private' };
const NOW = 1790000000;

function sign(body, t = NOW, secret = SECRET) {
  return 't=' + t + ',v1=' + crypto.createHmac('sha256', secret).update(t + '.' + body).digest('hex');
}
// A request like Vercel's: a readable stream of the raw bytes.
function request(body, headers = {}) {
  const req = Readable.from([Buffer.from(body)]);
  req.method = 'POST';
  req.headers = headers;
  return req;
}
function fakeRes() {
  return { statusCode: 0, headers: {}, body: '', setHeader(k, v) { this.headers[k] = v; }, end(b) { this.body = b; }, json() { return JSON.parse(this.body); } };
}
function emailjs(ok = true) {
  const calls = [];
  const fn = async (u, init) => { calls.push({ u, body: JSON.parse(init.body) }); return { ok, status: ok ? 200 : 400, text: async () => (ok ? 'OK' : 'bad') }; };
  fn.calls = calls;
  return fn;
}
async function deliver(event, { env = ENV, fetch = emailjs(), sigOverride, t = NOW } = {}) {
  const body = JSON.stringify(event);
  const res = fakeRes();
  await handler(request(body, { 'stripe-signature': sigOverride || sign(body, t) }), res, { env, fetch, now: () => NOW });
  return { res, fetch };
}

const serviceSession = {
  id: 'cs_test_svc', object: 'checkout.session', mode: 'payment', status: 'complete', payment_status: 'paid', amount_total: 3700,
  customer_email: 'pat@example.com', customer_details: { email: 'pat@example.com', name: 'Pat Doe' }, total_details: {},
  metadata: { service_key: 'data-rescue', service: 'Data Rescue', customer_name: 'Pat Doe', business: 'Acme', source: 'favorableodds.io/services', details_1: 'File type:\nxlsx\n\n', details_2: 'Rows:\n500', notes: 'rush please' }
};
const shopSession = {
  id: 'cs_test_shop', object: 'checkout.session', mode: 'payment', status: 'complete', payment_status: 'paid', amount_total: 10600,
  customer_details: { email: 'sam@example.com', name: 'Sam Lee', phone: '+15555550100' },
  shipping_details: { name: 'Sam Lee', address: { line1: '1 Main St', line2: 'Apt 2', city: 'Tampa', state: 'FL', postal_code: '33601', country: 'US' } },
  total_details: { amount_discount: 1000, amount_shipping: 500, amount_tax: 600 },
  metadata: { source: 'favorableodds.io/shop', items: 'koi L x2; galaxy M x1', total_tees: '3', deal_pairs: '1' }
};
const ev = (type, object, livemode = false) => ({ id: 'evt_1', type, livemode, data: { object } });

// ---- signature -----------------------------------------------------------

test('valid signatures pass; tampered body, wrong secret, old timestamps and junk fail', () => {
  const body = Buffer.from('{"a":1}');
  assert.ok(verifySignature(body, sign('{"a":1}'), SECRET, NOW));
  assert.ok(verifySignature(body, 't=' + NOW + ',v1=' + '0'.repeat(64) + ',' + sign('{"a":1}').split(',')[1], SECRET, NOW), 'any matching v1 is enough');
  assert.ok(!verifySignature(Buffer.from('{"a":2}'), sign('{"a":1}'), SECRET, NOW));
  assert.ok(!verifySignature(body, sign('{"a":1}', NOW, 'whsec_other'), SECRET, NOW));
  assert.ok(!verifySignature(body, sign('{"a":1}', NOW - 301), SECRET, NOW));
  assert.ok(!verifySignature(body, sign('{"a":1}', NOW + 301), SECRET, NOW));
  for (const h of ['', 'garbage', 't=abc,v1=00', 't=' + NOW, 'v1=' + 'a'.repeat(64), 't=' + NOW + ',v1=zz']) assert.ok(!verifySignature(body, h, SECRET, NOW), h);
});

test('bad signatures are rejected with 400 and nothing is emailed', async () => {
  const { res, fetch } = await deliver(ev('checkout.session.completed', serviceSession), { sigOverride: 't=' + NOW + ',v1=' + 'a'.repeat(64) });
  assert.strictEqual(res.statusCode, 400);
  assert.strictEqual(fetch.calls.length, 0);
});

test('a missing webhook secret is a 503; GET is a 405', async () => {
  const a = await deliver(ev('checkout.session.completed', serviceSession), { env: { EMAILJS_PRIVATE_KEY: 'x' } });
  assert.strictEqual(a.res.statusCode, 503);
  const res = fakeRes();
  await handler(Object.assign(request(''), { method: 'GET' }), res, { env: ENV, fetch: emailjs() });
  assert.strictEqual(res.statusCode, 405);
});

// ---- emails ----------------------------------------------------------------

test('a paid service order emails the intake details through EmailJS', async () => {
  const { res, fetch } = await deliver(ev('checkout.session.completed', serviceSession));
  assert.strictEqual(res.statusCode, 200);
  assert.strictEqual(fetch.calls.length, 1);
  const { u, body } = fetch.calls[0];
  assert.strictEqual(u, EMAILJS_URL);
  assert.strictEqual(body.accessToken, 'emailjs-private');
  assert.strictEqual(body.service_id, 'service_blx7dqd');
  assert.strictEqual(body.template_id, 'template_lbtqhem');
  const p = body.template_params;
  assert.strictEqual(p.service, '[TEST] Data Rescue');
  assert.match(p.price, /^PAID: \$37\.00$/);
  assert.strictEqual(p.details, 'File type:\nxlsx\n\nRows:\n500');
  assert.strictEqual(p.business, 'Acme');
  assert.strictEqual(p.reply_to, 'pat@example.com');
  assert.match(p.notes, /rush please/);
  assert.match(p.notes, /cs_test_svc/);
});

test('live orders are not marked [TEST]; subscriptions show per month', () => {
  const p = orderEmail(ev('checkout.session.completed', { ...serviceSession, mode: 'subscription', amount_total: 9900, metadata: { ...serviceSession.metadata, service: 'Care Plan: Growth' } }, true));
  assert.strictEqual(p.service, 'Care Plan: Growth');
  assert.match(p.price, /^PAID: \$99\.00 per month$/);
});

test('a paid shop order emails items, totals and the shipping address', async () => {
  const { fetch } = await deliver(ev('checkout.session.completed', shopSession));
  const p = fetch.calls[0].body.template_params;
  assert.strictEqual(p.service, '[TEST] Shop order (3 tees)');
  assert.strictEqual(p.price, 'PAID: $106.00 (discount -$10.00, shipping $5.00, tax $6.00)');
  assert.match(p.details, /Items: koi L x2; galaxy M x1/);
  assert.match(p.details, /Ship to:\nSam Lee\n1 Main St\nApt 2\nTampa, FL 33601\nUS/);
  assert.match(p.details, /Phone: \+15555550100/);
  assert.strictEqual(p.from_name, 'Sam Lee');
});

test('newer API versions put shipping under collected_information', () => {
  const s = { ...shopSession, shipping_details: undefined, collected_information: { shipping_details: { name: 'Kim', address: { line1: '9 Oak', city: 'Miami', state: 'FL', postal_code: '33101', country: 'US' } } } };
  assert.match(orderEmail(ev('checkout.session.completed', s)).details, /Ship to:\nKim\n9 Oak\nMiami, FL 33101/);
});

test('bank payments: processing first, then paid or failed', () => {
  const unpaid = { ...serviceSession, payment_status: 'unpaid' };
  assert.match(orderEmail(ev('checkout.session.completed', unpaid)).price, /^PAYMENT PROCESSING/);
  assert.match(orderEmail(ev('checkout.session.async_payment_succeeded', serviceSession)).price, /^PAID \(bank payment cleared\)/);
  assert.match(orderEmail(ev('checkout.session.async_payment_failed', unpaid)).price, /^PAYMENT FAILED/);
});

test('other events are acknowledged and ignored', async () => {
  const { res, fetch } = await deliver(ev('payment_intent.created', { id: 'pi_1' }));
  assert.strictEqual(res.statusCode, 200);
  assert.strictEqual(res.json().handled, false);
  assert.strictEqual(fetch.calls.length, 0);
});

test('EmailJS failure returns 500 so Stripe retries; no private key is acknowledged without retry', async () => {
  const failed = await deliver(ev('checkout.session.completed', serviceSession), { fetch: emailjs(false) });
  assert.strictEqual(failed.res.statusCode, 500);
  const unset = await deliver(ev('checkout.session.completed', serviceSession), { env: { STRIPE_WEBHOOK_SECRET: SECRET } });
  assert.strictEqual(unset.res.statusCode, 200);
  assert.strictEqual(unset.res.json().emailed, false);
  assert.strictEqual(unset.fetch.calls.length, 0);
});

test('a body Vercel already parsed into an object cannot be verified and is refused', async () => {
  const req = Readable.from([]);
  req.method = 'POST';
  req.headers = { 'stripe-signature': sign('{}') };
  req.body = { already: 'parsed' };
  const res = fakeRes();
  await handler(req, res, { env: ENV, fetch: emailjs(), now: () => NOW });
  assert.strictEqual(res.statusCode, 400);
  assert.strictEqual(res.json().error, 'raw_body_unavailable');
});
