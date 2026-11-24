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
    // The floating add button is available on every tab, including overview.
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

  function updateSharingUI() {
    var forced = NS.state.requireCommunitySharing === true && !NS.state.byok;
    var switchEl = $("settings-share");
    if (switchEl) {
      var row = switchEl.closest("label");
      if (row) { row.hidden = forced; }
    }
    NS.emit("sharing-mode-changed", { forced: forced });
  }

  // --- appearance -------------------------------------------------------
  function applyTheme() {
    var mode = NS.state.themeMode || "system";
    var root = document.documentElement;
    if (mode === "system") { root.removeAttribute("data-theme"); }
    else { root.setAttribute("data-theme", mode); }
    var dark = mode === "dark" ||
      (mode === "system" && global.matchMedia &&
       global.matchMedia("(prefers-color-scheme: dark)").matches);
    var label = $("theme-label");
    if (label) { label.textContent = dark ? "Mach das Licht an" : "Mach das Licht aus"; }
    var icon = $("theme-icon");
    if (icon) {
      icon.textContent = "";
      var ns = "http://www.w3.org/2000/svg";
      var svg = document.createElementNS(ns, "svg");
      svg.setAttribute("viewBox", "0 0 24 24");
      svg.setAttribute("fill", "none");
      svg.setAttribute("stroke", "currentColor");
      svg.setAttribute("stroke-width", "1.8");
      var shape = document.createElementNS(ns, dark ? "circle" : "path");
      if (dark) {
        shape.setAttribute("cx", "12");
        shape.setAttribute("cy", "12");
        shape.setAttribute("r", "8");
      } else {
        shape.setAttribute("d",
          "M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6l1.4 1.4" +
          "m10 10 1.4 1.4m0-12.8L17 7M7 17l-1.4 1.4");
      }
      svg.appendChild(shape);
      icon.appendChild(svg);
    }
  }

  // --- onboarding checklist ---------------------------------------------
  function onboardingTargets() {
    return [
      { text: "Ersten Bon oder eBon erfassen", key: "receipt" },
      { text: "PLZ / Region festlegen", key: "plz" },
      { text: "Ersten Artikel per Barcode verifizieren", key: "barcode" },
      { text: "Einkaufsliste im Tab Liste testen", key: "list" },
      { text: "Gast-Token einmal sichern (Backup)", key: "token" }
    ];
  }

  function computeOnboarding() {
    return NS.api.get("/api/v1/receipts").then(function (receipts) {
      var hasBarcode = (receipts || []).some(function (receipt) {
        return (receipt.items || []).some(function (item) { return !!item.ean; });
      });
      var plzSet = NS.storage.get("fairbon.plz", null) !== null;
      var stepFlags = {
        receipt: (receipts || []).length > 0,
        plz: plzSet,
        barcode: hasBarcode,
        list: NS.storage.get("fairbon.onboarding.list_used", false) === true,
        token: NS.state.tokenBackedUp === true
      };
      var saved = NS.state.onboardingSteps || {};
      var steps = onboardingTargets().map(function (target) {
        return {
          text: target.text, key: target.key,
          done: stepFlags[target.key] === true || saved[target.key] === true
        };
      });
      NS.state.onboardingSteps = steps.reduce(function (all, step) {
        all[step.key] = step.done;
        return all;
      }, {});
      NS.storage.set("fairbon.onboarding_steps", NS.state.onboardingSteps);
      if (steps.every(function (step) { return step.done; })) {
        NS.state.onboardingDone = true;
        NS.storage.set("fairbon.onboarding_done", true);
      }
      return steps;
    }).catch(function () {
      return onboardingTargets().map(function (target) {
        return {
          text: target.text, key: target.key,
          done: NS.state.onboardingSteps[target.key] === true
        };
      });
    });
  }

  function refreshOnboardingTile() {
    computeOnboarding().then(function (steps) {
      var done = steps.filter(function (step) { return step.done; }).length;
      var progress = $("onboarding-progress");
      if (progress) { progress.textContent = done + "/" + steps.length; }
      var tile = $("tile-onboarding");
      if (tile) { tile.hidden = NS.state.onboardingDone === true; }
      NS.emit("onboarding-progress", { done: done, total: steps.length });
    });
  }

  function openOnboarding() {
    computeOnboarding().then(function (steps) {
      var list = $("onboarding-steps");
      var summary = $("onboarding-summary");
      var done = steps.filter(function (step) { return step.done; }).length;
      if (summary) { summary.textContent = done + " von " + steps.length + " erledigt"; }
      if (!list) { return; }
      list.textContent = "";
      steps.forEach(function (step) {
        var li = document.createElement("li");
        if (step.done) { li.className = "done"; }
        li.textContent = (step.done ? "✓ " : "○ ") + step.text;
        list.appendChild(li);
      });
      $("onboarding-modal").hidden = false;
      $("onboarding-backdrop").hidden = false;
    });
  }

  function storageInfo() {
    var count = 0;
    var bytes = 0;
    try {
      for (var i = 0; i < global.localStorage.length; i += 1) {
        var key = global.localStorage.key(i);
        if (!key || key === "fairbon.owner_token.v1") { continue; }
        count += 1;
        bytes += (global.localStorage.getItem(key) || "").length;
      }
    } catch (e) { /* private mode */ }
    var el = $("settings-storage-info");
    if (el) {
      el.textContent = count + " lokale Einträge · ca. " +
        Math.round(bytes / 1024) + " KB im Browser gespeichert.";
    }
  }

  function bindSettings() {
    var modal = $("settings-modal");
    var backdrop = $("settings-backdrop");
    var country = $("settings-country");
    var budget = $("settings-budget");
    var budgetStart = $("settings-budget-start");
    var byok = $("settings-byok");
    var byokProvider = $("settings-byok-provider");
    var share = $("settings-share");
    var business = $("settings-business");
    var docEnhance = $("settings-doc-enhance");
    var systemTheme = $("settings-system-theme");
    var themeBtn = $("settings-theme-btn");
    var haptics = $("settings-haptics");
    var tokenCopy = $("settings-token-copy");
    var tokenRestore = $("settings-token-restore");
    var tokenRestoreBtn = $("settings-token-restore-btn");
    var tokenFeedback = $("settings-token-feedback");

    function tokenMessage(text, isError) {
      tokenFeedback.textContent = text;
      tokenFeedback.hidden = false;
      tokenFeedback.setAttribute("role", isError ? "alert" : "status");
    }

    function copyToken() {
      var value = NS.ownerToken || "";
      function done() {
        NS.state.tokenBackedUp = true;
        NS.storage.set("fairbon.token_backed_up", true);
        refreshOnboardingTile();
        tokenMessage("Kopiert! ✓", false);
      }
      function fallback() {
        var field = document.createElement("textarea");
        field.value = value;
        field.setAttribute("readonly", "");
        field.style.position = "fixed";
        field.style.opacity = "0";
        document.body.appendChild(field);
        field.select();
        try { document.execCommand("copy"); done(); }
        catch (e) { tokenMessage("Kopieren nicht möglich – bitte manuell markieren.", true); }
        document.body.removeChild(field);
      }
      if (global.navigator.clipboard && global.navigator.clipboard.writeText) {
        global.navigator.clipboard.writeText(value).then(done).catch(fallback);
      } else { fallback(); }
    }

    function syncLabels() {
      country.value = NS.state.country || "DE";
      budget.value = NS.state.budget ? String(NS.state.budget) : "";
      budgetStart.value = String(NS.state.budgetStart || 1);
      byok.value = NS.state.byok || "";
      byokProvider.value = NS.state.byokProvider || "openai_compatible";
      share.checked = NS.state.shareOptin === true;
      business.checked = NS.state.businessExpenses === true;
      docEnhance.checked = NS.state.docEnhance !== false;
      systemTheme.checked = (NS.state.themeMode || "system") === "system";
      haptics.checked = NS.state.haptics !== false;
      storageInfo();
      applyTheme();
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

    country.addEventListener("change", function () {
      NS.state.country = country.value;
      NS.storage.set("fairbon.country", country.value);
    });
    budget.addEventListener("change", function () {
      NS.state.budget = Math.max(0, Number(budget.value) || 0);
      NS.storage.set("fairbon.budget", NS.state.budget);
      NS.emit("receipts-changed");
    });
    budgetStart.addEventListener("change", function () {
      var day = Math.max(1, Math.min(28, Number(budgetStart.value) || 1));
      NS.state.budgetStart = day;
      budgetStart.value = String(day);
      NS.storage.set("fairbon.budget_start", day);
      NS.emit("receipts-changed");
    });
    systemTheme.addEventListener("change", function () {
      NS.state.themeMode = systemTheme.checked ? "system" :
        ((NS.state.themeMode === "dark") ? "dark" : "light");
      NS.storage.set("fairbon.theme_mode", NS.state.themeMode);
      applyTheme();
    });
    themeBtn.addEventListener("click", function () {
      systemTheme.checked = false;
      var dark = document.documentElement.getAttribute("data-theme") === "dark";
      NS.state.themeMode = dark ? "light" : "dark";
      NS.storage.set("fairbon.theme_mode", NS.state.themeMode);
      applyTheme();
      NS.haptic();
    });
    haptics.addEventListener("change", function () {
      NS.state.haptics = haptics.checked === true;
      NS.storage.set("fairbon.haptics", NS.state.haptics);
      if (NS.state.haptics) { NS.haptic(); }
    });
    $("settings-clear-cache").addEventListener("click", function () {
      if (!global.confirm("Temporäre App-Caches leeren? Deine Bons und der Token bleiben erhalten.")) {
        return;
      }
      if (global.caches && global.caches.keys) {
        global.caches.keys().then(function (keys) {
          keys.filter(function (key) { return String(key).indexOf("fairbon") === 0; })
            .forEach(function (key) { global.caches.delete(key); });
        }).catch(function () { /* offline */ });
      }
      storageInfo();
      tokenMessage("Caches geleert.", false);
    });
    $("settings-changelog").addEventListener("click", function () {
      $("changelog-modal").hidden = false;
      $("changelog-backdrop").hidden = false;
    });
    $("changelog-close").addEventListener("click", function () {
      $("changelog-modal").hidden = true;
      $("changelog-backdrop").hidden = true;
    });
    $("changelog-backdrop").addEventListener("click", function () {
      $("changelog-modal").hidden = true;
      $("changelog-backdrop").hidden = true;
    });
    $("settings-onboarding").addEventListener("click", function () {
      close();
      openOnboarding();
    });
    $("onboarding-close").addEventListener("click", function () {
      $("onboarding-modal").hidden = true;
      $("onboarding-backdrop").hidden = true;
    });
    $("onboarding-backdrop").addEventListener("click", function () {
      $("onboarding-modal").hidden = true;
      $("onboarding-backdrop").hidden = true;
    });
    byok.addEventListener("change", function () {
      NS.state.byok = byok.value.trim();
      NS.storage.set("fairbon.byok", NS.state.byok);
      updateSharingUI();
    });
    byokProvider.addEventListener("change", function () {
      NS.state.byokProvider = byokProvider.value;
      NS.storage.set("fairbon.byokProvider", NS.state.byokProvider);
    });
    share.addEventListener("change", function () {
      NS.state.shareOptin = share.checked === true;
      NS.storage.set("fairbon.share_optin.v1", NS.state.shareOptin);
    });
    docEnhance.addEventListener("change", function () {
      NS.state.docEnhance = docEnhance.checked === true;
      NS.storage.set("fairbon.doc_enhance", NS.state.docEnhance);
    });
    business.addEventListener("change", function () {
      NS.state.businessExpenses = business.checked === true;
      NS.storage.set("fairbon.business_expenses", NS.state.businessExpenses);
      NS.emit("receipts-changed");
    });
    tokenCopy.addEventListener("click", copyToken);
    tokenRestoreBtn.addEventListener("click", function () {
      var value = (tokenRestore.value || "").trim();
      if (!/^[A-Za-z0-9._-]{8,128}$/.test(value)) {
        tokenMessage("Token ungültig – 8 bis 128 Zeichen erforderlich.", true);
        return;
      }
      NS.storage.set("fairbon.owner_token.v1", value);
      global.location.reload();
    });
    $("settings-reset").addEventListener("click", function () {
      if (!global.confirm(
        "Neuen Gast-Token erzeugen? Deine bisherigen Bons sind dann nicht " +
        "mehr sichtbar. Kopiere den aktuellen Token vorher für die Wiederherstellung."
      )) { return; }
      NS.resetOwnerToken();
      NS.emit("receipts-changed");
      syncLabels();
      tokenMessage("Neuer Token erzeugt – bitte kopieren und sichern.", false);
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
    applyTheme();
    updateSharingUI();
    NS.api.get("/health").then(function (config) {
      NS.state.requireCommunitySharing = config.require_community_sharing === true;
      updateSharingUI();
    }).catch(function () { /* offline: keep the self-hosted default */ });
    if (global.matchMedia && global.matchMedia("(prefers-color-scheme: dark)").addEventListener) {
      global.matchMedia("(prefers-color-scheme: dark)").addEventListener(
        "change", function () {
          if ((NS.state.themeMode || "system") === "system") { applyTheme(); }
        }
      );
    }
    var onboardTile = $("tile-onboarding");
    if (onboardTile) {
      onboardTile.addEventListener("click", function (event) {
        if (event.target && event.target.id === "tile-onboarding-close") { return; }
        openOnboarding();
      });
      onboardTile.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") { openOnboarding(); }
      });
    }
    var closeTile = $("tile-onboarding-close");
    if (closeTile) {
      closeTile.addEventListener("click", function () {
        NS.state.onboardingDone = true;
        NS.storage.set("fairbon.onboarding_done", true);
        if (onboardTile) { onboardTile.hidden = true; }
      });
    }
    var communityTile = $("tile-community");
    if (communityTile) {
      communityTile.addEventListener("click", function () {
        NS.emit("tab", { tab: "prices" });
      });
    }
    NS.on("receipts-changed", refreshOnboardingTile);
    refreshOnboardingTile();
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
