'use strict';

// GET /api/checkout-session?id=cs_...
// Lets the thank-you pages say whether the payment actually went through. Returns only
// { state: paid | processing | not_completed | not_found | unknown, kind: services | bookkeeping | shop | null, subscription: bool }.
// No amounts, names, emails or addresses. Checkout session ids are long random values that only the customer's browser receives.

const { send, stripeGet } = require('./_stripe');

const ID_RE = /^cs_(test|live)_[A-Za-z0-9]{10,200}$/;

function stateOf(s) {
  if (s.status === 'complete' && (s.payment_status === 'paid' || s.payment_status === 'no_payment_required')) return 'paid';
  if (s.status === 'complete') return 'processing';     // e.g. a bank payment that hasn't cleared yet
  return 'not_completed';
}

function kindOf(s) {
  const m = /\/(services|bookkeeping|shop)$/.exec(String((s.metadata || {}).source || ''));
  return m ? m[1] : null;
}

async function handler(req, res, deps) {
  const env = (deps && deps.env) || process.env;
  const doFetch = (deps && deps.fetch) || fetch;

  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    return send(res, 405, { error: 'method_not_allowed' });
  }
  const id = String((req.query && req.query.id) || new URL(req.url || '/', 'http://x').searchParams.get('id') || '');
  if (!ID_RE.test(id)) return send(res, 400, { error: 'invalid_id' });
  const key = env.STRIPE_SECRET_KEY || '';
  if (!/^(sk|rk)_(live|test)_/.test(key)) return send(res, 503, { state: 'unknown', kind: null, subscription: false });

  const r = await stripeGet(doFetch, key, 'checkout/sessions/' + id);
  if (r.status === 404) return send(res, 200, { state: 'not_found', kind: null, subscription: false });
  if (!r.ok) return send(res, 200, { state: 'unknown', kind: null, subscription: false });
  return send(res, 200, { state: stateOf(r.data), kind: kindOf(r.data), subscription: r.data.mode === 'subscription' });
}

module.exports = function (req, res) { return handler(req, res); };
module.exports.handler = handler;
