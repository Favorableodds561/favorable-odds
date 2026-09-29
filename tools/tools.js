/* Favorable Odds — Free Tools shared behaviour: mobile menu + a vendor-neutral analytics shim.
   No third-party tracking is loaded by this file. */
(function () {
  "use strict";

  /* ── Analytics shim ──────────────────────────────────────────────────────
     foTrack(name, params) forwards to whichever analytics the site adds later (gtag, dataLayer, Plausible)
     and always emits a "fo:track" CustomEvent on document. With none installed it is a no-op.
     Only numbers, booleans and short strings are forwarded, and anything password- or file-related is dropped,
     so a careless call can't leak sensitive values. */
  function clean(params) {
    var out = {};
    if (!params) return out;
    Object.keys(params).forEach(function (k) {
      var v = params[k];
      if (!/^[a-z0-9_]{1,30}$/.test(k) || /pass|file_?name|path|content/.test(k)) return;
      if (typeof v === "number" || typeof v === "boolean" || (typeof v === "string" && v.length <= 40)) out[k] = v;
    });
    return out;
  }
  window.foTrack = function (name, params) {
    try {
      if (!/^[a-z0-9_]{1,40}$/.test(name)) return;
      var p = clean(params);
      document.dispatchEvent(new CustomEvent("fo:track", { detail: { name: name, params: p } }));
      if (typeof window.gtag === "function") window.gtag("event", name, p);
      else if (Array.isArray(window.dataLayer)) window.dataLayer.push(Object.assign({ event: name }, p));
      else if (typeof window.plausible === "function") window.plausible(name, { props: p });
    } catch (e) { /* analytics must never break the page */ }
  };

  // <a data-fo-event="shop_click" data-fo-location="vault_more"> → foTrack("shop_click", {location:"vault_more"})
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("[data-fo-event]");
    if (a) window.foTrack(a.getAttribute("data-fo-event"), { location: a.getAttribute("data-fo-location") || "page" });
  });
  var pv = document.body && document.body.getAttribute("data-fo-page-event");
  if (pv) window.foTrack(pv);

  /* ── Mobile menu (same behaviour as the main site) ── */
  var burger = document.getElementById("navHamburger");
  var overlay = document.getElementById("navOverlay");
  if (!burger || !overlay) return;
  function setMenu(open) {
    overlay.classList.toggle("open", open);
    burger.classList.toggle("open", open);
    burger.setAttribute("aria-expanded", open ? "true" : "false");
    document.body.style.overflow = open ? "hidden" : "";
  }
  burger.addEventListener("click", function () { setMenu(true); });
  document.getElementById("navOverlayClose").addEventListener("click", function () { setMenu(false); });
  overlay.addEventListener("click", function (e) { if (e.target === overlay || e.target.closest("a")) setMenu(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") setMenu(false); });
})();
