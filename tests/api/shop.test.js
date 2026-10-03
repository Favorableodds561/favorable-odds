'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const shop = require('../../api/_shop');
const { handler, buildParams } = require('../../api/create-shop-checkout');

const ENV = { STRIPE_SECRET_KEY: 'sk_test_' + 'x'.repeat(24) };
const ONE = { items: [{ id: 'koi', size: 'L', qty: 1 }] };

function fakeRes() {
  return { statusCode: 0, headers: {}, body: '', setHeader(k, v) { this.headers[k] = v; }, end(b) { this.body = b; }, json() { return JSON.parse(this.body); } };
}
// Fake Stripe: records every call; coupons and sessions succeed unless told otherwise.
function stripe({ couponOk = true, sessionOk = true } = {}) {
  const calls = [];
  const fn = async (u, init) => {
    calls.push({ u, init, form: new URLSearchParams(init.body) });
    if (u.endsWith('/coupons')) return { ok: couponOk, status: couponOk ? 200 : 400, json: async () => (couponOk ? { id: 'coupon_1' } : { error: { type: 'x' } }) };
    return { ok: sessionOk, status: sessionOk ? 200 : 400, json: async () => (sessionOk ? { id: 'cs_test_9', url: 'https://checkout.stripe.com/c/pay/cs_test_9' } : { error: { type: 'x' } }) };
  };
  fn.calls = calls;
  return fn;
}
async function call(body, deps = {}, req = {}) {
  const res = fakeRes();
  await handler(Object.assign({ method: 'POST', headers: {}, body }, req), res, Object.assign({ env: ENV, fetch: stripe() }, deps));
  return res;
}
const sessionCall = (f) => f.calls.find((c) => c.u.endsWith('/checkout/sessions'));

// ---- pricing -----------------------------------------------------------

test('pricing: singles, pairs, odd quantities and flat shipping', () => {
  assert.deepStrictEqual(shop.price(1), { subtotal: 3500, bundles: 0, discount: 0, shipping: 500, total: 4000 });
  assert.deepStrictEqual(shop.price(2), { subtotal: 7000, bundles: 1, discount: 1000, shipping: 500, total: 6500 });
  assert.strictEqual(shop.price(3).total, 6000 + 3500 + 500);
  assert.strictEqual(shop.price(4).total, 12000 + 500);
  assert.strictEqual(shop.price(5).discount, 2000);
});

// ---- drift guard against the real page ---------------------------------------

function pageShop() {
  const html = fs.readFileSync(path.join(__dirname, '..', '..', 'shop.html'), 'utf8');
  const cfg = html.match(/const CONFIG = \{[\s\S]*?\n\};/)[0];
  const prods = html.match(/const PRODUCTS = \[[\s\S]*?\n\];/)[0];
  const sizes = html.match(/const SIZES = \[[^\]]*\];/)[0];
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(cfg + '\n' + prods + '\n' + sizes + '\nthis.out = { CONFIG, PRODUCTS, SIZES };', ctx);
  return ctx.out;
}

test('shop.html and the server agree on products, sizes, prices, deal and shipping', () => {
  const page = pageShop();
  assert.deepStrictEqual([...page.PRODUCTS].map((p) => p.id).sort(), Object.keys(shop.PRODUCTS).sort());
  for (const p of page.PRODUCTS) {
    const s = shop.PRODUCTS[p.id];
    assert.strictEqual(s.title, p.title, p.id + ' title');
    assert.strictEqual(s.collection, p.collection, p.id + ' collection');
    assert.strictEqual(s.image, p.main, p.id + ' image');
    assert.strictEqual(p.price * 100, shop.TEE_CENTS, p.id + ' price');
    assert.ok(fs.existsSync(path.join(__dirname, '..', '..', s.image)), p.id + ' image file exists');
  }
  assert.deepStrictEqual([...page.SIZES], shop.SIZES);
  assert.strictEqual(page.CONFIG.teePrice * 100, shop.TEE_CENTS);
  assert.strictEqual(page.CONFIG.promo.bundleQty, shop.PROMO.qty);
  assert.strictEqual(page.CONFIG.promo.bundlePrice * 100, shop.PROMO.cents);
  assert.strictEqual(page.CONFIG.shippingFlat * 100, shop.SHIPPING_CENTS);
});

// ---- request validation ------------------------------------------------

