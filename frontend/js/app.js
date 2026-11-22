/* FairBon — app shell: tab navigation, settings and wiring (ES5). */
(function (global) {
  "use strict";

  var NS = global.FairBon = global.FairBon || {};

  function $(id) { return document.getElementById(id); }

  function switchTab(tab) {
    NS.state.tab = tab;
    Array.prototype.forEach.call(
      document.querySelectorAll(".tab-panel"),
      function (panel) {
        panel.hidden = panel.getAttribute("data-tab") !== tab;
      }
    );
    Array.prototype.forEach.call(
      document.querySelectorAll(".tab-btn"),
      function (button) {
        var active = button.getAttribute("data-tab") === tab;
        if (active) {
          button.setAttribute("aria-current", "page");
        } else {
          button.removeAttribute("aria-current");
        }
      }
    );
    var fab = $("add-receipt-fab");
    if (fab) { fab.hidden = tab === "overview"; }
    if (global.location.hash !== "#" + tab) {
      global.history.replaceState(null, "", "#" + tab);
    }
    global.scrollTo(0, 0);
  }

  function bindTabs() {
    Array.prototype.forEach.call(
      document.querySelectorAll(".tab-btn"),
      function (button) {
        button.addEventListener("click", function () {
          switchTab(button.getAttribute("data-tab"));
        });
      }
    );
    NS.on("tab", function (payload) {
      if (payload && payload.tab) { switchTab(payload.tab); }
    });
  }

  function bindSettings() {
    var modal = $("settings-modal");
    var backdrop = $("settings-backdrop");
    var plzPill = $("plz-pill");
    var plzInput = $("settings-plz");
    var country = $("settings-country");
    var budget = $("settings-budget");
    var byok = $("settings-byok");
    var byokProvider = $("settings-byok-provider");
    var share = $("settings-share");
    var business = $("settings-business");

    function syncLabels() {
      plzPill.textContent = "PLZ " + NS.state.postalCode;
      plzInput.value = NS.state.postalCode;
      country.value = NS.state.country || "DE";
      budget.value = NS.state.budget ? String(NS.state.budget) : "";
      byok.value = NS.state.byok || "";
      byokProvider.value = NS.state.byokProvider || "openai_compatible";
      share.checked = NS.state.shareOptin === true;
      business.checked = NS.state.businessExpenses === true;
    }

    function open() {
      syncLabels();
      modal.hidden = false;
      backdrop.hidden = false;
      var close = $("settings-close");
      if (close) { close.focus(); }
    }

    function close() {
      modal.hidden = true;
      backdrop.hidden = true;
    }

    $("settings-open").addEventListener("click", open);
    $("settings-close").addEventListener("click", close);
    backdrop.addEventListener("click", close);

    // --- PLZ popover (header pill) -----------------------------------
    var plzPopover = $("plz-popover");
    var plzField = $("plz-input");
    var plzSave = $("plz-save");

    function closePlzPopover() {
      plzPopover.hidden = true;
      plzPill.setAttribute("aria-expanded", "false");
    }

    function savePlzPopover() {
      NS.setPostalCode(plzField.value);
      plzField.value = NS.state.postalCode;
      syncLabels();
      closePlzPopover();
      NS.emit("plz-changed", NS.state.postalCode);
    }

    plzPill.addEventListener("click", function () {
      plzPopover.hidden = !plzPopover.hidden;
      var openNow = !plzPopover.hidden;
      plzPill.setAttribute("aria-expanded", String(openNow));
      if (openNow) {
        plzField.value = NS.state.postalCode;
        plzField.focus();
        plzField.select();
      }
    });
    plzSave.addEventListener("click", savePlzPopover);
    plzField.addEventListener("keydown", function (event) {
      if (event.key === "Enter") { savePlzPopover(); }
      if (event.key === "Escape") { closePlzPopover(); }
    });
    document.addEventListener("click", function (event) {
      if (plzPopover.hidden) { return; }
      var wrap = plzPopover.parentNode;
      if (wrap && !wrap.contains(event.target)) { closePlzPopover(); }
    });
    plzPill.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { closePlzPopover(); }
    });

    plzInput.addEventListener("change", function () {
      NS.setPostalCode(plzInput.value);
      syncLabels();
      NS.emit("plz-changed", NS.state.postalCode);
    });
    country.addEventListener("change", function () {
      NS.state.country = country.value;
      NS.storage.set("fairbon.country", country.value);
    });
    budget.addEventListener("change", function () {
      NS.state.budget = Math.max(0, Number(budget.value) || 0);
      NS.storage.set("fairbon.budget", NS.state.budget);
      NS.emit("receipts-changed");
    });
    byok.addEventListener("change", function () {
      NS.state.byok = byok.value.trim();
      NS.storage.set("fairbon.byok", NS.state.byok);
    });
    byokProvider.addEventListener("change", function () {
      NS.state.byokProvider = byokProvider.value;
      NS.storage.set("fairbon.byokProvider", NS.state.byokProvider);
    });
    share.addEventListener("change", function () {
      NS.state.shareOptin = share.checked === true;
      NS.storage.set("fairbon.share_optin.v1", NS.state.shareOptin);
    });
    business.addEventListener("change", function () {
      NS.state.businessExpenses = business.checked === true;
      NS.storage.set("fairbon.business_expenses", NS.state.businessExpenses);
      NS.emit("receipts-changed");
    });
    $("settings-reset").addEventListener("click", function () {
      NS.resetOwnerToken();
      NS.emit("receipts-changed");
      syncLabels();
    });
  }

  function bindOverlayKeys() {
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") { return; }
      var targets = [
        ["add-modal", "add-close"],
        ["receipt-modal", "receipt-close"],
        ["settings-modal", "settings-close"]
      ];
      for (var i = 0; i < targets.length; i += 1) {
        var modal = $(targets[i][0]);
        if (modal && !modal.hidden) {
          var close = $(targets[i][1]);
          if (close) { close.click(); }
          event.preventDefault();
          return;
        }
      }
    });
  }

  function initialTab() {
    var hash = (global.location.hash || "").replace("#", "");
    if (["overview", "receipts", "prices", "list"].indexOf(hash) >= 0) {
      return hash;
    }
    return "overview";
  }

  function bindShopping() {
    NS.on("shopping-search", function (terms) {
      if (!terms || !terms.length) { return; }
      switchTab("prices");
      NS.views.prices.setQuery(terms[0]);
      NS.views.prices.searchTerms(terms);
    });
    NS.on("plz-changed", function () {
      var postal = $("postal-code");
      if (postal) { postal.value = NS.state.postalCode; }
    });
    NS.on("tab", function () {});
  }

  function init() {
    bindTabs();
    bindSettings();
    bindOverlayKeys();
    bindShopping();
    global.addEventListener("hashchange", function () {
      switchTab(initialTab());
    });
    NS.views.prices.init();
    NS.views.list.init();
    NS.views.overview.init();
    NS.views.receipts.init();
    NS.components.addSheet.init();
    var plzPill = $("plz-pill");
    if (plzPill) { plzPill.textContent = "PLZ " + NS.state.postalCode; }
    switchTab(initialTab());

    if ("serviceWorker" in global.navigator) {
      global.navigator.serviceWorker.register("./sw.js").catch(function () {
        /* offline support is best-effort */
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
