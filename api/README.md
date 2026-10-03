# Checkout API (Instant Services, Care Plans, Bookkeeping, Shop)

| Function | Used by | Sells |
| --- | --- | --- |
| `POST /api/create-checkout-session` | `services.html`, `bookkeeping.html` | Instant Services, Care Plans (monthly), Bookkeeping Starter/Standard (monthly), New LLC Starter |
| `POST /api/create-shop-checkout` | `shop.html` | Tees (US only, flat shipping, "any 2 for $60" deal, Stripe Tax) |
| `POST /api/stripe-webhook` | Stripe | Emails every paid, processing or failed order to the business inbox |
| `GET /api/checkout-session?id=` | thank-you pages | Says whether a checkout was paid (no customer data) |
| `GET /billing` → `/api/billing-portal` | plan pages, thank-you page | Sends plan customers to the Stripe customer portal (or `/manage-plan`) |
| `GET /api/checkout-status` | you | Setup self-check |

Each creates a Stripe-hosted Checkout page and returns `{ "url": "https://checkout.stripe.com/..." }`.
The browser then redirects to it. Card details go to Stripe only; this site never sees them.
Shared code is in `_stripe.js`; price lists are in `_catalog.js` (services) and `_shop.js` (shop). Files starting with `_` are not routes.

## How it works

1. `services.html` sends the service key plus the intake form to the function. **Prices are never sent from the browser.**
2. `api/_catalog.js` holds the services price list. One-time services use `mode: payment`; Care Plans use `mode: subscription` billed monthly.
3. The intake details are stored in the Checkout Session metadata (visible in the Stripe dashboard on the payment) and also emailed through EmailJS, marked **PAYMENT PENDING**. Confirm the payment in Stripe before starting work.
4. If the function returns an error or is not configured, the page falls back to the old email request flow and tells the customer nothing was charged.
5. Stripe sends customers back to `/services/thanks` (paid or not, the page makes no payment claim) or to `/services?checkout=cancelled`.

## Setup (Vercel)

Set these in **Vercel → Project → Settings → Environment Variables** (never commit them):

| Variable | Required | Value |
| --- | --- | --- |
| `STRIPE_SECRET_KEY` | yes | Stripe secret key `sk_test_...` (Preview) and `sk_live_...` (Production). A restricted key `rk_...` with **Checkout Sessions: write** is better. |
| `SITE_URL` | no | Defaults to `https://favorableodds.io` |
| `SHOP_AUTOMATIC_TAX` | no | Shop only. Stripe Tax is **on** unless this is exactly `off`. |
| `STRIPE_WEBHOOK_SECRET` | for order emails | The webhook endpoint's signing secret (`whsec_...`). Test and live endpoints have different secrets. |
| `EMAILJS_PRIVATE_KEY` | for order emails | EmailJS → Account → API keys → Private key. Also turn on "Allow EmailJS API for non-browser applications" (Account → Security). |
| `STRIPE_PORTAL_LOGIN_URL` | for self-service cancel | Stripe → Settings → Billing → Customer portal → login link (`https://billing.stripe.com/p/login/...`). Test and live links differ. |

The publishable key (`pk_...`) is **not used**: hosted Checkout does not need it.
Never paste a secret key into chat, issues or code. If one is exposed, roll it in the Stripe dashboard immediately.

Redeploy after changing environment variables.

## Check that it is working

Open **`/api/checkout-status`** on the address you are testing (for example `https://favorableodds.io/api/checkout-status` or a Vercel preview address). It reports, in plain language:

- whether `STRIPE_SECRET_KEY` is set for **that** environment and whether it is a test or live key,
- whether Stripe accepts the key and the account can take charges,
- whether Stripe Tax is active (needed for shop checkout), with the missing items if not,
- whether that address is allowed to start checkouts.

It reads only. It creates nothing in Stripe and never shows the key. `"ready": true` means everything it can see is fine.

If a customer sees "Online checkout isn't available" on the shop (the page shows an `Error:` code), the usual causes are:

| Error code | Meaning | Fix |
| --- | --- | --- |
| `payments_unavailable` (503) | No usable `STRIPE_SECRET_KEY` in this Vercel environment | Add it (Production and Preview are separate checkboxes) and **redeploy** |
| `forbidden_origin` (403) | Opened from an address the function does not recognize | Set `SITE_URL`, or use the Vercel-provided address |
| `checkout_unavailable` (502) | Stripe rejected the request | Check `/api/checkout-status` (usually Stripe Tax not active). Vercel → Logs shows the exact reason (`stripe_failed ...`) |
| `http_404` | The `/api` functions were not deployed | Confirm the deployment includes the `api/` folder |

Note: this repo is connected to more than one Vercel project. Environment variables belong to a project, so set the key on the project that serves your domain.

## Test mode first