test('invalid carts are rejected before anything reaches Stripe', async () => {
  const bad = [
    undefined, null, {}, { items: [] }, { items: 'koi' },
    { items: [{ id: 'nope', size: 'L', qty: 1 }] },
    { items: [{ id: '__proto__', size: 'L', qty: 1 }] },
    { items: [{ id: 'koi', size: 'XXL', qty: 1 }] },
    { items: [{ id: 'koi', size: 'L', qty: 0 }] },
    { items: [{ id: 'koi', size: 'L', qty: -1 }] },
    { items: [{ id: 'koi', size: 'L', qty: 1.5 }] },
    { items: [{ id: 'koi', size: 'L', qty: '2' }] },
    { items: [{ id: 'koi', size: 'L', qty: 11 }] },
    { items: [null] },
    { items: Array.from({ length: 21 }, () => ({ id: 'koi', size: 'L', qty: 1 })) },
    { items: ['S', 'M', 'L', 'XL', '2XL', '3XL'].flatMap((size) => ['koi', 'galaxy', 'success', 'fortuna'].map((id) => ({ id, size, qty: 2 }))).slice(0, 20) }
  ];
  for (const body of bad) {
    const f = stripe();
    const res = await call(body, { fetch: f });
    assert.strictEqual(res.statusCode, 400, String(JSON.stringify(body)).slice(0, 80));
    assert.strictEqual(f.calls.length, 0);
  }
});

test('same product and size across lines are merged and capped', async () => {
  const merged = shop.normalizeItems([{ id: 'koi', size: 'L', qty: 3 }, { id: 'koi', size: 'L', qty: 4 }]);
  assert.deepStrictEqual(merged.lines, [{ id: 'koi', size: 'L', qty: 7 }]);
  assert.strictEqual(shop.normalizeItems([{ id: 'koi', size: 'L', qty: 6 }, { id: 'koi', size: 'L', qty: 6 }]).error, 'invalid_quantity');
});

// ---- Stripe requests ---------------------------------------------------

test('a single tee: one session, no coupon, US-only flat shipping, Stripe Tax', async () => {
  const f = stripe();
  const res = await call(ONE, { fetch: f });
  assert.strictEqual(res.statusCode, 200);
  assert.strictEqual(res.json().url, 'https://checkout.stripe.com/c/pay/cs_test_9');
  assert.strictEqual(f.calls.length, 1);
  const p = sessionCall(f).form;
  assert.strictEqual(p.get('mode'), 'payment');
  assert.strictEqual(p.get('line_items[0][quantity]'), '1');
  assert.strictEqual(p.get('line_items[0][price_data][unit_amount]'), '3500');
  assert.strictEqual(p.get('line_items[0][price_data][product_data][name]'), 'Koi Collection Tee — Size L');
  assert.strictEqual(p.get('line_items[0][price_data][product_data][images][0]'), 'https://favorableodds.io/fo_koi_shirt_main.jpg');
  assert.strictEqual(p.get('discounts[0][coupon]'), null);
  assert.strictEqual(p.get('shipping_address_collection[allowed_countries][0]'), 'US');
  assert.strictEqual(p.get('shipping_address_collection[allowed_countries][1]'), null);
  assert.strictEqual(p.get('shipping_options[0][shipping_rate_data][fixed_amount][amount]'), '500');
  assert.strictEqual(p.get('shipping_options[0][shipping_rate_data][fixed_amount][currency]'), 'usd');
  assert.strictEqual(p.get('automatic_tax[enabled]'), 'true');
  assert.strictEqual(p.get('line_items[0][price_data][tax_behavior]'), 'exclusive');
  assert.match(p.get('custom_text[submit][message]'), /Pre-order/);
  assert.strictEqual(p.get('success_url'), 'https://favorableodds.io/shop/thanks?session_id={CHECKOUT_SESSION_ID}');
  assert.strictEqual(p.get('cancel_url'), 'https://favorableodds.io/shop.html?checkout=cancelled');
  assert.strictEqual(p.get('metadata[items]'), 'koi L x1');
});

test('two or more tees create the deal coupon first, then use it', async () => {
  const f = stripe();
  const res = await call({ items: [{ id: 'koi', size: 'L', qty: 1 }, { id: 'galaxy', size: 'M', qty: 2 }] }, { fetch: f });
  assert.strictEqual(res.statusCode, 200);
  assert.strictEqual(f.calls.length, 2);
  assert.ok(f.calls[0].u.endsWith('/coupons'));
  const c = f.calls[0].form;
  assert.strictEqual(c.get('amount_off'), '1000');           // 3 tees = one pair: 2 x $35 -> $60
  assert.strictEqual(c.get('currency'), 'usd');
  assert.strictEqual(c.get('duration'), 'once');
  assert.strictEqual(c.get('max_redemptions'), '1');
  const p = sessionCall(f).form;
  assert.strictEqual(p.get('discounts[0][coupon]'), 'coupon_1');
  assert.strictEqual(p.get('line_items[1][quantity]'), '2');
  assert.strictEqual(p.get('metadata[total_tees]'), '3');
  assert.strictEqual(p.get('metadata[deal_pairs]'), '1');
});

