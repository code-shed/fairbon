/* FairBon — Tab 3: price search, results and price-history modal (ES5). */
(function (global) {
  "use strict";

  var NS = global.FairBon = global.FairBon || {};
  var euro = NS.euro;

  var state = {
    query: "",
    items: [],
    excluded: [],
    sort: "unit",
    detailOffer: null,
    detailDays: 365,
    detailIdentity: "strict",
    requestSeq: 0
  };

  var els = {};

  function $(id) { return document.getElementById(id); }

  function init() {
    els.form = $("search-form");
    els.query = $("query");
    els.postal = $("postal-code");
    els.precise = $("precise");
    els.todayOnly = $("today-only");
    els.standard = $("standard");
    els.limit = $("limit");
    els.storeGrid = $("store-grid");
    els.chips = $("chips");
    els.summary = $("summary");
    els.state = $("state");
    els.results = $("results");
    els.coverage = $("coverage");
    if (!els.form) { return; }

    els.postal.value = NS.state.postalCode;
    renderStores();
    bindEvents();
    fetchCoverage();
    bindDetailModal();
  }

  function renderStores() {
    els.storeGrid.textContent = "";
    NS.STORES.forEach(function (store) {
      var label = document.createElement("label");
      label.className = "store-chip";
      var input = document.createElement("input");
      input.type = "checkbox";
      input.value = store.id;
      input.checked = true;
      var span = document.createElement("span");
      span.textContent = store.label;
      label.appendChild(input);
      label.appendChild(span);
      els.storeGrid.appendChild(label);
    });
  }

  function selectedStores() {
    if (!els.storeGrid) { return []; }
    return Array.prototype.slice
      .call(els.storeGrid.querySelectorAll("input:checked"))
      .map(function (input) { return input.value; });
  }

  function bindEvents() {
    els.form.addEventListener("submit", function (event) {
      event.preventDefault();
      runSearch();
    });
    els.postal.addEventListener("change", function () {
      NS.setPostalCode(els.postal.value);
      fetchCoverage();
    });
    Array.prototype.forEach.call(
      document.querySelectorAll(".sortgroup button"),
      function (button) {
        button.addEventListener("click", function () {
          state.sort = button.getAttribute("data-sort") || "unit";
          Array.prototype.forEach.call(
            document.querySelectorAll(".sortgroup button"),
            function (other) {
              other.setAttribute("aria-pressed", String(other === button));
            }
          );
          renderResults();
        });
      }
    );
    var mic = $("mic-search");
    if (mic) { mic.addEventListener("click", startSpeech); }
  }

  function fetchCoverage() {
    var plz = NS.state.postalCode;
    if (!plz || !els.coverage) { return; }
    NS.api.get("/api/v1/crowd/coverage?postal_code=" + encodeURIComponent(plz))
      .then(function (data) {
        els.coverage.textContent = "PLZ " + plz + ": " + data.observations +
          (data.observations === 1 ? " Standardpreis" : " Standardpreise") +
          " erfasst · " + data.products + " Produkte · " + data.stores + " Märkte";
      })
      .catch(function () {
        if (els.coverage) { els.coverage.textContent = ""; }
      });
  }

  function runSearch() {
    var query = (els.query.value || "").trim();
    if (!query) { return; }
    state.query = query;
    NS.setPostalCode(els.postal.value);
    els.state.textContent = "Angebote werden geladen …";
    els.results.textContent = "";
    var seq = ++state.requestSeq;
    var params = [
      "query=" + encodeURIComponent(query),
      "postal_code=" + encodeURIComponent(NS.state.postalCode),
      "stores=" + encodeURIComponent(selectedStores().join(",")),
      "limit=" + encodeURIComponent(els.limit.value),
      "precise=" + (els.precise.checked ? "true" : "false"),
      "today_only=" + (els.todayOnly.checked ? "true" : "false"),
      "include_standard=" + (els.standard.checked ? "true" : "false"),
      "offers_only=false"
    ];
    if (state.excluded.length) {
      params.push("exclude=" + encodeURIComponent(state.excluded.join(",")));
    }
    NS.api.get("/api/v1/products/search/ranked?" + params.join("&"))
      .then(function (data) {
        if (seq !== state.requestSeq) { return; }
        state.items = (data.items || []).map(function (item) {
          return {
            product: item.product,
            relevance: item.relevance || {},
            validity: item.validity || {}
          };
        });
        if (els.state) { els.state.textContent = ""; }
        renderQuickFilters(data.quick_filters || []);
        renderResults();
      })
      .catch(function (error) {
        if (seq !== state.requestSeq) { return; }
        els.state.textContent = error.message || "Suche fehlgeschlagen.";
      });
  }

  function renderQuickFilters(filters) {
    els.chips.textContent = "";
    (filters || []).forEach(function (filter) {
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = "− " + filter.term + " (" + filter.count + ")";
      chip.addEventListener("click", function () {
        state.excluded.push(filter.term);
        runSearch();
      });
      els.chips.appendChild(chip);
    });
    if (state.excluded.length) {
      var reset = document.createElement("button");
      reset.type = "button";
      reset.className = "chip";
      reset.textContent = "Alle zurücksetzen";
      reset.addEventListener("click", function () {
        state.excluded = [];
        runSearch();
      });
      els.chips.appendChild(reset);
    }
  }

  function sortValue(entry) {
    var p = entry.product;
    if (state.sort === "price") { return typeof p.price === "number" ? p.price : Infinity; }
    if (state.sort === "discount") {
      return typeof p.discount_percent === "number" ? -p.discount_percent : Infinity;
    }
    return typeof p.unit_price === "number" ? p.unit_price : Infinity;
  }

  function renderResults() {
    els.results.textContent = "";
    if (!state.items.length) {
      els.state.textContent = "Keine Angebote gefunden – andere PLZ oder Suchbegriff probieren.";
      var cta = document.createElement("button");
      cta.type = "button";
      cta.className = "secondary";
      cta.textContent = "Bon scannen & Preise beitragen";
      cta.addEventListener("click", function () {
        if (NS.components.addSheet) { NS.components.addSheet.open(false); }
      });
      els.state.appendChild(cta);
      els.summary.textContent = "";
      return;
    }
    var sorted = state.items.slice().sort(function (a, b) {
      return (sortValue(a) - sortValue(b)) || (a.product.name < b.product.name ? -1 : 1);
    });
    els.summary.textContent = sorted.length + " Angebote für „" + state.query + "“";
    sorted.forEach(function (entry) {
      els.results.appendChild(renderCard(entry));
    });
  }

  function renderCard(entry) {
    var product = entry.product;
    var validity = entry.validity || {};
    var card = document.createElement("article");
    card.className = "offer card";

    var top = document.createElement("div");
    top.className = "row-top";
    top.appendChild(NS.storeBadge(NS.storeInfo(product.store)));
    var save = document.createElement("button");
    save.type = "button";
    save.className = "mini-btn";
    save.textContent = "+ Merken";
    save.addEventListener("click", function () {
      var added = NS.addToBasket(product);
      save.textContent = added ? "✓ Gemerkt" : "schon gemerkt";
      save.disabled = true;
    });
    top.appendChild(save);
    card.appendChild(top);

    var title = document.createElement("h2");
    title.className = "product";
    var titleButton = document.createElement("button");
    titleButton.type = "button";
    titleButton.className = "product-link";
    titleButton.textContent = product.display_title || product.name;
    titleButton.addEventListener("click", function () { openDetail(product); });
    title.appendChild(titleButton);
    card.appendChild(title);

    var priceRow = document.createElement("div");
    priceRow.className = "pricing";
    var price = document.createElement("strong");
    price.className = "price";
    price.textContent = typeof product.price === "number" ? euro.format(product.price) : "–";
    priceRow.appendChild(price);
    if (typeof product.unit_price === "number" && (product.unit === "kg" || product.unit === "l")) {
      var unit = document.createElement("span");
      unit.className = "unitprice";
      unit.textContent = euro.format(product.unit_price) + "/" + product.unit;
      priceRow.appendChild(unit);
    }
    if (typeof product.discount_percent === "number" && product.discount_percent > 0) {
      var discount = document.createElement("span");
      discount.className = "discount";
      discount.textContent = "−" + Math.round(product.discount_percent) + " %";
      priceRow.appendChild(discount);
    }
    card.appendChild(priceRow);

    var meta = document.createElement("p");
    meta.className = "meta";
    if (product.brand) { meta.appendChild(document.createTextNode(product.brand)); }
    if (validity.label) {
      if (meta.textContent) { meta.appendChild(document.createTextNode(" · ")); }
      var badge = document.createElement("span");
      badge.className = "validity " + (validity.state || "unknown");
      badge.textContent = validity.label;
      meta.appendChild(badge);
    }
    card.appendChild(meta);

    return card;
  }

  // --- detail modal -----------------------------------------------------
  function bindDetailModal() {
    var close = $("detail-close");
    var backdrop = $("detail-backdrop");
    if (close) { close.addEventListener("click", hideDetail); }
    if (backdrop) { backdrop.addEventListener("click", hideDetail); }
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { hideDetail(); }
    });
    Array.prototype.forEach.call(
      document.querySelectorAll("#detail-modal .range-tabs button"),
      function (tab) {
        tab.addEventListener("click", function () {
          state.detailDays = Number(tab.getAttribute("data-days"));
          Array.prototype.forEach.call(
            document.querySelectorAll("#detail-modal .range-tabs button"),
            function (other) { other.setAttribute("aria-selected", String(other === tab)); }
          );
          loadDetail();
        });
      }
    );
    Array.prototype.forEach.call(
      document.querySelectorAll("#detail-modal .detail-identity-tabs button"),
      function (tab) {
        tab.addEventListener("click", function () {
          state.detailIdentity = tab.getAttribute("data-identity") || "strict";
          Array.prototype.forEach.call(
            document.querySelectorAll("#detail-modal .detail-identity-tabs button"),
            function (other) { other.setAttribute("aria-selected", String(other === tab)); }
          );
          loadDetail();
        });
      }
    );
  }

  function openDetail(product) {
    state.detailOffer = product;
    state.detailDays = 365;
    state.detailIdentity = "strict";
    $("detail-title").textContent = product.display_title || product.name || "Preisverlauf";
    $("detail-sub").textContent = [product.brand, product.store ? NS.storeInfo(product.store).label : ""]
      .filter(Boolean).join(" · ");
    $("detail-modal").hidden = false;
    $("detail-backdrop").hidden = false;
    Array.prototype.forEach.call(
      document.querySelectorAll("#detail-modal .detail-identity-tabs button"),
      function (tab) {
        tab.setAttribute("aria-selected", String(tab.getAttribute("data-identity") === "strict"));
      }
    );
    Array.prototype.forEach.call(
      document.querySelectorAll("#detail-modal .range-tabs button"),
      function (tab) {
        tab.setAttribute("aria-selected", String(tab.getAttribute("data-days") === "365"));
      }
    );
    loadDetail();
  }

  function hideDetail() {
    var modal = $("detail-modal");
    var backdrop = $("detail-backdrop");
    if (modal && !modal.hidden) { modal.hidden = true; }
    if (backdrop) { backdrop.hidden = true; }
  }

  function loadDetail() {
    var product = state.detailOffer;
    if (!product) { return; }
    var params = [
      "name=" + encodeURIComponent(product.name),
      "days=" + state.detailDays
    ];
    if (state.detailIdentity === "strict" && product.brand) {
      params.push("brand=" + encodeURIComponent(product.brand));
    }
    if (state.detailIdentity === "strict" && typeof product.quantity === "number") {
      params.push("quantity=" + encodeURIComponent(product.quantity));
      if (product.unit) { params.push("unit=" + encodeURIComponent(product.unit)); }
    }
    NS.api.get("/api/v1/products/price-insights?" + params.join("&"))
      .then(renderDetail)
      .catch(function (error) {
        var box = $("detail-error");
        if (box) { box.hidden = false; box.textContent = error.message; }
      });
  }

  function renderDetail(data) {
    var points = data.points || [];
    var stats = data.stats || {};
    var verdict = data.verdict || {};
    var verdictBox = $("detail-verdict");
    verdictBox.hidden = false;
    verdictBox.className = "verdict " + (verdict.level || "unknown");
    verdictBox.textContent = "";
    var strong = document.createElement("strong");
    strong.textContent = verdict.label || "";
    verdictBox.appendChild(strong);
    var reason = document.createElement("span");
    reason.textContent = " " + (verdict.reason || "");
    verdictBox.appendChild(reason);

    var metrics = [
      { label: "Aktuell", value: stats.current },
      { label: "Tiefstpreis", value: stats.low },
      { label: "Durchschnitt", value: stats.average },
      { label: "Höchstpreis", value: stats.high }
    ];
    var grid = $("detail-metrics");
    grid.textContent = "";
    metrics.forEach(function (metric) {
      var dl = document.createElement("dl");
      dl.className = "metric" + (verdict.level === "top" && metric.label === "Aktuell" ? " highlight" : "");
      var dt = document.createElement("dt");
      dt.textContent = metric.label;
      var dd = document.createElement("dd");
      dd.textContent = typeof metric.value === "number" ? euro.format(metric.value) : "–";
      dl.appendChild(dt);
      dl.appendChild(dd);
      grid.appendChild(dl);
    });

    renderChart(points);
    renderStoreComparison(data.stores || []);

    var note = $("detail-note");
    note.textContent = points.length
      ? "Grundlage: " + points.length + " aufgezeichnete Preise (Community, anonymisiert)."
      : "Noch keine Preisdaten – scanne einen Kassenbon, um die Historie aufzubauen.";
  }

  function renderChart(points) {
    var svg = $("detail-chart");
    if (!svg) { return; }
    Array.prototype.slice.call(svg.childNodes).forEach(function (node) {
      if (node.nodeName !== "title" && node.nodeName !== "desc") { node.remove(); }
    });
    if (!points.length) { return; }
    var W = 640, H = 240, padL = 52, padR = 14, padT = 18, padB = 34;
    var prices = points.map(function (p) { return Number(p.price); });
    var min = Math.min.apply(null, prices);
    var max = Math.max.apply(null, prices);
    if (max - min < 0.01) { max = min + 0.5; }
    var pad = (max - min) * 0.12;
    var lo = Math.max(0, min - pad);
    var hi = max + pad;
    var times = points.map(function (p) { return Date.parse(p.changed_at) || 0; });
    var tMin = Math.min.apply(null, times);
    var tMax = Math.max.apply(null, times);
    if (tMax === tMin) { tMin -= 86400000; tMax += 86400000; }

    function x(t) { return padL + ((t - tMin) / (tMax - tMin)) * (W - padL - padR); }
    function y(v) { return H - padB - ((v - lo) / (hi - lo)) * (H - padT - padB); }

    [lo, (lo + hi) / 2, hi].forEach(function (value) {
      var line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", padL);
      line.setAttribute("x2", W - padR);
      line.setAttribute("y1", y(value));
      line.setAttribute("y2", y(value));
      line.setAttribute("class", "grid-line");
      svg.appendChild(line);
      var label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("x", padL - 8);
      label.setAttribute("y", y(value) + 4);
      label.setAttribute("text-anchor", "end");
      label.setAttribute("class", "axis");
      label.textContent = euro.format(value);
      svg.appendChild(label);
    });

    var d = "";
    points.forEach(function (point, index) {
      var px = x(times[index]);
      var py = y(Number(point.price));
      d += (index === 0 ? "M" : "L") + px.toFixed(1) + " " + py.toFixed(1) + " ";
    });
    var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d.trim());
    path.setAttribute("class", "series");
    svg.appendChild(path);

    points.forEach(function (point, index) {
      var dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("cx", x(times[index]));
      dot.setAttribute("cy", y(Number(point.price)));
      dot.setAttribute("r", 3.5);
      dot.setAttribute("class", "dot");
      svg.appendChild(dot);
    });
  }

  function renderStoreComparison(stores) {
    var box = $("detail-stores");
    var list = $("detail-stores-list");
    if (!box || !list) { return; }
    list.textContent = "";
    if (!stores.length) { box.hidden = true; return; }
    stores.slice(0, 6).forEach(function (entry, index) {
      var li = document.createElement("li");
      li.className = "detail-store-row";
      li.appendChild(NS.storeBadge(NS.storeInfo(entry.store)));
      var price = document.createElement("span");
      price.className = "price" + (index === 0 ? " cheapest" : "");
      price.textContent = typeof entry.price === "number" ? euro.format(entry.price) : "–";
      li.appendChild(price);
      var date = document.createElement("span");
      date.className = "date";
      date.textContent = entry.date ? NS.formatDate(entry.date) : "";
      li.appendChild(date);
      list.appendChild(li);
    });
    box.hidden = false;
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
      els.query.value = text;
      runSearch();
    };
    recognition.start();
  }

  function searchTerms(terms) {
    if (!terms || !terms.length) { return; }
    var collected = [];
    var seq = ++state.requestSeq;
    var chain = Promise.resolve();
    terms.forEach(function (term) {
      chain = chain.then(function () {
        var params = [
          "query=" + encodeURIComponent(term),
          "postal_code=" + encodeURIComponent(NS.state.postalCode),
          "stores=" + encodeURIComponent(selectedStores().join(",")),
          "limit=" + encodeURIComponent(els.limit.value),
          "precise=" + (els.precise.checked ? "true" : "false"),
          "today_only=" + (els.todayOnly.checked ? "true" : "false"),
          "include_standard=" + (els.standard.checked ? "true" : "false")
        ];
        return NS.api.get("/api/v1/products/search/ranked?" + params.join("&"))
          .then(function (data) {
            (data.items || []).forEach(function (item) { collected.push(item); });
          });
      });
    });
    chain.then(function () {
      if (seq !== state.requestSeq) { return; }
      state.query = terms.join(", ");
      state.items = collected.map(function (item) {
        return { product: item.product, relevance: item.relevance || {}, validity: item.validity || {} };
      });
      if (els.state) { els.state.textContent = ""; }
      renderResults();
    }).catch(function (error) {
      els.state.textContent = error.message || "Suche fehlgeschlagen.";
    });
  }

  NS.views = NS.views || {};
  NS.views.prices = {
    init: init,
    search: runSearch,
    searchTerms: searchTerms,
    setQuery: function (value) { els.query.value = value; },
    openDetail: openDetail
  };
})(window);
