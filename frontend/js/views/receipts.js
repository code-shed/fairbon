/* FairBon — Tab 2: receipt list, detail sheet, privacy toggle and export (ES5). */
(function (global) {
  "use strict";

  var NS = global.FairBon = global.FairBon || {};
  var euro = NS.euro;
  var els = {};
  var receipts = [];
  var filter = "all";
  var search = "";
  var activeReceipt = null;
  var loaded = false;
  var loadError = "";

  function $(id) { return document.getElementById(id); }

  function init() {
    els.list = $("receipt-list");
    els.empty = $("receipts-empty");
    els.search = $("receipts-search");
    els.filters = $("receipt-filters");
    els.modal = $("receipt-modal");
    els.backdrop = $("receipt-backdrop");
    els.items = $("receipt-items");
    els.status = $("receipts-status");
    els.statusText = $("receipts-status-text");
    els.retry = $("receipts-retry");
    els.exportError = $("export-error");
    els.banner = $("barcode-banner");
    if (!els.list) { return; }

    NS.on("quick-scan-banner", function (payload) {
      if (!els.banner || !payload || !payload.open) { return; }
      els.banner.textContent = "";
      var text = document.createElement("span");
      text.textContent = payload.open + " von " + payload.total +
        " Artikeln automatisch erkannt – magst du beim Auspacken kurz " +
        "1–2 der übrigen scannen?";
      var start = document.createElement("button");
      start.type = "button";
      start.className = "mini-btn";
      start.textContent = "Schnell-Scan starten";
      start.addEventListener("click", function () {
        startQuickScan(payload.items || []);
        els.banner.hidden = true;
      });
      var close = document.createElement("button");
      close.type = "button";
      close.className = "mini-btn";
      close.setAttribute("aria-label", "Hinweis schließen");
      close.textContent = "×";
      close.addEventListener("click", function () { els.banner.hidden = true; });
      els.banner.appendChild(text);
      els.banner.appendChild(start);
      els.banner.appendChild(close);
      els.banner.hidden = false;
    });

    els.search.addEventListener("input", function () {
      search = (els.search.value || "").trim().toLowerCase();
      renderList();
    });
    Array.prototype.forEach.call(
      els.filters.querySelectorAll(".chip"),
      function (chip) {
        chip.addEventListener("click", function () {
          filter = chip.getAttribute("data-filter");
          Array.prototype.forEach.call(
            els.filters.querySelectorAll(".chip"),
            function (other) { other.setAttribute("aria-pressed", String(other === chip)); }
          );
          renderList();
        });
      }
    );
    $("receipt-close").addEventListener("click", closeDetail);
    els.backdrop.addEventListener("click", closeDetail);
    $("receipt-delete").addEventListener("click", deleteActive);
    els.retry.addEventListener("click", load);
    $("export-xlsx").addEventListener("click", function () { download("xlsx"); });
    $("export-csv").addEventListener("click", function () { download("csv"); });

    NS.on("receipts-changed", load);
    NS.on("open-receipts", function (payload) {
      if (payload && payload.category) {
        search = payload.category.toLowerCase();
        els.search.value = payload.category;
        filter = "all";
        Array.prototype.forEach.call(
          els.filters.querySelectorAll(".chip"),
          function (chip) {
            chip.setAttribute(
              "aria-pressed",
              String(chip.getAttribute("data-filter") === "all")
            );
          }
        );
        renderList();
        NS.emit("tab", { tab: "receipts" });
      }
    });
    load();
  }

  function load() {
    loadError = "";
    renderList();
    NS.api.get("/api/v1/receipts")
      .then(function (data) {
        receipts = data || [];
        loaded = true;
        renderList();
      })
      .catch(function (error) {
        loadError = error && error.message ? error.message : "Unbekannter Fehler.";
        renderList();
      });
  }

  function matches(receipt) {
    if (filter === "shared" && !receipt.shared_to_community) { return false; }
    if (filter === "business") {
      var hasBusiness = (receipt.items || []).some(function (item) {
        return !item.is_private;
      });
      if (!hasBusiness) { return false; }
    }
    if (!search) { return true; }
    if (String(receipt.store || "").toLowerCase().indexOf(search) >= 0) { return true; }
    return (receipt.items || []).some(function (item) {
      var name = String(item.normalized_name || item.raw_text || "").toLowerCase();
      var price = ((item.price_cents || 0) / 100).toFixed(2);
      return name.indexOf(search) >= 0 ||
        String(item.quantity || "").indexOf(search) >= 0 ||
        price.indexOf(search) >= 0 ||
        price.replace(".", ",").indexOf(search) >= 0;
    });
  }

  function renderList() {
    els.list.textContent = "";
    var visible = receipts.filter(matches);
    var waiting = !loaded && !loadError;
    els.status.hidden = !(waiting || loadError);
    els.statusText.textContent = loadError
      ? "Bons konnten nicht geladen werden. " + loadError
      : "Bons werden geladen …";
    els.retry.hidden = !loadError;
    els.empty.hidden = waiting || !!loadError || visible.length > 0;
    els.empty.textContent = receipts.length
      ? "Keine Bons für diese Suche oder diesen Filter."
      : "Noch keine Bons. Tippe auf „+ Bon erfassen“.";
    visible.forEach(function (receipt) {
      var row = document.createElement("div");
      row.setAttribute("role", "button");
      row.setAttribute("tabindex", "0");
      row.className = "receipt-row";

      var body = document.createElement("div");
      body.className = "receipt-main";
      var title = document.createElement("strong");
      title.textContent = NS.storeInfo(receipt.store).label;
      if (NS.state.coloredBadges !== false) {
        var info = NS.storeInfo(receipt.store);
        var badge = document.createElement("span");
        badge.className = "store-badge";
        badge.style.background = info.bg;
        badge.style.color = info.fg;
        badge.textContent = String(info.label || "?").trim().slice(0, 2).toUpperCase();
        title.insertBefore(badge, title.firstChild);
        title.insertBefore(document.createTextNode(" "), badge.nextSibling);
      }
      var meta = document.createElement("span");
      meta.textContent = [
        receipt.postal_code || "",
        NS.formatDate(receipt.receipt_date),
        (receipt.item_count || 0) + " Positionen"
      ].filter(Boolean).join(" · ");
      body.appendChild(title);
      body.appendChild(meta);
      row.appendChild(body);

      var total = document.createElement("span");
      total.className = "receipt-total";
      total.textContent = euro.format((receipt.total_cents || 0) / 100);
      row.appendChild(total);

      if (receipt.is_business) {
        var businessBadge = document.createElement("span");
        businessBadge.className = "pill-badge business";
        businessBadge.textContent = "Geschäftlich";
        row.appendChild(businessBadge);
      }

      if (receipt.shared_to_community) {
        var shared = document.createElement("span");
        shared.className = "validity standard";
        shared.textContent = "geteilt";
        row.appendChild(shared);
      }

      if (NS.demo.isSaved(receipt.id)) {
        var demoBadge = document.createElement("span");
        demoBadge.className = "pill-badge demo";
        demoBadge.textContent = "Beispiel-Bon";
        row.appendChild(demoBadge);
        var demoDelete = document.createElement("button");
        demoDelete.type = "button";
        demoDelete.className = "mini-btn demo-delete";
        demoDelete.textContent = "Demo löschen";
        demoDelete.addEventListener("click", function (event) {
          event.stopPropagation();
          if (!global.confirm("Beispiel-Bon wirklich löschen?")) { return; }
          demoDelete.disabled = true;
          NS.api.del("/api/v1/receipts/" + receipt.id).then(function () {
            NS.demo.unmarkSaved(receipt.id);
            load();
            NS.emit("receipts-changed");
          }).catch(function () { demoDelete.disabled = false; });
        });
        row.appendChild(demoDelete);
      }

      row.addEventListener("click", function () { openDetail(receipt); });
      row.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openDetail(receipt);
        }
      });
      els.list.appendChild(row);
    });
  }

  function openDetail(receipt) {
    activeReceipt = receipt;
    $("receipt-title").textContent = NS.storeInfo(receipt.store).label;
    $("receipt-sub").textContent = [
      NS.formatDate(receipt.receipt_date),
      receipt.postal_code || "",
      receipt.currency || "EUR"
    ].filter(Boolean).join(" · ");
    renderItems(receipt);
    els.modal.hidden = false;
    els.backdrop.hidden = false;
    var close = $("receipt-close");
    if (close) { close.focus(); }
  }

  function closeDetail() {
    els.modal.hidden = true;
    els.backdrop.hidden = true;
    activeReceipt = null;
  }

  var SCAN_CATEGORIES = {
    "Lebensmittel": true, "Getränke": true, "Drogerie": true, "Haushalt": true
  };

  function canScanItem(item) {
    if (item.ean || item.is_ambiguous || !SCAN_CATEGORIES[item.category]) {
      return false;
    }
    // Loose goods weighed in kg need no package barcode.
    var unit = String(item.unit || "").toLowerCase();
    return !(unit === "kg" && Number(item.quantity) < 1);
  }

  function openItems(receipt) {
    return (receipt.items || []).filter(canScanItem);
  }

  function fuzzyMatch(name, items) {
    var words = String(name || "").toLowerCase().split(/\W+/).filter(function (w) {
      return w.length >= 3;
    });
    var best = null;
    var bestScore = 0;
    items.forEach(function (item) {
      var text = String(item.normalized_name || item.raw_text || "").toLowerCase();
      var brand = String(item.brand || "").toLowerCase();
      var score = words.reduce(function (sum, word) {
        return sum + (text.indexOf(word) >= 0 ? 2 : 0) +
          (brand.indexOf(word) >= 0 ? 1 : 0);
      }, 0);
      if (score > bestScore) { bestScore = score; best = item; }
    });
    return bestScore > 0 ? best : null;
  }

  function confirmScan(product, item, onConfirm) {
    var backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    var box = document.createElement("div");
    box.className = "modal modal--sheet";
    box.setAttribute("role", "dialog");
    var title = document.createElement("h2");
    title.textContent = "Barcode zuordnen";
    var info = document.createElement("p");
    info.className = "detail-note";
    info.textContent = product.name +
      (product.brand ? " · " + product.brand : "") +
      " → " + (item.normalized_name || item.raw_text);
    var actions = document.createElement("div");
    actions.className = "modal-actions";
    var cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "secondary";
    cancel.textContent = "Abbrechen";
    var ok = document.createElement("button");
    ok.type = "button";
    ok.className = "primary";
    ok.textContent = "Bestätigen";
    function close() {
      if (backdrop.parentNode) { document.body.removeChild(backdrop); }
      if (box.parentNode) { document.body.removeChild(box); }
    }
    cancel.addEventListener("click", close);
    ok.addEventListener("click", function () { close(); onConfirm(); });
    actions.appendChild(cancel);
    actions.appendChild(ok);
    box.appendChild(title);
    box.appendChild(info);
    box.appendChild(actions);
    document.body.appendChild(backdrop);
    document.body.appendChild(box);
  }

  function startQuickScan(items) {
    var queue = items.slice();
    function step() {
      if (!queue.length) { return; }
      NS.platform.scanBarcode().then(function (ean) {
        if (!ean) { return; }
        NS.haptic();
        NS.api.postJson(
          "/api/v1/receipts/items/" + queue[0].id + "/link-barcode?preview=true",
          { ean: ean }
        ).then(function (product) {
          var match = fuzzyMatch(product.name, queue) || queue[0];
          confirmScan(product, match, function () { linkEan(ean, match, queue); });
        }).catch(function () { linkEan(ean, queue[0], queue); });
      });
    }
    step();
  }

  function linkEan(ean, item, queue) {
    NS.api.postJson(
      "/api/v1/receipts/items/" + item.id + "/link-barcode", { ean: ean }
    ).then(function () {
      var index = queue.indexOf(item);
      if (index >= 0) { queue.splice(index, 1); }
      load();
      startQuickScan(queue);
    }).catch(function (error) {
      $("receipt-error").hidden = false;
      $("receipt-error").textContent = error.message || "Barcode konnte nicht gespeichert werden.";
    });
  }

  function renderItems(receipt) {
    els.items.textContent = "";
    (receipt.items || []).forEach(function (item) {
      var li = document.createElement("li");
      li.className = "receipt-item";

      var name = document.createElement("span");
      name.className = "item-name";
      name.textContent = item.normalized_name || item.raw_text || "Artikel";
      var price = document.createElement("span");
      price.className = "item-price";
      price.textContent = euro.format((item.price_cents || 0) / 100);
      var meta = document.createElement("span");
      meta.className = "item-meta";
      meta.textContent = [
        item.brand || "",
        item.category || "",
        item.vat_rate != null ? item.vat_rate + " % MwSt." : ""
      ].filter(Boolean).join(" · ");
      li.appendChild(name);
      li.appendChild(price);
      li.appendChild(meta);

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
      if (badges.childNodes.length) { li.appendChild(badges); }

      var actions = document.createElement("div");
      actions.className = "item-actions";

      var toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "mini-btn";
      toggle.textContent = item.is_private ? "Öffentlich" : "Privat";
      toggle.addEventListener("click", function () {
        setPrivate(item, !item.is_private);
      });
      actions.appendChild(toggle);

      var add = document.createElement("button");
      add.type = "button";
      add.className = "mini-btn";
      add.textContent = "+ Liste";
      add.addEventListener("click", function () {
        NS.addToBasket({
          name: item.normalized_name || item.raw_text,
          brand: item.brand,
          store: receipt.store,
          price: (item.price_cents || 0) / 100,
          unit_price: item.unit_price_cents ? item.unit_price_cents / 100 : null,
          quantity: item.quantity,
          unit: item.unit
        });
        add.textContent = "✓ Gemerkt";
      });
      actions.appendChild(add);

      if (canScanItem(item)) {
        var scan = document.createElement("button");
        scan.type = "button";
        scan.className = "mini-btn";
        scan.textContent = "Barcode scannen";
        scan.addEventListener("click", function () { startQuickScan([item]); });
        actions.appendChild(scan);
      }

      li.appendChild(actions);
      els.items.appendChild(li);
    });

    var savings = (receipt.items || []).reduce(function (sum, item) {
      return sum + (item.discount_cents || 0);
    }, 0);
    if (savings > 0) {
      var line = document.createElement("li");
      line.className = "receipt-savings";
      line.textContent = "Du hast " + euro.format(savings / 100) +
        " durch Rabatte gespart";
      els.items.appendChild(line);
    }

    var fix = document.createElement("button");
    fix.type = "button";
    fix.className = "btn-link fix-link";
    fix.textContent = "Stimmt hier etwas nicht?";
    fix.addEventListener("click", function () { toggleEdit(receipt); });
    els.items.appendChild(fix);
  }

  var EDIT_CATEGORIES = [
    "Lebensmittel", "Getränke", "Drogerie", "Haushalt",
    "Bäcker/Gastronomie", "Technik/Non-Food", "Pfand", "Sonstiges"
  ];

  function toggleEdit(receipt) {
    var existing = els.items.querySelectorAll(".item-editor");
    if (existing.length) {
      Array.prototype.forEach.call(existing, function (row) {
        if (row.parentNode) { row.parentNode.removeChild(row); }
      });
      return;
    }
    receipt.items.forEach(function (item) {
      var box = document.createElement("li");
      box.className = "item-editor";
      var name = document.createElement("input");
      name.type = "text";
      name.value = item.normalized_name || item.raw_text || "";
      name.setAttribute("aria-label", "Name");
      var quantity = document.createElement("input");
      quantity.type = "number";
      quantity.min = "0.01";
      quantity.step = "0.01";
      quantity.value = String(item.quantity || 1);
      quantity.setAttribute("aria-label", "Menge");
      var price = document.createElement("input");
      price.type = "number";
      price.min = "0";
      price.step = "0.01";
      price.value = ((item.price_cents || 0) / 100).toFixed(2);
      price.setAttribute("aria-label", "Preis in Euro");
      var category = document.createElement("select");
      category.setAttribute("aria-label", "Kategorie");
      EDIT_CATEGORIES.forEach(function (value) {
        var option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        if (value === item.category) { option.selected = true; }
        category.appendChild(option);
      });
      var save = document.createElement("button");
      save.type = "button";
      save.className = "mini-btn";
      save.textContent = "Speichern";
      save.addEventListener("click", function () {
        save.disabled = true;
        NS.api.patchJson("/api/v1/receipts/items/" + item.id, {
          name: name.value,
          quantity: Number(quantity.value) || 1,
          price_cents: Math.round((Number(price.value) || 0) * 100),
          category: category.value
        }).then(function () {
          load();
          closeDetail();
        }).catch(function (error) {
          save.disabled = false;
          $("receipt-error").hidden = false;
          $("receipt-error").textContent = error.message || "Änderung fehlgeschlagen.";
        });
      });
      box.appendChild(name);
      box.appendChild(quantity);
      box.appendChild(price);
      box.appendChild(category);
      box.appendChild(save);
      els.items.appendChild(box);
    });
  }

  function setPrivate(item, value) {
    var data = new FormData();
    data.append("is_private", value ? "true" : "false");
    NS.api.patchForm(
      "/api/v1/receipts/" + activeReceipt.id + "/items/" + item.id,
      data
    ).then(function () {
      item.is_private = value;
      renderItems(activeReceipt);
    }).catch(function (error) {
      $("receipt-error").hidden = false;
      $("receipt-error").textContent = error.message;
    });
  }

  function deleteActive() {
    if (!activeReceipt) { return; }
    if (!global.confirm("Diesen Bon wirklich löschen?")) { return; }
    var receiptId = activeReceipt.id;
    var button = $("receipt-delete");
    button.disabled = true;
    NS.api.del("/api/v1/receipts/" + receiptId).then(function () {
      NS.demo.unmarkSaved(receiptId);
      closeDetail();
      load();
      NS.emit("receipts-changed");
    }).catch(function (error) {
      button.disabled = false;
      $("receipt-error").hidden = false;
      $("receipt-error").textContent = error.message;
    });
  }

  function download(format) {
    var button = $("export-" + format);
    els.exportError.hidden = true;
    els.exportError.textContent = "";
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    NS.api.blob("/api/v1/receipts/export?format=" + format)
      .then(function (blob) {
        saveBlob(blob, "fairbon-bons-" + dateStamp() + "." + format);
      })
      .catch(function (error) {
        els.exportError.hidden = false;
        els.exportError.textContent = error.message || "Export fehlgeschlagen.";
      })
      .then(function () {
        button.disabled = false;
        button.removeAttribute("aria-busy");
      });
  }

  function saveBlob(blob, filename) {
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    global.setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function dateStamp() {
    var now = new Date();
    var month = ("0" + (now.getMonth() + 1)).slice(-2);
    var day = ("0" + now.getDate()).slice(-2);
    return now.getFullYear() + "-" + month + "-" + day;
  }

  NS.views = NS.views || {};
  NS.views.receipts = { init: init, reload: load };
})(window);
