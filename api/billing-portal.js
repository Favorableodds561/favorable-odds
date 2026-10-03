'use strict';

// GET /billing (rewritten here by vercel.json)
// Sends Care Plan and Bookkeeping customers to Stripe's customer portal, where they update their card or cancel.
// Set STRIPE_PORTAL_LOGIN_URL to the portal's login link (Stripe > Settings > Billing > Customer portal). Until then,
// customers land on /manage-plan, which tells them how to reach us.

function handler(req, res, deps) {
  const env = (deps && deps.env) || process.env;
  const url = env.STRIPE_PORTAL_LOGIN_URL || '';
  const target = /^https:\/\/billing\.stripe\.com\/[A-Za-z0-9/_\-]+$/.test(url) ? url : '/manage-plan';
  res.statusCode = 302;
  res.setHeader('Location', target);
  res.setHeader('Cache-Control', 'no-store');
  res.end();
}

module.exports = function (req, res) { return handler(req, res); };
module.exports.handler = handler;
