/* Odd$ Guard page: email step -> download reveal, help mailto, analytics events.
   Privacy: the email address is sent ONLY to the configured provider, never to analytics, storage or the console.
   Analytics calls carry no personal data. Configure via guard-config.js. */
(function () {
  "use strict";
  var C = window.FO_GUARD_CONFIG || {};
  var track = window.foTrack || function () {};
  var $ = function (id) { return document.getElementById(id); };
  var UNLOCK_KEY = "fo_guard_unlocked"; // remembers only that this browser already unlocked the download (never the email)

  var form = $("lead-form"), emailEl = $("lead-email"), trap = $("lead-website"), msg = $("lead-msg"), btn = $("lead-submit");
  var gate = $("lead-gate"), panel = $("guard-download"), link = $("download-link");

  /* Obfuscated mailto, same idea as the rest of the site (keeps the address out of the static HTML). */
  function mailHref(subject, body) {
    return "mai" + "lto:hello@favorableodds.io?subject=" + encodeURIComponent(subject) + "&body=" + encodeURIComponent(body);
  }
  var helpBody = "Hi Favorable Odds,\n\nI ran Odd$ Guard" + (C.version ? " (v" + C.version + ")" : "") +
    " and would like help understanding my results.\n\nWhat I'm seeing:\n\n" +
    "(The report lists your computer and account names, so only paste what you're comfortable sharing.)";
  Array.prototype.forEach.call(document.querySelectorAll("[data-help-mail]"), function (a) {
    a.addEventListener("click", function (e) { e.preventDefault(); window.location.href = mailHref("Odd$ Guard report help", helpBody); });
  });

  /* ---- Lead providers. Each returns a Promise that resolves ONLY if the address was really accepted. ---- */
  var providers = {
    emailjs: function (address) {
      var p = (C.lead && C.lead.emailjs) || {};
      if (!window.emailjs || !p.publicKey || !p.serviceId || !p.templateId) return Promise.reject(new Error("not-configured"));
      return window.emailjs.send(p.serviceId, p.templateId, {
        from_name: "Odd$ Guard download request",
        email: address,
        reply_to: address,
        business: "N/A (free tool lead)",
        service: "Odd$ Guard v" + (C.version || "") + " free download",
        price: "Free",
        details: "Email captured on /tools/odds-guard/ to unlock the Odd$ Guard download.",
        notes: "Lead source: Odd$ Guard landing page"
      }, { publicKey: p.publicKey });
    }
  };
  var provider = C.lead && providers[C.lead.provider];

  function say(text, isError) { msg.textContent = ""; msg.className = "lead-msg" + (isError ? " is-error" : ""); msg.appendChild(document.createTextNode(text)); }
  function sayWithMail(text, linkText) {
    say(text + " ", true);
    var a = document.createElement("a");
    a.href = "/#contact"; a.textContent = linkText || "Email us and we'll send the download.";
    a.addEventListener("click", function (e) { e.preventDefault(); window.location.href = mailHref("Odd$ Guard download", "Hi, please send me the Odd$ Guard download link."); });
    msg.appendChild(a);
  }

  function reveal(fromSubmit) {
    link.href = C.downloadPath;
    gate.hidden = true;
    panel.hidden = false;
    if (fromSubmit) { track("guard_download_reveal"); panel.focus(); }
  }

  if (!form) return;

  if (!provider) { // integration not configured: keep the download hidden and say so
    emailEl.disabled = true; btn.disabled = true;
    sayWithMail("The download form isn't available right now.");
    return;
  }

  try { if (window.localStorage.getItem(UNLOCK_KEY) === "1") reveal(false); } catch (e) { /* storage blocked: fine */ }

  var sending = false;
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (sending) return;
    var address = (emailEl.value || "").trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(address)) { say("Please enter a valid email address.", true); emailEl.focus(); return; }
    if (trap && trap.value) { reveal(false); return; } // bots fill the hidden field; give them nothing to retry
    sending = true; btn.disabled = true; say("Unlocking your download…", false);
    track("guard_form_submit");
    provider(address).then(function () {
      try { window.localStorage.setItem(UNLOCK_KEY, "1"); } catch (e2) { /* ignore */ }
      say("", false);
      reveal(true);
    }).catch(function () {
      // Never reveal without a delivered address, and never pretend it worked.
      sayWithMail("We couldn't save your email just now, so the download wasn't unlocked. Please try again in a moment, or", "email us and we'll send it to you.");
      sending = false; btn.disabled = false;
    });
  });
})();
