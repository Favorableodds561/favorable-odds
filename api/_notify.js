'use strict';

// Server-side order emails through EmailJS's REST API, using the same EmailJS service and template as the site's forms.
// Needs EMAILJS_PRIVATE_KEY in Vercel, and "Allow EmailJS API for non-browser applications" switched on in EmailJS (Account > Security).
// The service ID, template ID and public key below are already public in the site's HTML.

const EMAILJS_URL = 'https://api.emailjs.com/api/v1.0/email/send';
const EMAILJS = { serviceId: 'service_blx7dqd', templateId: 'template_lbtqhem', publicKey: 'YVFMPQh2ifuDyFMUq' };

// Returns { ok, status, skipped }. skipped = true when no private key is configured.
async function sendOrderEmail(doFetch, env, templateParams) {
  const accessToken = env.EMAILJS_PRIVATE_KEY || '';
  if (!accessToken) return { ok: false, status: 0, skipped: true };
  const controller = new AbortController();
  const timer = setTimeout(function () { controller.abort(); }, 8000);
  try {
    const response = await doFetch(EMAILJS_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        service_id: EMAILJS.serviceId,
        template_id: EMAILJS.templateId,
        user_id: EMAILJS.publicKey,
        accessToken: accessToken,
        template_params: templateParams
      }),
      signal: controller.signal
    });
    if (!response.ok) {
      const text = await response.text().catch(function () { return ''; });
      console.error('emailjs_failed', response.status, String(text).slice(0, 200));
    }
    return { ok: response.ok, status: response.status, skipped: false };
  } catch (e) {
    console.error('emailjs_error', e && e.name);
    return { ok: false, status: 0, skipped: false };
  } finally {
    clearTimeout(timer);
  }
}

module.exports = { sendOrderEmail, EMAILJS, EMAILJS_URL };
