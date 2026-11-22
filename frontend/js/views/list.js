/* FairBon — Tab 4: shopping list, basket and smart-basket optimiser (ES5). */
(function (global) {
  "use strict";

  var NS = global.FairBon = global.FairBon || {};
  var euro = NS.euro;
  var els = {};

  function $(id) { return document.getElementById(id); }

  function init() {
    els.input = $("shopping-list");
    els.chips = $("list-chips");
    els.apply = $("apply-list");
    els.searchAll = $("search-all");
    els.basketItems = $("basket-items");
    els.basketCount = $("basket-count");
    els.basketClear = $("basket-clear");
    els.basketOptimize = $("basket-optimize");
    els.badge = $("list-badge");
    els.optimize = $("optimize");
    els.mic = $("mic");
    if (!els.basketItems) { return; }

    els.basketClear.addEventListener("click", function () {
      NS.clearBasket();
    });
    els.basketOptimize.addEventListener("click", optimize);
    els.apply.addEventListener("click", applyList);
    els.searchAll.addEventListener("click", searchAll);
    if (els.mic) { els.mic.addEventListener("click", startSpeech); }
    var wa = $("share-whatsapp");
    var copy = $("share-copy");
    if (wa) { wa.addEventListener("click", shareWhatsApp); }
    if (copy) { copy.addEventListener("click", copyShare); }

    NS.on("basket-changed", renderBasket);
    renderBasket();
  }

  // --- free-text list parser (mirrors the server's rules roughly) ------
  function splitTerms(text) {
    var cleaned = String(text || "")
      .replace(/\b(ich brauche|ich möchte|ich moechte|und|sowie|bitte)\b/gi, " ");
    return cleaned
      .split(/[,;\n]+|\s{2,}/)
      .map(function (part) { return part.trim(); })
      .filter(function (part) { return part.length >= 2; })
      .slice(0, 20);
  }

  function renderChips(terms) {
    els.chips.textContent = "";
    terms.forEach(function (term) {
      var chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = term;
      els.chips.appendChild(chip);
    });
  }

  function applyList() {
    var terms = splitTerms(els.input.value);
    renderChips(terms);
    NS.emit("shopping-terms", terms);
  }

  function searchAll() {
    var terms = splitTerms(els.input.value);
    if (!terms.length) { return; }
    NS.emit("shopping-search", terms);
  }

  // --- basket -----------------------------------------------------------
  function renderBasket() {
    if (!els.basketItems) { return; }
    els.basketItems.textContent = "";
    var count = NS.basket.length;
    els.basketCount.textContent = String(count);
    if (els.badge) {
      els.badge.textContent = String(count);
      els.badge.hidden = count === 0;
    }
    if (!count) {
      var empty = document.createElement("p");
      empty.className = "basket-empty";
      empty.textContent = "Die Merkliste ist leer. Mit „+ Merken“ Angebote hinzufügen.";
      els.basketItems.appendChild(empty);
      return;
    }
    NS.basket.forEach(function (entry, index) {
      var row = document.createElement("div");
      row.className = "basket-item";
      var body = document.createElement("div");
      body.className = "basket-item-body";
      var title = document.createElement("strong");
      title.textContent = entry.name;
      var meta = document.createElement("span");
      meta.textContent = [
        entry.brand || "",
        entry.store ? NS.storeInfo(entry.store).label : "",
        typeof entry.price === "number" ? euro.format(entry.price) : ""
      ].filter(Boolean).join(" · ");
      body.appendChild(title);
      body.appendChild(meta);
      row.appendChild(body);
      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "mini-btn";
      remove.textContent = "Entfernen";
      remove.addEventListener("click", function () {
        NS.basket.splice(index, 1);
        NS.saveBasket();
      });
      row.appendChild(remove);
      els.basketItems.appendChild(row);
    });
  }

  // --- optimiser --------------------------------------------------------
  function optimize() {
    if (!NS.basket.length) {
      showOptimizeMessage("Merkliste ist leer – erst Angebote merken.");
      return;
    }
    var items = NS.basket.map(function (entry) { return entry.name; });
    showOptimizeMessage("Berechne günstigste Aufteilung …");
    NS.api.postJson("/api/v1/basket/optimize", {
      items: items,
      postal_code: NS.state.postalCode
    }).then(renderPlan).catch(function (error) {
      showOptimizeMessage(error.message || "Optimierung fehlgeschlagen.");
    });
  }

  function showOptimizeMessage(text) {
    if (!els.optimize) { return; }
    els.optimize.hidden = false;
    els.optimize.textContent = "";
    var p = document.createElement("p");
    p.textContent = text;
    els.optimize.appendChild(p);
  }

  function renderPlan(plan) {
    if (!els.optimize) { return; }
    els.optimize.hidden = false;
    els.optimize.textContent = "";
    [plan.option_a, plan.option_b].forEach(function (option) {
      var card = document.createElement("article");
      card.className = "option-panel card";
      var head = document.createElement("div");
      head.className = "option-head";
      var label = document.createElement("strong");
      label.textContent = option.label;
      var total = document.createElement("span");
      total.textContent = euro.format(option.total);
      head.appendChild(label);
      head.appendChild(total);
      card.appendChild(head);
      option.stores.forEach(function (group) {
        var block = document.createElement("div");
        block.className = "store-block";
        var storeHead = document.createElement("div");
        storeHead.className = "store-block-head";
        storeHead.appendChild(NS.storeBadge(NS.storeInfo(group.store)));
        var subtotal = document.createElement("strong");
        subtotal.textContent = euro.format(group.subtotal);
        storeHead.appendChild(subtotal);
        block.appendChild(storeHead);
        var list = document.createElement("ul");
        list.className = "line-list";
        group.lines.forEach(function (line) {
          var row = document.createElement("li");
          var name = document.createElement("span");
          name.className = "line-name";
          name.textContent = line.item + " – " +
            (line.product.display_title || line.product.name);
          var price = document.createElement("span");
          price.className = "line-price";
          price.textContent = euro.format(line.product.price);
          row.appendChild(name);
          row.appendChild(price);
          list.appendChild(row);
        });
        block.appendChild(list);
        card.appendChild(block);
      });
      if (option.missing_items && option.missing_items.length) {
        var missing = document.createElement("p");
        missing.className = "empty-hint";
        missing.textContent = "Nicht verfügbar: " + option.missing_items.join(", ");
        card.appendChild(missing);
      }
      els.optimize.appendChild(card);
    });

    NS.lastShareText = plan.share_text || "";
    NS.lastShareUrl = plan.whatsapp_url || "";
    var wa = $("share-whatsapp");
    var copy = $("share-copy");
    if (wa) { wa.setAttribute("data-share", NS.lastShareText); }
    if (copy) { copy.setAttribute("data-share", NS.lastShareText); }
  }

  function shareWhatsApp() {
    var url = NS.lastShareUrl;
    if (url) { global.open(url, "_blank", "noopener"); }
  }

  function copyShare() {
    var text = NS.lastShareText || "";
    var button = $("share-copy");
    if (!text || !button) { return; }
    if (!button.getAttribute("data-label")) {
      button.setAttribute("data-label", button.textContent);
    }
    var clipboard = global.navigator.clipboard;
    if (clipboard && clipboard.writeText) {
      clipboard.writeText(text).then(function () {
        flashCopy(button, "✓ Kopiert");
      }, function () {
        flashCopy(button, copyWithSelection(text) ? "✓ Kopiert" : "Kopieren fehlgeschlagen");
      });
      return;
    }
    flashCopy(button, copyWithSelection(text) ? "✓ Kopiert" : "Kopieren fehlgeschlagen");
  }

  function copyWithSelection(text) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    var copied = false;
    try { copied = document.execCommand("copy"); } catch (error) { copied = false; }
    area.remove();
    return copied;
  }

  function flashCopy(button, label) {
    button.textContent = label;
    global.setTimeout(function () {
      button.textContent = button.getAttribute("data-label");
    }, 2000);
  }

  // --- speech -----------------------------------------------------------
  function startSpeech() {
    var Recognition = global.SpeechRecognition || global.webkitSpeechRecognition;
    if (!Recognition) { return; }
    var recognition = new Recognition();
    recognition.lang = "de-DE";
    recognition.interimResults = false;
    recognition.onresult = function (event) {
      var text = event.results[0][0].transcript || "";
      els.input.value = els.input.value ? els.input.value + ", " + text : text;
      applyList();
    };
    recognition.start();
  }

  NS.views = NS.views || {};
  NS.views.list = { init: init, renderBasket: renderBasket };
})(window);
