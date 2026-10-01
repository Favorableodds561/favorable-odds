/* Odd$ Guard: the ONE place to change how the download is unlocked.
   See tools/odds-guard/README.md ("Email capture") before editing.

   downloadPath : URL of the release ZIP. It is only put on the page after the lead step succeeds
                  (the page markup never contains the link). This is a soft gate: the file itself is a public static
                  file, so it is a lead magnet, not access control.

   lead.provider: 'emailjs'  -> sends the address to Favorable Odds through EmailJS (the provider the site already
                                uses on /services and /bookkeeping; same service and public key).
                  null       -> NOT configured: the form is disabled and the download stays hidden.
                  To move to a real mailing list (e.g. Brevo, listed in your stack), add a function under
                  `providers` in guard.js that returns a Promise, resolves only when the address was really accepted,
                  and set lead.provider to its name. If it rejects, the download is not revealed.

   The EmailJS values below are the ones already public in services.html and bookkeeping.html. templateId is the
   existing "order request" template, so leads land in the same inbox formatted as requests. Create a dedicated
   template (e.g. template_odds_guard_lead) in EmailJS and put its id here when you can. */
window.FO_GUARD_CONFIG = {
  version: '0.1.0',
  downloadPath: '/tools/odds-guard/download/OddsGuard-v0.1.zip',
  lead: {
    provider: 'emailjs',
    emailjs: {
      publicKey: 'YVFMPQh2ifuDyFMUq',
      serviceId: 'service_blx7dqd',
      templateId: 'template_lbtqhem'
    }
  }
};
