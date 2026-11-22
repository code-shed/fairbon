/* FairBon — static demo receipt (no API, no rate-limit, no vision call).
   All amounts are integer cents; discounts/deposits are carried separately so
   the same data can drive the preview, the checklist and the saved receipt. */
(function (global) {
  "use strict";

  var NS = global.FairBon = global.FairBon || {};
  var DEMO_KEY = "fairbon.demo_receipts.v1";

  function todayIso() {
    var now = new Date();
    return now.getFullYear() + "-" +
      String(now.getMonth() + 1).padStart(2, "0") + "-" +
      String(now.getDate()).padStart(2, "0");
  }

  var ITEMS = [
    {
      raw_text: "BIO VOLLMILCH 1L",
      normalized_name: "Bio Vollmilch 1L",
      brand: "Weihenstephan",
      category: "Lebensmittel",
      quantity: 1.0,
      unit: "l",
      price_cents: 129,
      unit_price_cents: 129,
      discount_cents: 0,
      deposit_cents: 0,
      vat_rate: 7.0
    },
    {
      raw_text: "BUTTER 250G",
      normalized_name: "Butter 250g",
      brand: "Weihenstephan",
      category: "Lebensmittel",
      quantity: 0.25,
      unit: "kg",
      price_cents: 249,
      unit_price_cents: 996,
      discount_cents: 60,
      deposit_cents: 0,
      vat_rate: 7.0
    },
    {
      raw_text: "BANANEN 0,912 KG",
      normalized_name: "Bananen",
      brand: null,
      category: "Lebensmittel",
      quantity: 0.912,
      unit: "kg",
      price_cents: 181,
      unit_price_cents: 198,
      discount_cents: 0,
      deposit_cents: 0,
      vat_rate: 7.0
    },
    {
      raw_text: "HAEHNCHENBRUST 400G",
      normalized_name: "Hähnchenbrust 400g",
      brand: null,
      category: "Lebensmittel",
      quantity: 0.4,
      unit: "kg",
      price_cents: 349,
      unit_price_cents: 873,
      discount_cents: 150,
      deposit_cents: 0,
      vat_rate: 7.0
    },
    {
      raw_text: "KAFFEE 500G",
      normalized_name: "Kaffee 500g",
      brand: "Melitta",
      category: "Lebensmittel",
      quantity: 0.5,
      unit: "kg",
      price_cents: 549,
      unit_price_cents: 1098,
      discount_cents: 0,
      deposit_cents: 0,
      vat_rate: 7.0
    },
    {
      raw_text: "SCHOKOLADE 100G",
      normalized_name: "Schokolade 100g",
      brand: "Ritter Sport",
      category: "Lebensmittel",
      quantity: 0.1,
      unit: "kg",
      price_cents: 119,
      unit_price_cents: 1190,
      discount_cents: 0,
      deposit_cents: 0,
      vat_rate: 7.0
    },
    {
      raw_text: "MINERALWASSER 1,5L",
      normalized_name: "Mineralwasser 1,5L",
      brand: "Gerolsteiner",
      category: "Getränke",
      quantity: 1.5,
      unit: "l",
      price_cents: 89,
      unit_price_cents: 59,
      discount_cents: 0,
      deposit_cents: 25,
      vat_rate: 19.0
    },
    {
      raw_text: "SPUELMITTEL",
      normalized_name: "Spülmittel",
      brand: "Frosch",
      category: "Haushalt",
      quantity: 1.0,
      unit: "stueck",
      price_cents: 149,
      unit_price_cents: null,
      discount_cents: 0,
      deposit_cents: 0,
      vat_rate: 19.0
    },
    {
      raw_text: "BUEROBLOCK A5",
      normalized_name: "Büroblock A5",
      brand: null,
      category: "Technik/Non-Food",
      quantity: 1.0,
      unit: "stueck",
      price_cents: 299,
      unit_price_cents: null,
      discount_cents: 0,
      deposit_cents: 0,
      vat_rate: 19.0
    }
  ];

  NS.demo = {
    /** Return a fresh demo receipt with today's date (deep copy). */
    build: function () {
      var items = ITEMS.map(function (item) {
        var copy = {};
        for (var key in item) {
          if (Object.prototype.hasOwnProperty.call(item, key)) { copy[key] = item[key]; }
        }
        return copy;
      });
      var total = items.reduce(function (sum, item) {
        return sum + item.price_cents + item.deposit_cents;
      }, 0);
      var savings = items.reduce(function (sum, item) {
        return sum + item.discount_cents;
      }, 0);
      return {
        store: "Frischmarkt",
        postal_code: "65618",
        date: todayIso(),
        currency: "EUR",
        items: items,
        total_cents: total,
        savings_cents: savings,
        engine: "demo"
      };
    },

    /** Remember which saved receipt ids were the demo (localStorage only). */
    markSaved: function (receiptId) {
      var ids = NS.demo.savedIds();
      if (ids.indexOf(receiptId) < 0) { ids.push(receiptId); }
      NS.storage.set(DEMO_KEY, ids);
    },

    unmarkSaved: function (receiptId) {
      NS.storage.set(DEMO_KEY, NS.demo.savedIds().filter(function (id) {
        return id !== receiptId;
      }));
    },

    isSaved: function (receiptId) {
      return NS.demo.savedIds().indexOf(receiptId) >= 0;
    },

    savedIds: function () {
      var ids = NS.storage.get(DEMO_KEY, []);
      return Array.isArray(ids) ? ids : [];
    }
  };
})(window);
