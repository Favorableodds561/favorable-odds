'use strict';

// Helpers shared by the checkout functions. Files starting with "_" are not exposed as routes by Vercel.

const STRIPE_API = 'https://api.stripe.com/v1/';
const STRIPE_VERSION = '2024-06-20';
const DEFAULT_SITE = 'https://favorableodds.io';

function send(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.end(JSON.stringify(body));
}

function originOf(value) {
  try { return new URL(value).origin; } catch (e) { return null; }
}

// The origins this site accepts checkout requests from, and may send customers back to.
function allowedOrigins(env) {
  const set = new Set([originOf(env.SITE_URL || DEFAULT_SITE)]);
  const base = set.values().next().value;
  if (base && base.startsWith('https://') && !base.startsWith('https://www.')) set.add(base.replace('https://', 'https://www.'));
  // Vercel's own addresses for this deployment (previews), its git-branch alias, and the project's default production alias.
  for (const host of [env.VERCEL_URL, env.VERCEL_BRANCH_URL, env.VERCEL_PROJECT_PRODUCTION_URL]) if (host) set.add('https://' + host);
  set.delete(null);
  return set;
}

// Common gate for every checkout function. Returns { origin, key } or { status, error } to send back as-is.
function gate(req, res, env) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return { status: 405, error: 'method_not_allowed' };
  }
  const requestOrigin = req.headers && req.headers.origin;
  if (requestOrigin && !allowedOrigins(env).has(requestOrigin)) return { status: 403, error: 'forbidden_origin' };
  const key = env.STRIPE_SECRET_KEY || '';
  // Missing, or a publishable key pasted into the wrong place: the page falls back to its email flow.
  if (!/^(sk|rk)_(live|test)_/.test(key)) return { status: 503, error: 'payments_unavailable' };
  return { origin: requestOrigin || originOf(env.SITE_URL || DEFAULT_SITE), key };
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

// POST form-encoded params to a Stripe endpoint. Returns { ok, status, data }. Never throws on HTTP errors.
async function stripePost(doFetch, key, endpoint, params) {
  const controller = new AbortController();
  const timer = setTimeout(function () { controller.abort(); }, 10000);
  try {
    const response = await doFetch(STRIPE_API + endpoint, {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + key,
        'Content-Type': 'application/x-www-form-urlencoded',
        'Stripe-Version': STRIPE_VERSION
      },
      body: params.toString(),
      signal: controller.signal
    });
    const data = await response.json().catch(function () { return {}; });
    if (!response.ok) {
      // Log what Stripe rejected, never the request body, keys or customer details. Stripe's message can echo a bad value, so strip anything email-like.
      const e = (data && data.error) || {};
      const msg = String(e.message || '').replace(/\S+@\S+/g, '[email]').slice(0, 200);
      console.error('stripe_failed', endpoint, response.status, [e.type, e.code, e.param].filter(Boolean).join('/'), msg);
    }
    return { ok: response.ok, status: response.status, data: data || {} };
  } catch (e) {
    console.error('stripe_error', endpoint, e && e.name);
    return { ok: false, status: 0, data: {} };
  } finally {
    clearTimeout(timer);
  }
}

// GET a Stripe endpoint. Returns { ok, status, data }. Used only by the status endpoint.
async function stripeGet(doFetch, key, endpoint) {
  const controller = new AbortController();
  const timer = setTimeout(function () { controller.abort(); }, 8000);
  try {
    const response = await doFetch(STRIPE_API + endpoint, {
      method: 'GET',
      headers: { Authorization: 'Bearer ' + key, 'Stripe-Version': STRIPE_VERSION },
      signal: controller.signal
    });
    const data = await response.json().catch(function () { return {}; });
    return { ok: response.ok, status: response.status, data: data || {} };
  } catch (e) {
    return { ok: false, status: 0, data: {} };
  } finally {
    clearTimeout(timer);
  }
}

function isCheckoutUrl(url) {
  return typeof url === 'string' && url.startsWith('https://checkout.stripe.com/');
}

module.exports = { send, originOf, allowedOrigins, gate, str, parseBody, stripePost, stripeGet, isCheckoutUrl, DEFAULT_SITE };
