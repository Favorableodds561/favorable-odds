# Checkout API (Instant Services and Care Plans)

`POST /api/create-checkout-session` creates a Stripe-hosted Checkout page and returns `{ "url": "https://checkout.stripe.com/..." }`.
The browser then redirects to it. Card details go to Stripe only; this site never sees them.

## How it works

1. `services.html` sends the service key plus the intake form to the function. **Prices are never sent from the browser.**
2. `api/_catalog.js` holds the price list. One-time services use `mode: payment`; Care Plans use `mode: subscription` billed monthly.
3. The intake details are stored in the Checkout Session metadata (visible in the Stripe dashboard on the payment) and also emailed through EmailJS, marked **PAYMENT PENDING**. Confirm the payment in Stripe before starting work.
4. If the function returns an error or is not configured, the page falls back to the old email request flow and tells the customer nothing was charged.
5. Stripe sends customers back to `/services/thanks` (paid or not, the page makes no payment claim) or to `/services?checkout=cancelled`.

## Setup (Vercel)

Set these in **Vercel → Project → Settings → Environment Variables** (never commit them):

| Variable | Required | Value |
| --- | --- | --- |
| `STRIPE_SECRET_KEY` | yes | Stripe secret key `sk_test_...` (Preview) and `sk_live_...` (Production). A restricted key `rk_...` with **Checkout Sessions: write** is better. |
| `SITE_URL` | no | Defaults to `https://favorableodds.io` |

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

## Limits of this phase

- No webhook: nothing on the site confirms a payment automatically. Stripe's emails and dashboard are the source of truth.
- Care Plans: Stripe handles recurring billing; there is no on-site account area.
- Sales tax is not collected on these services. Confirm with your accountant (the shop phase will use Stripe Tax).
- Add a refund/terms page before taking live payments, and link it from the page.

## Tests

```
node --test "tests/api/*.test.js"
```

Runs with a mocked Stripe (no network and no keys). One test reads `IS_SERVICES` from `services.html` and fails if the server price list differs.
