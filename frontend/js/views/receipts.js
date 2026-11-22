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

  function $(id) { return document.getElementById(id); }

  function init() {
    els.list = $("receipt-list");
    els.empty = $("receipts-empty");
    els.search = $("receipts-search");
    els.filters = $("receipt-filters");
    els.modal = $("receipt-modal");
    els.backdrop = $("receipt-backdrop");
    els.items = $("receipt-items");
    if (!els.list) { return; }

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
    $("export-xlsx").addEventListener("click", function (event) {
      event.preventDefault();
      download("xlsx");
    });
    $("export-csv").addEventListener("click", function (event) {
      event.preventDefault();
      download("csv");
    });

    NS.on("receipts-changed", load);
    NS.on("open-receipts", function (payload) {
      if (payload && payload.category) {
        search = payload.category.toLowerCase();
        els.search.value = payload.category;
        filter = "all";
        renderList();
      }
    });
    load();
  }

  function load() {
    NS.api.get("/api/v1/receipts")
      .then(function (data) {
        receipts = data || [];
        renderList();
      })
      .catch(function () {
        receipts = [];
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
      return name.indexOf(search) >= 0;
    });
  }

  function renderList() {
    els.list.textContent = "";
    var visible = receipts.filter(matches);
    els.empty.hidden = visible.length > 0;
    visible.forEach(function (receipt) {
      var row = document.createElement("button");
      row.type = "button";
      row.className = "receipt-row";

      var body = document.createElement("div");
      body.className = "receipt-main";
      var title = document.createElement("strong");
      title.textContent = NS.storeInfo(receipt.store).label;
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
          NS.api.del("/api/v1/receipts/" + receipt.id).then(function () {
            NS.demo.unmarkSaved(receipt.id);
            load();
            NS.emit("receipts-changed");
          });
        });
        row.appendChild(demoDelete);
      }

      row.addEventListener("click", function () { openDetail(receipt); });
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
  }

  function closeDetail() {
    els.modal.hidden = true;
    els.backdrop.hidden = true;
    activeReceipt = null;
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
    NS.api.del("/api/v1/receipts/" + activeReceipt.id).then(function () {
      closeDetail();
      load();
      NS.emit("receipts-changed");
    }).catch(function (error) {
      $("receipt-error").hidden = false;
      $("receipt-error").textContent = error.message;
    });
  }

  function download(format) {
    var path = "/api/v1/receipts/export?format=" + format;
    fetch(NS.api.url(path), { headers: NS.api.headers() })
      .then(function (response) {
        if (!response.ok) { throw new Error("Export fehlgeschlagen."); }
        return response.blob();
      })
      .then(function (blob) {
        var url = URL.createObjectURL(blob);
        var link = document.createElement("a");
        link.href = url;
        link.download = "fairbon-bons." + format;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
      })
      .catch(function (error) {
        $("receipt-error").hidden = false;
        $("receipt-error").textContent = error.message;
      });
  }

  NS.views = NS.views || {};
  NS.views.receipts = { init: init, reload: load };
})(window);
