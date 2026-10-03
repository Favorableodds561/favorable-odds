'use strict';

// POST /api/create-shop-checkout
// Body: { items: [{ id, size, qty }] }. Creates a Stripe-hosted Checkout Session for a shop order and returns { url }.
// US shipping only, flat shipping rate, "any 2 tees for $60" deal applied as a one-use coupon, tax calculated by Stripe Tax.
// Customers enter their name, email, shipping address and phone on Stripe's page, so the site never handles them.

const { PRODUCTS, TEE_CENTS, SHIPPING_CENTS, normalizeItems, price } = require('./_shop');
const { send, gate, parseBody, stripePost, isCheckoutUrl } = require('./_stripe');

const PREORDER = 'Pre-order: ships within 2–3 weeks of purchase. US addresses only.';

function buildParams(order, origin, couponId, env) {
  const p = new URLSearchParams();
  p.set('mode', 'payment');
  p.set('success_url', origin + '/shop/thanks?session_id={CHECKOUT_SESSION_ID}');
  p.set('cancel_url', origin + '/shop.html?checkout=cancelled');
  p.set('submit_type', 'pay');

  order.lines.forEach(function (l, i) {
    const prod = PRODUCTS[l.id];
    const pre = 'line_items[' + i + ']';
    p.set(pre + '[quantity]', String(l.qty));
    p.set(pre + '[price_data][currency]', 'usd');
    p.set(pre + '[price_data][unit_amount]', String(TEE_CENTS));
    p.set(pre + '[price_data][tax_behavior]', 'exclusive');
    p.set(pre + '[price_data][product_data][name]', prod.title + ' — Size ' + l.size);
    p.set(pre + '[price_data][product_data][description]', prod.collection + ' · pre-order');
    p.set(pre + '[price_data][product_data][images][0]', origin + '/' + prod.image);
  });

  if (couponId) p.set('discounts[0][coupon]', couponId);

  // US only, flat shipping per order.
  p.set('shipping_address_collection[allowed_countries][0]', 'US');
  p.set('phone_number_collection[enabled]', 'true');
  p.set('shipping_options[0][shipping_rate_data][type]', 'fixed_amount');
  p.set('shipping_options[0][shipping_rate_data][display_name]', 'Flat-rate shipping (US)');
  p.set('shipping_options[0][shipping_rate_data][fixed_amount][amount]', String(SHIPPING_CENTS));
  p.set('shipping_options[0][shipping_rate_data][fixed_amount][currency]', 'usd');
  p.set('shipping_options[0][shipping_rate_data][tax_behavior]', 'exclusive');

  // Stripe Tax is on unless explicitly switched off with SHOP_AUTOMATIC_TAX=off (see api/README.md).
  if (env.SHOP_AUTOMATIC_TAX !== 'off') p.set('automatic_tax[enabled]', 'true');

  p.set('custom_text[submit][message]', PREORDER);

  const summary = order.lines.map(function (l) { return l.id + ' ' + l.size + ' x' + l.qty; }).join('; ').slice(0, 500);
  const meta = { source: 'favorableodds.io/shop', items: summary, total_tees: String(order.totalQty), deal_pairs: String(order.price.bundles) };
  for (const [k, v] of Object.entries(meta)) {
    p.set('metadata[' + k + ']', v);
    p.set('payment_intent_data[metadata][' + k + ']', v);
  }
  p.set('payment_intent_data[description]', 'Favorable Odds Shop order (' + order.totalQty + ' tee' + (order.totalQty === 1 ? '' : 's') + ')');
  return p;
}

async function handler(req, res, deps) {
  const env = (deps && deps.env) || process.env;
  const doFetch = (deps && deps.fetch) || fetch;

  const g = gate(req, res, env);
  if (g.error) return send(res, g.status, { error: g.error });

  const body = parseBody(req);
  if (!body) return send(res, 400, { error: 'invalid_request' });
  const norm = normalizeItems(body.items);
  if (norm.error) return send(res, 400, { error: norm.error });
  const order = { lines: norm.lines, totalQty: norm.totalQty, price: price(norm.totalQty) };

  // The deal discount is a one-use fixed-amount coupon, so receipts show "2 for $60 deal" as its own line.
  let couponId = null;
  if (order.price.discount > 0) {
    const c = new URLSearchParams({
      amount_off: String(order.price.discount),
      currency: 'usd',
      duration: 'once',
      max_redemptions: '1',
      name: '2 for $60 deal'
    });
    const coupon = await stripePost(doFetch, g.key, 'coupons', c);
    if (!coupon.ok || !coupon.data.id) return send(res, 502, { error: 'checkout_unavailable' });
    couponId = coupon.data.id;
  }

  const result = await stripePost(doFetch, g.key, 'checkout/sessions', buildParams(order, g.origin, couponId, env));
  if (!result.ok || !isCheckoutUrl(result.data.url)) return send(res, 502, { error: 'checkout_unavailable' });
  return send(res, 200, { url: result.data.url, id: result.data.id });
}

module.exports = function (req, res) { return handler(req, res); };
module.exports.handler = handler;
module.exports.buildParams = buildParams;