1. Use `sk_test_...` for the **Preview** environment and test with card `4242 4242 4242 4242`, any future expiry, any CVC.
2. Check: one-time service, a Care Plan, cancelling at Stripe (returns to `/services?checkout=cancelled`), and the fallback (remove the variable in a preview and confirm the email request flow appears).
3. Only then add `sk_live_...` to **Production** and place one real small order yourself, then refund it in Stripe.

## Stripe dashboard settings to turn on

- **Settings → Customer emails → Successful payments** (receipts) and **Refunds**.
- **Settings → Public details**: business name, support email and phone (shown on Checkout and receipts).
- **Settings → Billing → Customer portal**: lets Care Plan customers update their card or cancel. Share the portal link in your welcome email.
- Notifications: turn on email alerts for new payments (Stripe emails only, no webhook in this phase).

## Order emails (Stripe webhook)

Every completed checkout is emailed to the inbox on the EmailJS template (`template_lbtqhem`, currently `hello@favorableodds.io`), sent from the server, so it does not depend on the customer's browser.

- **PAID**: start work or ship. Services and bookkeeping include the full intake form; shop orders include items, totals and the shipping address.
- **PAYMENT PROCESSING**: a bank payment that has not cleared. Wait for the PAID email.
- **PAYMENT FAILED**: do not start or ship.
- Sandbox orders are prefixed `[TEST]`.

Setup, once per mode (sandbox first, then live):
1. Stripe → Developers → Webhooks → **Add endpoint**: `https://<your address>/api/stripe-webhook`. Events: `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`.
2. Copy the endpoint's **signing secret** into `STRIPE_WEBHOOK_SECRET` (Vercel; Preview for the sandbox endpoint, Production for the live one) and redeploy.
3. Add `EMAILJS_PRIVATE_KEY` and allow non-browser API access in EmailJS.
4. In Stripe, open the endpoint and click **Send test event** (or place a test order). The endpoint should show `200`.

If EmailJS is down, the webhook returns an error and Stripe retries for up to 3 days. A retry after a slow success can occasionally send the same email twice; the Stripe event id in the notes tells duplicates apart.
The browser still sends a "PAYMENT PENDING" email when checkout starts (useful for following up abandoned checkouts). Treat only **PAID** as an order.

## Plans: annual billing and self-service

- Care Plans can be bought **monthly or annually** (annual = 10 months, "2 months free"). The page sends only `billing: "year"`; the server computes the price. Bookkeeping plans are monthly only.
- `/billing` sends customers to the Stripe customer portal to update their card or cancel. Turn the portal on in Stripe (Settings → Billing → Customer portal: allow cancellation and payment-method updates), copy its login link into `STRIPE_PORTAL_LOGIN_URL`. Without it, `/billing` shows `/manage-plan`, which tells customers to email or text you.

## Shop checkout

- Customers enter name, email, **US-only** shipping address and phone on Stripe's page. Shipping is a flat **$5.00 per order** (`SHIPPING_CENTS` in `api/_shop.js` and `shippingFlat` in `shop.html`; a test fails if they differ, so change both).
- The "any 2 tees for $60" deal is a one-use coupon created per order, so receipts show it as its own line. 3 tees = one pair + one single.
- **Stripe Tax is on.** Before it works you must set it up in Stripe: **Tax → Settings** (head office address, registrations where you must collect, default product tax code, e.g. clothing). Until then, shop checkout returns an error and customers see the "reserve by email" option. Test it in test mode first. If you need to sell before Tax is ready, set `SHOP_AUTOMATIC_TAX=off` and redeploy (you are then responsible for tax).
- Pre-order wording ("ships within 2–3 weeks") appears in the cart, on Stripe's pay button area and on the thank-you page.
- Fulfilment: each paid order is in Stripe → Payments, with shipping address and `items` metadata (for example `koi L x2; galaxy M x1`).
- A coupon is created for every checkout attempt with 2+ tees, including abandoned ones. They are harmless (one use, not shareable) and can be ignored.

## Bookkeeping notes

- Starter and Standard are monthly subscriptions and New LLC Starter is a one-time charge. **Catch-Up Cleanup (from $150) is quoted after a review, so it stays an email quote request and is never charged online.**
- The page no longer says "we'll confirm the right fit before anything is billed", because checkout bills immediately. It now points customers to the free 15-minute fit call first. Add a refund policy you are comfortable with.

## Limits of this phase

- Order emails depend on the webhook and EmailJS being configured (see above). Stripe's dashboard remains the source of truth.
- Plans: Stripe handles recurring billing and the customer portal; there is no on-site account area.
- Sales tax is not collected on services, care plans or bookkeeping. Confirm with your accountant. Shop orders use Stripe Tax.
- Add a refund/terms page before taking live payments, and link it from the page.

## Tests

```
node --test "tests/api/*.test.js"
```

Runs with a mocked Stripe (no network and no keys). One test reads `IS_SERVICES` from `services.html` and fails if the server price list differs.
