'use strict';

// POST /api/stripe-webhook
// Stripe calls this after a Checkout payment. It verifies Stripe's signature, then emails the order to the business inbox
// (same EmailJS template as the site forms) marked PAID, PAYMENT PROCESSING or PAYMENT FAILED, with the customer's intake
// details or shipping address. Stripe retries if this returns an error, so a temporary email failure is not lost.
//
// Setup (see api/README.md): Stripe > Developers > Webhooks > add endpoint https://favorableodds.io/api/stripe-webhook with the
// events checkout.session.completed, checkout.session.async_payment_succeeded and checkout.session.async_payment_failed.
// Put its signing secret (whsec_...) in STRIPE_WEBHOOK_SECRET, and the EmailJS private key in EMAILJS_PRIVATE_KEY.

const crypto = require('crypto');
const { send } = require('./_stripe');
const { sendOrderEmail } = require('./_notify');

const TOLERANCE_SECONDS = 300;
const HANDLED = {
  'checkout.session.completed': true,
  'checkout.session.async_payment_succeeded': true,
  'checkout.session.async_payment_failed': true
};

// Stripe needs the exact bytes it signed, so read the raw request stream instead of a parsed body.
async function readRawBody(req) {
  const chunks = [];
  try {
    for await (const chunk of req) chunks.push(typeof chunk === 'string' ? Buffer.from(chunk) : chunk);
  } catch (e) { /* fall through to any buffered body */ }
  if (chunks.length) return Buffer.concat(chunks);
  if (Buffer.isBuffer(req.rawBody)) return req.rawBody;
  if (Buffer.isBuffer(req.body)) return req.body;
  if (typeof req.body === 'string') return Buffer.from(req.body);
  return null;   // only a parsed object is left: the signature can't be checked
}

// Stripe-Signature: t=<unix seconds>,v1=<hex hmac>[,v1=...]. Signed payload is "<t>.<raw body>" with the endpoint secret.
function verifySignature(raw, header, secret, nowSeconds) {
  if (!raw || !header || !secret) return false;
  let timestamp = null;
  const signatures = [];
  for (const part of String(header).split(',')) {
    const i = part.indexOf('=');
    if (i < 1) continue;
    const k = part.slice(0, i).trim();
    const v = part.slice(i + 1).trim();
    if (k === 't') timestamp = v;
    else if (k === 'v1') signatures.push(v);
  }
  if (!/^\d+$/.test(timestamp || '') || !signatures.length) return false;
  if (Math.abs(nowSeconds - Number(timestamp)) > TOLERANCE_SECONDS) return false;
  const expected = crypto.createHmac('sha256', secret).update(timestamp + '.').update(raw).digest();
  return signatures.some(function (sig) {
    if (!/^[0-9a-f]{64}$/.test(sig)) return false;
    return crypto.timingSafeEqual(expected, Buffer.from(sig, 'hex'));
  });
}

function money(cents) {
  return '$' + (Number(cents || 0) / 100).toFixed(2);
}

function addressLines(a) {
  if (!a) return [];
  return [a.line1, a.line2, [a.city, a.state, a.postal_code].filter(Boolean).join(', ').replace(/, (\d)/, ' $1'), a.country].filter(Boolean);
}