test('the customer total Stripe will charge equals the server price', async () => {
  for (const qty of [1, 2, 3, 4, 5, 9]) {
    const f = stripe();
    await call({ items: [{ id: 'success', size: 'M', qty: Math.min(qty, 10) }] }, { fetch: f });
    const p = sessionCall(f).form;
    const lines = Number(p.get('line_items[0][quantity]')) * Number(p.get('line_items[0][price_data][unit_amount]'));
    const off = f.calls.find((c) => c.u.endsWith('/coupons'));
    const total = lines - (off ? Number(off.form.get('amount_off')) : 0) + Number(p.get('shipping_options[0][shipping_rate_data][fixed_amount][amount]'));
    assert.strictEqual(total, shop.price(qty).total, 'qty ' + qty);
  }
});

test('client-supplied prices, shipping, coupons and countries are ignored', async () => {
  const f = stripe();
  await call({ ...ONE, amount: 1, price: 1, shipping: 0, coupon: 'FREE', countries: ['CA'], items: [{ id: 'koi', size: 'L', qty: 1, price: 1, unit_amount: 1 }] }, { fetch: f });
  const p = sessionCall(f).form;
  assert.strictEqual(p.get('line_items[0][price_data][unit_amount]'), '3500');
  assert.strictEqual(p.get('discounts[0][coupon]'), null);
  assert.strictEqual(p.get('shipping_options[0][shipping_rate_data][fixed_amount][amount]'), '500');
});

test('SHOP_AUTOMATIC_TAX=off disables Stripe Tax; anything else keeps it on', async () => {
  const off = stripe();
  await call(ONE, { fetch: off, env: { ...ENV, SHOP_AUTOMATIC_TAX: 'off' } });
  assert.strictEqual(sessionCall(off).form.get('automatic_tax[enabled]'), null);
  const on = stripe();
  await call(ONE, { fetch: on, env: { ...ENV, SHOP_AUTOMATIC_TAX: 'maybe' } });
  assert.strictEqual(sessionCall(on).form.get('automatic_tax[enabled]'), 'true');
});

// ---- gate and failures ---------------------------------------------------

test('503 without a usable key; 405 for GET; 403 for foreign origins', async () => {
  const f = stripe();
  assert.strictEqual((await call(ONE, { fetch: f, env: {} })).statusCode, 503);
  assert.strictEqual((await call(ONE, { fetch: f, env: { STRIPE_SECRET_KEY: 'pk_live_abc' } })).statusCode, 503);
  assert.strictEqual((await call(ONE, { fetch: f }, { method: 'GET' })).statusCode, 405);
  assert.strictEqual((await call(ONE, { fetch: f }, { headers: { origin: 'https://evil.example' } })).statusCode, 403);
  assert.strictEqual(f.calls.length, 0);
});

test('a failed coupon or session becomes a generic 502, and no session is made without the coupon', async () => {
  const two = { items: [{ id: 'koi', size: 'L', qty: 2 }] };
  const f1 = stripe({ couponOk: false });
  const r1 = await call(two, { fetch: f1 });
  assert.strictEqual(r1.statusCode, 502);
  assert.strictEqual(f1.calls.length, 1);
  assert.strictEqual((await call(ONE, { fetch: stripe({ sessionOk: false }) })).statusCode, 502);
  const boom = async () => { throw new Error('down'); };
  assert.strictEqual((await call(ONE, { fetch: boom })).statusCode, 502);
});

test('responses are not cached and never contain the key', async () => {
  const res = await call(ONE);
  assert.strictEqual(res.headers['Cache-Control'], 'no-store');
  assert.ok(!res.body.includes(ENV.STRIPE_SECRET_KEY));
});

test('buildParams keeps metadata values within Stripe limits for the largest cart', () => {
  const lines = ['S', 'M', 'L', 'XL', '2XL', '3XL'].flatMap((size) => Object.keys(shop.PRODUCTS).map((id) => ({ id, size, qty: 1 }))).slice(0, 20);
  const p = buildParams({ lines, totalQty: 20, price: shop.price(20) }, 'https://favorableodds.io', null, ENV);
  for (const [k, v] of p.entries()) if (k.startsWith('metadata[')) assert.ok(v.length <= 500, k);
});
