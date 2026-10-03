'use strict';

// POST /api/create-checkout-session
// Creates a Stripe-hosted Checkout Session for one Instant Service, Care Plan or Bookkeeping plan and returns { url }.
// Needs only STRIPE_SECRET_KEY (Vercel environment variable). No npm dependencies: it calls Stripe's REST API directly.
// The publishable key is not needed because the browser is redirected to Stripe's hosted page.

const { CATALOG, ANNUAL_MONTHS_CHARGED } = require('./_catalog');
const { send, gate, str, parseBody, stripePost, isCheckoutUrl } = require('./_stripe');

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX = { name: 100, email: 254, business: 200, details: 4000, notes: 1000 };
const CHUNK = 500;          // Stripe metadata values are limited to 500 characters
const MAX_CHUNKS = 8;       // 8 x 500 = 4000 characters of intake details

function validate(input) {
  const service = typeof input.service === 'string' ? input.service : '';
  if (!Object.prototype.hasOwnProperty.call(CATALOG, service)) return { error: 'unknown_service' };
  const clean = {
    service,
    name: str(input.name),
    email: str(input.email),
    business: str(input.business),
    details: str(input.details),
    notes: str(input.notes),
    billing: input.billing === 'year' ? 'year' : 'month'
  };
  if (clean.billing === 'year' && !CATALOG[service].annual) return { error: 'annual_not_available' };
  if (!clean.name || clean.name.length > MAX.name) return { error: 'invalid_name' };
  if (!EMAIL_RE.test(clean.email) || clean.email.length > MAX.email) return { error: 'invalid_email' };
  if (!clean.business || clean.business.length > MAX.business) return { error: 'invalid_business' };
  if (clean.details.length > MAX.details) clean.details = clean.details.slice(0, MAX.details);
  if (clean.notes.length > MAX.notes) clean.notes = clean.notes.slice(0, MAX.notes);
  return { value: clean };
}

function metadataFor(order, item) {
  const meta = {
    service_key: order.service,
    service: item.title,
    customer_name: order.name.slice(0, CHUNK),
    business: order.business.slice(0, CHUNK),
    source: 'favorableodds.io/' + item.group
  };
  if (item.recurring) meta.billing = order.billing === 'year' ? 'annual' : 'monthly';
  if (order.notes) meta.notes = order.notes.slice(0, CHUNK);
  for (let i = 0; i * CHUNK < order.details.length && i < MAX_CHUNKS; i++) {
    meta['details_' + (i + 1)] = order.details.slice(i * CHUNK, (i + 1) * CHUNK);
  }
  return meta;
}

// Form-encoded body in the shape Stripe expects.
function buildParams(order, item, origin) {
  const p = new URLSearchParams();
  p.set('mode', item.recurring ? 'subscription' : 'payment');
  p.set('success_url', origin + '/services/thanks?session_id={CHECKOUT_SESSION_ID}&from=' + item.group);
  p.set('cancel_url', origin + '/' + item.group + '?checkout=cancelled');
  p.set('customer_email', order.email);
  p.set('line_items[0][quantity]', '1');
  p.set('line_items[0][price_data][currency]', 'usd');
  const yearly = item.recurring && order.billing === 'year';
  p.set('line_items[0][price_data][unit_amount]', String(yearly ? item.cents * ANNUAL_MONTHS_CHARGED : item.cents));
  p.set('line_items[0][price_data][product_data][name]', item.title + (yearly ? ' (annual)' : ''));
  p.set('line_items[0][price_data][product_data][description]', item.blurb);
  if (item.recurring) p.set('line_items[0][price_data][recurring][interval]', yearly ? 'year' : 'month');

  const meta = metadataFor(order, item);
  for (const [k, v] of Object.entries(meta)) {
    p.set('metadata[' + k + ']', v);
    // Copy to the payment / subscription so the details are visible wherever the dashboard is opened from.
    p.set((item.recurring ? 'subscription_data' : 'payment_intent_data') + '[metadata][' + k + ']', v);
  }
  if (!item.recurring) p.set('payment_intent_data[description]', item.title + ' for ' + order.business.slice(0, 100));
  return p;
}

async function handler(req, res, deps) {
  const env = (deps && deps.env) || process.env;
  const doFetch = (deps && deps.fetch) || fetch;

  const g = gate(req, res, env);
  if (g.error) return send(res, g.status, { error: g.error });

  const body = parseBody(req);
  if (!body) return send(res, 400, { error: 'invalid_request' });
  const checked = validate(body);
  if (checked.error) return send(res, 400, { error: checked.error });
  const order = checked.value;
  const item = CATALOG[order.service];

  const result = await stripePost(doFetch, g.key, 'checkout/sessions', buildParams(order, item, g.origin));
  if (!result.ok || !isCheckoutUrl(result.data.url)) return send(res, 502, { error: 'checkout_unavailable' });
  return send(res, 200, { url: result.data.url, id: result.data.id });
}

module.exports = function (req, res) { return handler(req, res); };
module.exports.handler = handler;
module.exports.buildParams = buildParams;
module.exports.validate = validate;
