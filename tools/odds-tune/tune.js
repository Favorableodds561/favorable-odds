/* Odd$ Tune page: the "Get Help" button opens a pre-filled email, built in script so the address is not in the static HTML
   (same approach as the rest of the site). Without JavaScript the link goes to the contact section. No network requests. */
(function () {
  "use strict";
  var body = "Hi Favorable Odds,\n\nI'm using Odd$ Tune and would like help with my PC.\n\nWhat's happening:\n\n" +
    "(Reports list technical details of your PC, so only paste what you're comfortable sharing.)";
  var href = "mai" + "lto:hello@favorableodds.io?subject=" + encodeURIComponent("Odd$ Tune help") + "&body=" + encodeURIComponent(body);
  Array.prototype.forEach.call(document.querySelectorAll("[data-help-mail]"), function (a) {
    a.addEventListener("click", function (e) { e.preventDefault(); window.location.href = href; });
  });
})();
