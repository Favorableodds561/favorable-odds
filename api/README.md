# Checkout API (Instant Services, Care Plans, Bookkeeping, Shop)

| Function | Used by | Sells |
| --- | --- | --- |
| `POST /api/create-checkout-session` | `services.html`, `bookkeeping.html` | Instant Services, Care Plans (monthly), Bookkeeping Starter/Standard (monthly), New LLC Starter |
| `POST /api/create-shop-checkout` | `shop.html` | Tees (US only, flat shipping, "any 2 for $60" deal, Stripe Tax) |

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

The publishable key (`pk_...`) is **not used**: hosted Checkout does not need it.
Never paste a secret key into chat, issues or code. If one is exposed, roll it in the Stripe dashboard immediately.

Redeploy after changing environment variables.

## Test mode first

1. Use `sk_test_...` for the **Preview** environment and test with card `4242 4242 4242 4242`, any future expiry, any CVC.
2. Check: one-time service, a Care Plan, cancelling at Stripe (returns to `/services?checkout=cancelled`), and the fallback (remove the variable in a preview and confirm the email request flow appears).
3. Only then add `sk_live_...` to **Production** and place one real small order yourself, then refund it in Stripe.

## Stripe dashboard settings to turn on

- **Settings → Customer emails → Successful payments** (receipts) and **Refunds**.
- **Settings → Public details**: business name, support email and phone (shown on Checkout and receipts).
- **Settings → Billing → Customer portal**: lets Care Plan customers update their card or cancel. Share the portal link in your welcome email.
- Notifications: turn on email alerts for new payments (Stripe emails only, no webhook in this phase).

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

- No webhook: nothing on the site confirms a payment automatically. Stripe's emails and dashboard are the source of truth.
- Care Plans: Stripe handles recurring billing; there is no on-site account area.
- Sales tax is not collected on services, care plans or bookkeeping. Confirm with your accountant. Shop orders use Stripe Tax.
- Add a refund/terms page before taking live payments, and link it from the page.

## Tests

```
node --test "tests/api/*.test.js"
```

Runs with a mocked Stripe (no network and no keys). One test reads `IS_SERVICES` from `services.html` and fails if the server price list differs.
