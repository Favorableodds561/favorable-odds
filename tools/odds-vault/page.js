/* Odd$ Vault page wiring: analytics events and the post-success "More from Favorable Odd$" section.
   Listens to the engine's counts-only events; never touches file names, contents or passwords. */
(function () {
  "use strict";
  var track = window.foTrack || function () {};
  var more = document.getElementById("vault-more");
  document.addEventListener("vault:started", function () { track("vault_started"); });
  document.addEventListener("vault:success", function (e) {
    track("vault_success", { file_count: (e.detail && e.detail.files) || 0 });
    if (more) more.hidden = false;
  });
})();
