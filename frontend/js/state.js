/* FairBon — shared app state (ES5).
   Global namespace: window.FairBon */
(function (global) {
  "use strict";

  var NS = global.FairBon = global.FairBon || {};

  NS.STORES = [
    { id: "lidl", label: "Lidl", bg: "#0050aa", fg: "#ffffff" },
    { id: "rewe", label: "Rewe", bg: "#cc071e", fg: "#ffffff" },
    { id: "edeka", label: "Edeka", bg: "#ffd800", fg: "#1b1f24" },
    { id: "aldi", label: "Aldi", bg: "#00457c", fg: "#ffffff" },
    { id: "penny", label: "Penny", bg: "#d40e1e", fg: "#ffffff" },
    { id: "netto", label: "Netto", bg: "#ffe500", fg: "#1b1f24" },
    { id: "kaufland", label: "Kaufland", bg: "#e10915", fg: "#ffffff" },
    { id: "rossmann", label: "Rossmann", bg: "#d40511", fg: "#ffffff" },
    { id: "dm", label: "dm", bg: "#005ca9", fg: "#ffffff" },
    { id: "globus", label: "Globus", bg: "#003a70", fg: "#ffffff" }
  ];

  NS.euro = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });
  NS.number = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 2 });

  NS.storage = {
    get: function (key, fallback) {
      try {
        var raw = global.localStorage.getItem(key);
        return raw === null ? fallback : JSON.parse(raw);
      } catch (e) {
        return fallback;
      }
    },
    set: function (key, value) {
      try {
        global.localStorage.setItem(key, JSON.stringify(value));
      } catch (e) {
        /* private mode / quota */
      }
    },
    remove: function (key) {
      try { global.localStorage.removeItem(key); } catch (e) { /* ignore */ }
    }
  };

  function uuid() {
    if (global.crypto && typeof global.crypto.randomUUID === "function") {
      return global.crypto.randomUUID();
    }
    var template = "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx";
    return template.replace(/[xy]/g, function (ch) {
      var r = (Math.random() * 16) | 0;
      var v = ch === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  var OWNER_KEY = "fairbon.owner_token.v1";
  var ownerToken = NS.storage.get(OWNER_KEY, null);
  if (!ownerToken) {
    ownerToken = uuid();
    NS.storage.set(OWNER_KEY, ownerToken);
  }

  NS.ownerToken = ownerToken;

  NS.resetOwnerToken = function () {
    NS.ownerToken = uuid();
    NS.storage.set(OWNER_KEY, NS.ownerToken);
    return NS.ownerToken;
  };

  NS.state = {
    postalCode: NS.storage.get("fairbon.plz", "65618"),
    country: NS.storage.get("fairbon.country", "DE"),
    budget: Number(NS.storage.get("fairbon.budget", 0)) || 0,
    budgetStart: Math.max(1, Math.min(28,
      Number(NS.storage.get("fairbon.budget_start", 1)) || 1)),
    byok: NS.storage.get("fairbon.byok", ""),
    byokProvider: NS.storage.get("fairbon.byokProvider", "openai_compatible"),
    shareOptin: NS.storage.get("fairbon.share_optin.v1", true) === true,
    requireCommunitySharing: false,
    businessExpenses: NS.storage.get("fairbon.business_expenses", false) === true,
    docEnhance: NS.storage.get("fairbon.doc_enhance", true) !== false,
    themeMode: NS.storage.get("fairbon.theme_mode", "system"),
    haptics: NS.storage.get("fairbon.haptics", true) !== false,
    coloredBadges: NS.storage.get("fairbon.colored_badges", true) !== false,
    tokenBackedUp: NS.storage.get("fairbon.token_backed_up", false) === true,
    onboardingDone: NS.storage.get("fairbon.onboarding_done", false) === true,
    onboardingSteps: NS.storage.get("fairbon.onboarding_steps", {}) || {},
    tab: "overview",
    month: ""
  };

  /** Short vibration where supported; silently ignored otherwise. */
  NS.haptic = function () {
    if (!NS.state.haptics) { return; }
    try {
      if (global.navigator && typeof global.navigator.vibrate === "function") {
        global.navigator.vibrate(15);
      }
    } catch (e) { /* haptics are best effort */ }
  };

  NS.setPostalCode = function (value) {
    var clean = String(value || "").replace(/\D/g, "").slice(0, 5);
    if (clean.length < 4) { return NS.state.postalCode; }
    NS.state.postalCode = clean;
    NS.storage.set("fairbon.plz", clean);
    return clean;
  };

  NS.storeInfo = function (id) {
    for (var i = 0; i < NS.STORES.length; i += 1) {
      if (NS.STORES[i].id === id) { return NS.STORES[i]; }
    }
    var label = String(id || "Unbekannt").replace(/[-_]+/g, " ");
    label = label.charAt(0).toUpperCase() + label.slice(1);
    return { id: id, label: label, bg: "#616b76", fg: "#ffffff" };
  };

  NS.storeBadge = function (store) {
    var badge = document.createElement("span");
    badge.className = "badge";
    badge.style.background = store.bg;
    badge.style.color = store.fg;
    badge.textContent = store.label;
    return badge;
  };

  NS.formatDate = function (iso) {
    if (!iso) { return ""; }
    var date = new Date(iso);
    if (isNaN(date.getTime())) { return String(iso).slice(0, 10); }
    return date.toLocaleDateString("de-DE", {
      day: "2-digit", month: "2-digit", year: "numeric",
      timeZone: "Europe/Berlin"
    });
  };

  NS.formatMonth = function (ym) {
    if (!ym) { return ""; }
    var parts = String(ym).split("-");
    var date = new Date(Number(parts[0]), Number(parts[1]) - 1, 1);
    return date.toLocaleDateString("de-DE", { month: "long", year: "numeric" });
  };

  // --- basket (shared between prices & list tabs) -----------------------
  var BASKET_KEY = "fairbon.basket.v1";
  NS.basket = NS.storage.get(BASKET_KEY, []);

  NS.saveBasket = function () {
    NS.storage.set(BASKET_KEY, NS.basket);
    NS.emit("basket-changed");
  };

  NS.addToBasket = function (entry) {
    var key = (entry.name || "") + "|" + (entry.store || "");
    for (var i = 0; i < NS.basket.length; i += 1) {
      if (NS.basket[i].key === key) { return false; }
    }
    NS.basket.push({
      key: key,
      name: entry.name || "",
      brand: entry.brand || null,
      store: entry.store || null,
      price: typeof entry.price === "number" ? entry.price : null,
      unit_price: typeof entry.unit_price === "number" ? entry.unit_price : null,
      quantity: entry.quantity || null,
      unit: entry.unit || null
    });
    NS.saveBasket();
    return true;
  };

  NS.clearBasket = function () {
    NS.basket = [];
    NS.saveBasket();
  };

  // --- tiny event bus ---------------------------------------------------
  var listeners = {};
  NS.on = function (name, fn) {
    (listeners[name] = listeners[name] || []).push(fn);
    return fn;
  };
  NS.emit = function (name, payload) {
    var fns = listeners[name] || [];
    for (var i = 0; i < fns.length; i += 1) {
      try { fns[i](payload); } catch (e) { /* one listener must not break others */ }
    }
  };
})(window);
