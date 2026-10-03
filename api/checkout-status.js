'use strict';

// GET /api/checkout-status
// Self-check for the owner: open it in a browser after setting up Stripe. It says whether the secret key is present and which mode it is in,
// whether Stripe answers and can take charges, whether Stripe Tax is ready for the shop, and whether this address is allowed to start checkouts.
// It never returns the key, account details or customer data. It creates nothing in Stripe.

const { send, allowedOrigins, stripeGet } = require('./_stripe');

function keyState(key) {
  if (!key) return 'missing';
  if (/^pk_/.test(key)) return 'publishable_key_in_secret_slot';
  if (/^(sk|rk)_test_/.test(key)) return 'test';
  if (/^(sk|rk)_live_/.test(key)) return 'live';
  return 'invalid_format';
}

async function handler(req, res, deps) {
  const env = (deps && deps.env) || process.env;
  const doFetch = (deps && deps.fetch) || fetch;

  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    return send(res, 405, { error: 'method_not_allowed' });
  }

  const key = env.STRIPE_SECRET_KEY || '';
  const state = keyState(key);
  const host = req.headers && req.headers.host;
  const out = {
    stripeKey: state,
    stripeReachable: null,
    chargesEnabled: null,
    shopTax: { setting: env.SHOP_AUTOMATIC_TAX === 'off' ? 'off' : 'on', stripeTaxStatus: null, missing: [] },
    thisAddressAllowed: host ? allowedOrigins(env).has('https://' + host) : null,
    vercelEnv: env.VERCEL_ENV || null,
    hints: []
  };

  if (state === 'missing') out.hints.push('STRIPE_SECRET_KEY is not set for this environment. Add it in Vercel (Production and Preview are separate checkboxes), then redeploy.');
  else if (state === 'publishable_key_in_secret_slot') out.hints.push('STRIPE_SECRET_KEY holds a publishable key (pk_...). Use the secret key (sk_...) or a restricted key (rk_...).');
  else if (state === 'invalid_format') out.hints.push('STRIPE_SECRET_KEY does not look like a Stripe secret key (expected sk_test_, sk_live_, rk_test_ or rk_live_).');

  if (state === 'test' || state === 'live') {
    const account = await stripeGet(doFetch, key, 'account');
    out.stripeReachable = account.ok;
    if (account.ok) {
      out.chargesEnabled = account.data.charges_enabled === true;
      if (!out.chargesEnabled) out.hints.push('Stripe says this account cannot take charges yet. Finish account activation in the Stripe dashboard.');
    } else {
      out.hints.push('Stripe rejected the key (HTTP ' + account.status + '). It may be wrong, revoked, or a restricted key without permission to read the account.');
    }

    if (out.shopTax.setting === 'on') {
      const tax = await stripeGet(doFetch, key, 'tax/settings');
      if (tax.ok) {
        out.shopTax.stripeTaxStatus = tax.data.status || null;
        const pending = tax.data.status_details && tax.data.status_details.pending;
        out.shopTax.missing = (pending && Array.isArray(pending.missing_fields)) ? pending.missing_fields : [];
        if (tax.data.status !== 'active') out.hints.push('Stripe Tax is not active yet, so shop checkout will fail. In Stripe go to Tax > Settings and finish the missing items (' + (out.shopTax.missing.join(', ') || 'head office address') + '), or set SHOP_AUTOMATIC_TAX=off to sell without tax calculation.');
      } else {
        out.hints.push('Could not read Stripe Tax settings (HTTP ' + tax.status + '). Open Tax in the Stripe dashboard and confirm it is set up. A restricted key needs read access to Tax Settings.');
      }
    }
  }

  // Not needed to take payments, but needed for order emails and self-service cancellations.
  out.extras = {
    orderEmails: /^whsec_/.test(env.STRIPE_WEBHOOK_SECRET || '') && !!env.EMAILJS_PRIVATE_KEY,
    webhookSecret: /^whsec_/.test(env.STRIPE_WEBHOOK_SECRET || ''),
    emailjsPrivateKey: !!env.EMAILJS_PRIVATE_KEY,
    customerPortal: /^https:\/\/billing\.stripe\.com\//.test(env.STRIPE_PORTAL_LOGIN_URL || '')
  };
  out.recommended = [];
  if (!out.extras.webhookSecret) out.recommended.push('Add a Stripe webhook and put its signing secret (whsec_...) in STRIPE_WEBHOOK_SECRET, so every paid order is emailed to you.');
  if (!out.extras.emailjsPrivateKey) out.recommended.push('Put your EmailJS private key in EMAILJS_PRIVATE_KEY and allow API access for non-browser applications in EmailJS, so the webhook can send order emails.');
  if (!out.extras.customerPortal) out.recommended.push('Turn on the Stripe customer portal and put its login link in STRIPE_PORTAL_LOGIN_URL, so plan customers can cancel or update their card themselves.');

  if (out.thisAddressAllowed === false) out.hints.push('Checkout requests from ' + host + ' are refused. Set SITE_URL to your production address, or open the site from a Vercel-provided address.');
  if (!out.hints.length) out.hints.push('Everything this check can see looks fine.');
  out.ready = out.hints.length === 1 && out.hints[0].startsWith('Everything');
  return send(res, 200, out);
}

module.exports = function (req, res) { return handler(req, res); };
module.exports.handler = handler;
module.exports.keyState = keyState;
