/* FairBon — "Bon erfassen" bottom sheet (ES5).
   Photo/PDF/eBon OR the static demo receipt -> scan progress -> editable
   preview with discount/deposit badges and a cent-exact sum check. */
(function (global) {
  "use strict";

  var NS = global.FairBon = global.FairBon || {};
  var euro = NS.euro;
  var els = {};
  var scanned = null;      // latest scan/demo result
  var items = [];          // editable working copy
  var isDemo = false;      // demo mode: never share with the community
  var progress = null;     // scan checklist controller
  var queue = [];          // receipts of a multi-page PDF, one preview each
  var queueIndex = 0;
  var queueSaved = 0;
  var queueWarnings = [];

  var DEMO_BANNER_KEY = "fairbon.demo_banner_seen.v1";

  function $(id) { return document.getElementById(id); }

  function init() {
    els.modal = $("add-modal");
    els.backdrop = $("add-backdrop");
    els.pdf = $("add-pdf");
    els.error = $("add-error");
    els.preview = $("add-preview");
    els.items = $("add-items");
    els.save = $("add-save");
    els.progressSection = $("scan-progress");
    els.progressBox = $("scan-checklist");
    els.card = $("demo-receipt-card");
    els.badge = $("demo-badge");
    els.demoNote = $("demo-note");
    els.summary = $("add-summary");
    els.banner = $("demo-banner");
    els.queueInfo = $("add-queue-info");
    els.storeField = $("add-store");
    els.businessWrap = $("add-business-wrap");
    els.business = $("add-business");
    els.warnings = $("add-warnings");
    els.skip = $("add-skip");
    if (!els.modal) { return; }

    $("add-receipt-fab").addEventListener("click", function () { open(false); });
    $("add-receipt-cta").addEventListener("click", function () { open(false); });
    var demoCta = $("demo-receipt-cta");
    if (demoCta) { demoCta.addEventListener("click", function () { open(true); }); }
    var demoAdd = $("demo-receipt-add");
    if (demoAdd) { demoAdd.addEventListener("click", function () { open(true); }); }

    $("add-close").addEventListener("click", close);
    els.backdrop.addEventListener("click", close);
    $("add-photo").addEventListener("click", function () {
      NS.platform.pickImage().then(function (file) {
        if (file) { scanFile(file, true); }
      });
    });
    $("add-ebon").addEventListener("click", function () {
      els.pdf.value = "";
      els.pdf.click();
    });
    els.pdf.addEventListener("change", function () {
      var file = els.pdf.files && els.pdf.files[0];
      if (file) { scanFile(file, false); }
    });
    $("add-manual").addEventListener("click", manual);
    els.save.addEventListener("click", save);
    els.skip.addEventListener("click", skipQueued);
    var storeOptions = $("store-options");
    if (storeOptions && !storeOptions.options.length) {
      NS.STORES.forEach(function (store) {
        var option = document.createElement("option");
        option.value = store.id;
        option.label = store.label;
        storeOptions.appendChild(option);
      });
    }
    var closeBanner = $("demo-banner-close");
    if (closeBanner) {
      closeBanner.addEventListener("click", function () {
        els.banner.hidden = true;
        NS.storage.set(DEMO_BANNER_KEY, true);
      });
    }
  }

  function open(demoMode) {
    scanned = null;
    items = [];
    queue = [];
    queueIndex = 0;
    queueSaved = 0;
    queueWarnings = [];
    isDemo = !!demoMode;
    progress = null;
    els.preview.hidden = true;
    els.error.hidden = true;
    els.error.textContent = "";
    els.progressSection.hidden = true;
    els.card.hidden = true;
    els.card.textContent = "";
    els.badge.hidden = !isDemo;
    els.demoNote.hidden = !isDemo;
    els.banner.hidden = true;
    els.summary.hidden = true;
    els.summary.textContent = "";
    els.save.textContent = isDemo ? "Als Demo speichern" : "Bon speichern";
    els.businessWrap.hidden = NS.state.businessExpenses !== true;
    els.business.checked = false;
    els.modal.hidden = false;
    els.backdrop.hidden = false;
    var close = $("add-close");
    if (close) { close.focus(); }
    if (isDemo) { startDemo(); }
  }

  function close() {
    els.modal.hidden = true;
    els.backdrop.hidden = true;
  }

  function showError(message) {
    els.error.hidden = !message;
    els.error.textContent = message || "";
  }

  function resetError() {
    els.error.hidden = true;
    els.error.textContent = "";
  }

  function setTilesDisabled(disabled) {
    ["add-photo", "add-ebon", "add-manual"].forEach(function (id) {
      var tile = $(id);
      if (tile) { tile.disabled = disabled; }
    });
  }

  // --- demo -------------------------------------------------------------
  function startDemo() {
    var demo = NS.demo.build();
    scanned = demo;
    items = demo.items.map(function (item) { return copyItem(item); });
    renderDemoCard(demo);
    els.progressSection.hidden = false;
    progress = NS.components.scanProgress.create(els.progressBox, [
      "Markt & Datum erkannt",
      items.length + " Artikel ausgelesen & kategorisiert",
      "Rabatte, Pfand & MwSt. (7 % / 19 %) zugeordnet",
      "Summe geprüft – stimmt auf den Cent"
    ]);
    // bring the checklist into view inside the sheet
    if (els.modal && els.progressSection) {
      els.modal.scrollTop = Math.max(0, els.progressSection.offsetTop - 12);
    }
    progress.playDemo().then(function () {
      renderPreview(true);
      setTilesDisabled(false);
    });
  }

  function renderDemoCard(demo) {
    var card = els.card;
    card.textContent = "";
    var head = document.createElement("div");
    head.className = "receipt-head";
    var store = document.createElement("strong");
    store.textContent = demo.store.toUpperCase();
    var meta = document.createElement("span");
    meta.textContent = "PLZ " + demo.postal_code + " · " + NS.formatDate(demo.date);
    head.appendChild(store);
    head.appendChild(meta);
    card.appendChild(head);

    var list = document.createElement("ul");
    list.className = "receipt-mini";
    demo.items.forEach(function (item) {
      var li = document.createElement("li");
      var name = document.createElement("span");
      name.textContent = item.normalized_name;
      var price = document.createElement("span");
      price.textContent = euro.format(item.price_cents / 100);
      li.appendChild(name);
      li.appendChild(price);
      list.appendChild(li);
    });
    card.appendChild(list);

    var total = document.createElement("div");
    total.className = "receipt-total-row";
    var label = document.createElement("strong");
    label.textContent = "SUMME";
    var value = document.createElement("strong");
    value.textContent = euro.format(demo.total_cents / 100);
    total.appendChild(label);
    total.appendChild(value);
    card.appendChild(total);
    card.hidden = false;
  }

  // --- real scans -------------------------------------------------------
  function scanFile(file, isImage) {
    resetError();
    setTilesDisabled(true);
    var prepare = isImage
      ? NS.platform.compressImage(
          file, undefined, undefined, NS.state.docEnhance !== false
        ).catch(function () { return file; })
      : Promise.resolve(file);

    prepare.then(function (payload) {
      els.progressSection.hidden = false;
      els.card.hidden = true;
      progress = NS.components.scanProgress.create(els.progressBox, [
        "Markt & Datum erkannt",
        "Artikel ausgelesen & kategorisiert",
        "Rabatte, Pfand & MwSt. (7 % / 19 %) zugeordnet",
        "Summe geprüft"
      ]);
      progress.start();
      var form = new FormData();
      form.append("file", payload, payload.name || "receipt");
      if (global.FAIRBON_TURNSTILE_TOKEN) {
        form.append("turnstile_token", global.FAIRBON_TURNSTILE_TOKEN);
      }
      return NS.api.postForm("/api/v1/receipts/scan", form);
    }).then(function (result) {
      resetError();
      queue = result.receipts && result.receipts.length ? result.receipts : [];
      queueIndex = 0;
      queueSaved = 0;
      queueWarnings = result.warnings || [];
      scanned = queue.length ? queue[0] : result;
      items = (scanned.items || []).map(copyItem);
      var check = sumCheck(scanned, items);
      var steps = [
        [0, null],
        [1, items.length + " Artikel ausgelesen & kategorisiert"],
        [2, null]
      ];
      var chain = Promise.resolve();
      steps.forEach(function (step) {
        chain = chain.then(function () {
          return new Promise(function (resolve) {
            global.setTimeout(function () {
              progress.complete(step[0], step[1]);
              resolve();
            }, 120);
          });
        });
      });
      chain.then(function () {
        return new Promise(function (resolve) {
          global.setTimeout(resolve, 120);
        });
      }).then(function () {
        if (check.warning) {
          progress.warning(3, check.warning);
        } else {
          progress.complete(3, "Summe geprüft – stimmt auf den Cent");
        }
        renderPreview(false);
        setTilesDisabled(false);
      });
    }).catch(function (error) {
      setTilesDisabled(false);
      showError(error.message || "Scan fehlgeschlagen.");
    });
  }

  function manual() {
    isDemo = false;
    queue = [];
    queueIndex = 0;
    scanned = {
      store: "Sonstiges",
      postal_code: NS.state.postalCode,
      date: todayIso(),
      currency: "EUR"
    };
    items = [{
      raw_text: "",
      normalized_name: "",
      brand: null,
      category: "Sonstiges",
      quantity: 1,
      unit: "stueck",
      price_cents: 0,
      unit_price_cents: null,
      discount_cents: 0,
      deposit_cents: 0,
      vat_rate: 19,
      is_private: false
    }];
    els.progressSection.hidden = true;
    setTilesDisabled(false);
    renderPreview(false);
  }

  function copyItem(item) {
    return {
      raw_text: item.raw_text || "",
      normalized_name: item.normalized_name || item.raw_text || "",
      brand: item.brand || null,
      category: item.category || "Sonstiges",
      quantity: item.quantity || 1,
      unit: item.unit || "stueck",
      price_cents: item.price_cents || 0,
      unit_price_cents: item.unit_price_cents || null,
      discount_cents: item.discount_cents || 0,
      deposit_cents: item.deposit_cents || 0,
      vat_rate: item.vat_rate != null ? item.vat_rate : null,
      is_private: !!item.is_private
    };
  }

  function todayIso() {
    var now = new Date();
    return now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") +
      "-" + String(now.getDate()).padStart(2, "0");
  }

  // --- preview ----------------------------------------------------------
  function renderPreview(fromDemo) {
    els.preview.hidden = false;
    els.items.textContent = "";
    els.storeField.value = (scanned && scanned.store) || "";
    els.banner.hidden = !(fromDemo && !NS.storage.get(DEMO_BANNER_KEY, false));

    items.forEach(function (item, index) {
      els.items.appendChild(renderRow(item, index));
    });
    renderSummary();
    renderQueueInfo();
  }

  function showQueued(index) {
    queueIndex = index;
    scanned = queue[index];
    items = (scanned.items || []).map(copyItem);
    resetError();
    renderPreview(false);
    els.modal.scrollTop = 0;
  }

  function renderQueueInfo() {
    els.warnings.hidden = !queueWarnings.length;
    els.warnings.textContent = queueWarnings.join(" ");
    var multi = queue.length > 1;
    els.queueInfo.hidden = !multi;
    els.skip.hidden = !multi;
    if (!multi) {
      els.queueInfo.textContent = "";
      return;
    }
    var page = scanned && scanned.page ? " (Seite " + scanned.page + ")" : "";
    var saved = queueSaved ? queueSaved + " gespeichert · " : "";
    els.queueInfo.textContent = saved + "Bon " + (queueIndex + 1) + " von " +
      queue.length + " aus dem PDF" + page + ".";
  }

  function skipQueued() {
    if (queueIndex + 1 < queue.length) {
      showQueued(queueIndex + 1);
      return;
    }
    close();
  }

  function renderRow(item, index) {
    var li = document.createElement("li");
    li.className = "receipt-item editable";

    var summary = document.createElement("button");
    summary.type = "button";
    summary.className = "item-summary";

    var name = document.createElement("span");
    name.className = "item-name";
    name.textContent = item.normalized_name || "Artikel";
    var price = document.createElement("span");
    price.className = "item-price";
    price.textContent = euro.format((item.price_cents + item.deposit_cents) / 100);
    summary.appendChild(name);
    summary.appendChild(price);

    var badges = document.createElement("span");
    badges.className = "item-badges";
    if (item.discount_cents > 0) {
      var discount = document.createElement("span");
      discount.className = "pill-badge discount";
      discount.textContent = "−" + euro.format(item.discount_cents / 100) + " Rabatt";
      badges.appendChild(discount);
    }
    if (item.deposit_cents > 0) {
      var deposit = document.createElement("span");
      deposit.className = "pill-badge deposit";
      deposit.textContent = "+" + euro.format(item.deposit_cents / 100) + " Pfand";
      badges.appendChild(deposit);
    }
    if (item.is_private) {
      var privateBadge = document.createElement("span");
      privateBadge.className = "pill-badge private";
      privateBadge.textContent = "privat";
      badges.appendChild(privateBadge);
    }
    if (badges.childNodes.length) { summary.appendChild(badges); }
    li.appendChild(summary);

    var editor = document.createElement("div");
    editor.className = "item-editor";
    editor.hidden = true;

    var nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.value = item.normalized_name;
    nameInput.setAttribute("aria-label", "Artikelname");
    nameInput.addEventListener("input", function () {
      item.normalized_name = nameInput.value;
      name.textContent = nameInput.value || "Artikel";
    });

    var priceInput = document.createElement("input");
    priceInput.type = "number";
    priceInput.step = "0.01";
    priceInput.min = "0";
    priceInput.value = (item.price_cents / 100).toFixed(2);
    priceInput.setAttribute("aria-label", "Preis in Euro");
    priceInput.addEventListener("input", function () {
      item.price_cents = Math.round((Number(priceInput.value) || 0) * 100);
      price.textContent = euro.format((item.price_cents + item.deposit_cents) / 100);
      renderSummary();
    });

    var vat = document.createElement("select");
    vat.setAttribute("aria-label", "MwSt-Satz");
    var rates = [19, 7, 0];
    if (item.vat_rate != null && rates.indexOf(Number(item.vat_rate)) < 0) {
      rates.push(Number(item.vat_rate));
    }
    rates.forEach(function (rate) {
      var option = document.createElement("option");
      option.value = String(rate);
      option.textContent = rate + " % MwSt.";
      vat.appendChild(option);
    });
    vat.value = String(item.vat_rate != null ? item.vat_rate : 19);
    vat.addEventListener("change", function () {
      item.vat_rate = Number(vat.value);
    });

    var category = document.createElement("select");
    category.setAttribute("aria-label", "Kategorie");
    ["Lebensmittel", "Getränke", "Drogerie", "Haushalt", "Bäcker/Gastronomie",
      "Technik/Non-Food", "Pfand", "Sonstiges"].forEach(function (label) {
      var option = document.createElement("option");
      option.value = label;
      option.textContent = label;
      category.appendChild(option);
    });
    category.value = item.category || "Sonstiges";
    category.addEventListener("change", function () {
      item.category = category.value;
    });

    var privateLabel = document.createElement("label");
    privateLabel.className = "switch item-private";
    var privateInput = document.createElement("input");
    privateInput.type = "checkbox";
    privateInput.checked = item.is_private;
    privateInput.addEventListener("change", function () {
      item.is_private = privateInput.checked;
      renderPreview(isDemo);
    });
    var privateText = document.createElement("span");
    privateText.textContent = "Privat (nicht exportieren)";
    privateLabel.appendChild(privateInput);
    privateLabel.appendChild(privateText);

    editor.appendChild(nameInput);
    editor.appendChild(priceInput);
    editor.appendChild(vat);
    editor.appendChild(category);
    editor.appendChild(privateLabel);
    li.appendChild(editor);

    summary.setAttribute("aria-expanded", "false");
    summary.addEventListener("click", function () {
      editor.hidden = !editor.hidden;
      summary.setAttribute("aria-expanded", String(!editor.hidden));
      li.className = "receipt-item editable" + (editor.hidden ? "" : " open");
    });
    return li;
  }

  function totalCents() {
    return items.reduce(function (sum, item) {
      return sum + (item.price_cents || 0) + (item.deposit_cents || 0);
    }, 0);
  }

  function savingsCents() {
    return items.reduce(function (sum, item) {
      return sum + (item.discount_cents || 0);
    }, 0);
  }

  function renderSummary() {
    els.summary.hidden = false;
    els.summary.textContent = "";
    var total = document.createElement("div");
    total.className = "summary-total";
    var label = document.createElement("span");
    label.textContent = "Gesamt";
    var value = document.createElement("strong");
    value.textContent = euro.format(totalCents() / 100);
    total.appendChild(label);
    total.appendChild(value);
    els.summary.appendChild(total);

    var savings = savingsCents();
    if (savings > 0) {
      var saved = document.createElement("p");
      saved.className = "summary-savings";
      saved.textContent = "Du hast " + euro.format(savings / 100) +
        " durch Rabatte gespart";
      els.summary.appendChild(saved);
    }
  }

  function sumCheck(result, workingItems) {
    var computed = workingItems.reduce(function (sum, item) {
      return sum + (item.price_cents || 0) + (item.deposit_cents || 0);
    }, 0);
    var declared = Number(result && result.total_cents);
    if (!declared || !isFinite(declared)) {
      return { computed: computed, declared: null, warning: null };
    }
    var diff = Math.abs(computed - declared);
    if (diff <= 1) { return { computed: computed, declared: declared, warning: null }; }
    return {
      computed: computed,
      declared: declared,
      warning: "Summe weicht um " + euro.format(diff / 100) + " ab – bitte kurz prüfen"
    };
  }

  // --- save -------------------------------------------------------------
  function save() {
    if (!items.length) {
      showError("Keine Positionen erkannt – bitte manuell erfassen.");
      return;
    }
    var total = totalCents();
    var data = new FormData();
    data.append(
      "store",
      els.storeField.value.trim() || (scanned && scanned.store) || "Sonstiges"
    );
    data.append(
      "postal_code",
      scanned && scanned.postal_code ? scanned.postal_code : NS.state.postalCode
    );
    data.append("country_code", NS.state.country);
    data.append("currency", (scanned && scanned.currency) || "EUR");
    data.append("receipt_date", (scanned && scanned.date) || todayIso());
    data.append("total_cents", String(total));
    // A demo receipt must never reach the community pool.
    data.append(
      "share_anonymized",
      !isDemo && NS.state.shareOptin === true ? "true" : "false"
    );
    data.append("is_demo", isDemo ? "true" : "false");
    data.append(
      "is_business",
      els.businessWrap.hidden ? "false" : (els.business.checked ? "true" : "false")
    );
    data.append("items_json", JSON.stringify(items));

    var demoFlag = isDemo;
    checkDuplicate(
      String(data.get("store") || ""),
      String(data.get("receipt_date") || ""),
      Number(data.get("total_cents") || 0)
    ).then(function (duplicate) {
      if (duplicate && !global.confirm(
        "Ein Bon mit gleichem Händler, Datum und Betrag existiert bereits. " +
        "Trotzdem speichern?"
      )) { return; }
      submitReceipt(data, demoFlag);
    }).catch(function () {
      // A failed duplicate check must never block saving.
      submitReceipt(data, demoFlag);
    });
  }

  function checkDuplicate(store, date, total) {
    if (isDemo) { return Promise.resolve(false); }
    return NS.api.get("/api/v1/receipts").then(function (receipts) {
      return (receipts || []).some(function (receipt) {
        return receipt.store === store &&
          receipt.receipt_date === date &&
          Number(receipt.total_cents) === total;
      });
    });
  }

  function submitReceipt(data, demoFlag) {
    els.save.disabled = true;
    NS.haptic();
    NS.api.postForm("/api/v1/receipts", data).then(function (result) {
      if (demoFlag && result && result.receipt_id) {
        NS.demo.markSaved(result.receipt_id);
      }
      NS.emit("receipts-changed");
      var receiptPlz = String((scanned && scanned.postal_code) || "").trim();
      if (
        /^[0-9]{4,5}$/.test(receiptPlz) &&
        NS.storage.get("fairbon.plz_manual", false) !== true
      ) {
        NS.setPostalCode(receiptPlz);
        NS.emit("plz-changed", receiptPlz);
      }
      if (!isDemo) {
        var relevant = items.filter(function (entry) {
          return [
            "Lebensmittel", "Getränke", "Drogerie", "Haushalt"
          ].indexOf(entry.category || "Sonstiges") >= 0;
        });
        var open = relevant.filter(function (entry) { return !entry.ean; });
        if (open.length) {
          NS.emit("quick-scan-banner", {
            open: open.length,
            total: items.length,
            items: open
          });
        }
      }
      if (queueIndex + 1 < queue.length) {
        queueSaved += 1;
        els.save.disabled = false;
        showQueued(queueIndex + 1);
        return;
      }
      close();
      NS.emit("tab", { tab: "receipts" });
    }).catch(function (error) {
      els.save.disabled = false;
      showError(error.message || "Speichern fehlgeschlagen.");
    });
  }

  NS.components = NS.components || {};
  NS.components.addSheet = { init: init, open: open, startDemo: startDemo };
})(window);