// What the business needs to fulfil the order, in the shape of the existing EmailJS template.
function orderEmail(event) {
  const s = event.data.object;
  const meta = s.metadata || {};
  const customer = s.customer_details || {};
  const totals = s.total_details || {};
  const source = String(meta.source || '');
  const isShop = /\/shop$/.test(source);
  const test = event.livemode ? '' : '[TEST] ';

  let state;
  if (event.type === 'checkout.session.async_payment_failed') state = 'PAYMENT FAILED. Do not start or ship.';
  else if (event.type === 'checkout.session.async_payment_succeeded') state = 'PAID (bank payment cleared)';
  else if (s.payment_status === 'paid' || s.payment_status === 'no_payment_required') state = 'PAID';
  else state = 'PAYMENT PROCESSING (bank payment). Wait for the "PAID" email before starting.';

  const email = customer.email || s.customer_email || '';
  const total = money(s.amount_total) + (s.mode === 'subscription' ? ' per month' : '');
  const breakdown = [];
  if (totals.amount_discount) breakdown.push('discount -' + money(totals.amount_discount));
  if (totals.amount_shipping) breakdown.push('shipping ' + money(totals.amount_shipping));
  if (totals.amount_tax) breakdown.push('tax ' + money(totals.amount_tax));

  let service, business, details;
  if (isShop) {
    const ship = s.shipping_details || (s.collected_information && s.collected_information.shipping_details) || null;
    const shipName = (ship && ship.name) || customer.name || '';
    const shipAddress = addressLines((ship && ship.address) || customer.address);
    service = test + 'Shop order (' + (meta.total_tees || '?') + ' tee' + (meta.total_tees === '1' ? '' : 's') + ')';
    business = 'Favorable Odds Shop';
    details = [
      'Items: ' + (meta.items || 'see Stripe'),
      meta.deal_pairs && meta.deal_pairs !== '0' ? '2-for-$60 pairs: ' + meta.deal_pairs : '',
      '',
      'Ship to:',
      shipName,
      ...shipAddress,
      customer.phone ? 'Phone: ' + customer.phone : ''
    ].filter(function (l, i) { return l !== '' || i === 2; }).join('\n');
  } else {
    const parts = [];
    for (let i = 1; i <= 8 && meta['details_' + i]; i++) parts.push(meta['details_' + i]);
    service = test + (meta.service || 'Order');
    business = meta.business || '';
    details = parts.join('') || '(no intake details)';
  }

  return {
    from_name: meta.customer_name || customer.name || 'Customer',
    email: email,
    reply_to: email,
    business: business,
    service: service,
    price: state + ': ' + total + (breakdown.length ? ' (' + breakdown.join(', ') + ')' : ''),
    details: details,
    notes: [meta.notes ? 'Customer notes: ' + meta.notes : '', 'Stripe checkout session: ' + s.id, 'Stripe event: ' + event.id].filter(Boolean).join('\n')
  };
}

async function handler(req, res, deps) {
  const env = (deps && deps.env) || process.env;
  const doFetch = (deps && deps.fetch) || fetch;
  const now = (deps && deps.now) || function () { return Math.floor(Date.now() / 1000); };

  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return send(res, 405, { error: 'method_not_allowed' });
  }
  const secret = env.STRIPE_WEBHOOK_SECRET || '';
  if (!/^whsec_/.test(secret)) return send(res, 503, { error: 'webhook_not_configured' });

  const raw = await readRawBody(req);
  if (!raw) {
    console.error('webhook_raw_body_unavailable');
    return send(res, 400, { error: 'raw_body_unavailable' });
  }
  const sigHeader = req.headers && req.headers['stripe-signature'];
  if (!verifySignature(raw, sigHeader, secret, now())) return send(res, 400, { error: 'invalid_signature' });

  let event;
  try { event = JSON.parse(raw.toString('utf8')); } catch (e) { return send(res, 400, { error: 'invalid_json' }); }
  if (!event || !HANDLED[event.type] || !event.data || !event.data.object) return send(res, 200, { received: true, handled: false });

  const result = await sendOrderEmail(doFetch, env, orderEmail(event));
  if (result.skipped) {
    console.error('webhook_email_not_configured', event.id);
    return send(res, 200, { received: true, emailed: false, reason: 'EMAILJS_PRIVATE_KEY not set' });
  }
  // A non-2xx makes Stripe retry later, so a temporary email outage doesn't lose the order notice.
  if (!result.ok) return send(res, 500, { error: 'email_failed' });
  return send(res, 200, { received: true, emailed: true });
}

module.exports = function (req, res) { return handler(req, res); };
module.exports.handler = handler;
module.exports.verifySignature = verifySignature;
module.exports.orderEmail = orderEmail;
module.exports.readRawBody = readRawBody;
// Next.js-style hint; plain Vercel functions read the stream above either way.
module.exports.config = { api: { bodyParser: false } };
