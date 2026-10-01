'use strict';

// POST /api/create-checkout-session
// Creates a Stripe-hosted Checkout Session for one Instant Service or Care Plan and returns { url }.
// Needs only STRIPE_SECRET_KEY (Vercel environment variable). No npm dependencies: it calls Stripe's REST API directly.
// The publishable key is not needed because the browser is redirected to Stripe's hosted page.

const { CATALOG } = require('./_catalog');

const STRIPE_URL = 'https://api.stripe.com/v1/checkout/sessions';
const DEFAULT_SITE = 'https://favorableodds.io';
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX = { name: 100, email: 254, business: 200, details: 4000, notes: 1000 };
const CHUNK = 500;          // Stripe metadata values are limited to 500 characters
const MAX_CHUNKS = 8;       // 8 x 500 = 4000 characters of intake details

function send(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.end(JSON.stringify(body));
}

function originOf(value) {
  try { return new URL(value).origin; } catch (e) { return null; }
}

// The origins this function will accept requests from, and may redirect customers back to.
function allowedOrigins(env) {
  const set = new Set([originOf(env.SITE_URL || DEFAULT_SITE)]);
  const base = set.values().next().value;
  if (base && base.startsWith('https://') && !base.startsWith('https://www.')) set.add(base.replace('https://', 'https://www.'));
  for (const host of [env.VERCEL_URL, env.VERCEL_BRANCH_URL]) if (host) set.add('https://' + host);
  set.delete(null);
  return set;
}

function str(value) {
  return typeof value === 'string' ? value.trim().replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '') : '';
}

function parseBody(req) {
  let body = req.body;
  if (Buffer.isBuffer(body)) body = body.toString('utf8');
  if (typeof body === 'string') { try { body = JSON.parse(body); } catch (e) { return null; } }
  return body && typeof body === 'object' ? body : null;
}

function validate(input) {
  const service = typeof input.service === 'string' ? input.service : '';
  if (!Object.prototype.hasOwnProperty.call(CATALOG, service)) return { error: 'unknown_service' };
  const clean = {
    service,
    name: str(input.name),
    email: str(input.email),
    business: str(input.business),
    details: str(input.details),
    notes: str(input.notes)
  };
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
    source: 'favorableodds.io/services'
  };
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
  p.set('success_url', origin + '/services/thanks?session_id={CHECKOUT_SESSION_ID}');
  p.set('cancel_url', origin + '/services?checkout=cancelled');
  p.set('customer_email', order.email);
  p.set('line_items[0][quantity]', '1');
  p.set('line_items[0][price_data][currency]', 'usd');
  p.set('line_items[0][price_data][unit_amount]', String(item.cents));
  p.set('line_items[0][price_data][product_data][name]', item.title);
  p.set('line_items[0][price_data][product_data][description]', item.blurb);
  if (item.recurring) p.set('line_items[0][price_data][recurring][interval]', 'month');

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

  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return send(res, 405, { error: 'method_not_allowed' });
  }

  const allowed = allowedOrigins(env);
  const requestOrigin = req.headers && req.headers.origin;
  if (requestOrigin && !allowed.has(requestOrigin)) return send(res, 403, { error: 'forbidden_origin' });
  const origin = requestOrigin || originOf(env.SITE_URL || DEFAULT_SITE);

  const key = env.STRIPE_SECRET_KEY || '';
  if (!/^(sk|rk)_(live|test)_/.test(key)) return send(res, 503, { error: 'payments_unavailable' });   // missing, or a publishable key pasted by mistake

  const body = parseBody(req);
  if (!body) return send(res, 400, { error: 'invalid_request' });
  const checked = validate(body);
  if (checked.error) return send(res, 400, { error: checked.error });
  const order = checked.value;
  const item = CATALOG[order.service];

  const controller = new AbortController();
  const timer = setTimeout(function () { controller.abort(); }, 10000);
  try {
    const response = await doFetch(STRIPE_URL, {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + key,
        'Content-Type': 'application/x-www-form-urlencoded',
        'Stripe-Version': '2024-06-20'
      },
      body: buildParams(order, item, origin).toString(),
      signal: controller.signal
    });
    const data = await response.json().catch(function () { return {}; });
    if (!response.ok || !data.url || typeof data.url !== 'string' || !data.url.startsWith('https://checkout.stripe.com/')) {
      // Log the error class only. Never log the request body, customer details or keys.
      console.error('stripe_checkout_failed', response.status, data && data.error && (data.error.type + '/' + (data.error.code || '')));
      return send(res, 502, { error: 'checkout_unavailable' });
    }
    return send(res, 200, { url: data.url, id: data.id });
  } catch (e) {
    console.error('stripe_checkout_error', e && e.name);
    return send(res, 502, { error: 'checkout_unavailable' });
  } finally {
    clearTimeout(timer);
  }
}

module.exports = function (req, res) { return handler(req, res); };
module.exports.handler = handler;
module.exports.buildParams = buildParams;
module.exports.validate = validate;
