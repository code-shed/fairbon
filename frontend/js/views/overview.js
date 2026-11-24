/* FairBon — Tab 1: monthly overview, SVG donut and category breakdown (ES5). */
(function (global) {
  "use strict";

  var NS = global.FairBon = global.FairBon || {};
  var euro = NS.euro;
  var els = {};
  var months = [];
  var monthIndex = 0;
  var loaded = false;
  var ringMode = "budget";
  var lastMonth = "";
  var lastData = null;

  function $(id) { return document.getElementById(id); }

  function init() {
    els.label = $("month-label");
    els.total = $("overview-total");
    els.average = $("overview-average");
    els.count = $("overview-count");
    els.shared = $("overview-shared");
    els.donut = $("spend-donut");
    els.bars = $("category-bars");
    els.empty = $("categories-empty");
    els.budgetHint = $("overview-budget-hint");
    els.status = $("overview-status");
    els.statusText = $("overview-status-text");
    els.retry = $("overview-retry");
    els.ringIndicator = $("ring-indicator");
    els.emptyHint = $("overview-empty-hint");
    if (!els.label) { return; }

    els.empty.hidden = true;
    els.retry.addEventListener("click", load);
    $("month-prev").addEventListener("click", function () { shiftMonth(1); });
    $("month-next").addEventListener("click", function () { shiftMonth(-1); });
    if (els.donut) {
      els.donut.style.cursor = "pointer";
      els.donut.setAttribute("role", "button");
      els.donut.setAttribute("tabindex", "0");
      els.donut.setAttribute("aria-label", "Ringansicht wechseln");
      els.donut.addEventListener("click", toggleRingMode);
      els.donut.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") { toggleRingMode(); }
      });
    }

    NS.on("receipts-changed", load);
    load();
  }

  function shiftMonth(delta) {
    if (!months.length) { return; }
    var next = monthIndex + delta;
    if (next < 0) { next = 0; }
    if (next >= months.length) { next = months.length - 1; }
    if (next === monthIndex) { return; }
    monthIndex = next;
    render(months[monthIndex]);
  }

  function load() {
    if (!loaded) { showStatus("Übersicht wird geladen …", false); }
    NS.api.get("/api/v1/receipts/stats?start_day=" +
      encodeURIComponent(NS.state.budgetStart || 1))
      .then(function (data) {
        loaded = true;
        months = (data.by_month || []).map(function (entry) { return entry.month; });
        if (!months.length) {
          months = [currentMonth()];
        }
        var month = NS.state.month || data.month || months[0];
        monthIndex = months.indexOf(month);
        if (monthIndex < 0) { monthIndex = 0; }
        NS.state.month = months[monthIndex];
        render(months[monthIndex], data);
      })
      .catch(function (error) {
        showStatus("Übersicht konnte nicht geladen werden. " + (error.message || ""), true);
      });
  }

  function showStatus(text, retry) {
    els.status.hidden = false;
    els.statusText.textContent = text;
    els.retry.hidden = !retry;
  }

  function hideStatus() {
    els.status.hidden = true;
    els.retry.hidden = true;
  }

  function currentMonth() {
    var now = new Date();
    return now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0");
  }

  function toggleRingMode() {
    ringMode = ringMode === "budget" ? "savings" : "budget";
    if (lastMonth) { render(lastMonth, lastData); }
  }

  function shortDate(iso) {
    var parts = String(iso || "").split("-");
    return parts.length === 3
      ? parts[2] + "." + parts[1] + "." + parts[0].slice(2)
      : String(iso || "");
  }

  function daysLeft(iso) {
    if (!iso) { return 1; }
    var end = new Date(iso + "T23:59:59");
    var now = new Date();
    return Math.max(1, Math.ceil((end - now) / 86400000));
  }

  function render(month, data) {
    lastMonth = month;
    lastData = data;
    var entry = null;
    (data && data.by_month || []).forEach(function (row) {
      if (row.month === month) { entry = row; }
    });
    if (!data) {
      NS.api.get("/api/v1/receipts/stats?month=" + encodeURIComponent(month) +
        "&start_day=" + encodeURIComponent(NS.state.budgetStart || 1))
        .then(function (fresh) { render(month, fresh); })
        .catch(function (error) {
          showStatus("Monat konnte nicht geladen werden. " + (error.message || ""), true);
        });
      return;
    }
    hideStatus();
    var period = data.period || {};
    els.label.textContent = period.from && period.to
      ? shortDate(period.from) + " – " + shortDate(period.to)
      : NS.formatMonth(month);

    var demoCard = $("demo-card");
    if (demoCard) {
      var empty = (data.receipt_count || 0) === 0;
      demoCard.hidden = !empty;
      if (els.emptyHint) { els.emptyHint.hidden = !empty; }
    }

    var total = data.total_cents || 0;
    els.total.textContent = euro.format(total / 100);
    els.average.textContent = euro.format((data.average_cents || 0) / 100);
    els.count.textContent = String(data.receipt_count || 0);
    els.shared.textContent = String(data.shared_count || 0);
    var communityCount = $("community-count");
    if (communityCount) {
      communityCount.textContent = String(data.shared_count || 0) +
        " Preise geteilt";
    }

    var budget = Number(NS.state.budget) || 0;
    var savings = (data.discount_cents || 0) / 100;
    if (ringMode === "savings") {
      var savedRatio = Math.min(1, budget > 0 ? savings / budget : (total > 0 ? savings / (total / 100) : 0));
      els.budgetHint.textContent = "Ersparnis durch Rabatte · " + euro.format(savings);
      drawDonut(total > 0 || savings > 0 ? Math.max(0.04, savedRatio) : 0.04, "var(--accent)");
    } else if (budget > 0) {
      var remainingCents = Math.max(0, Math.round(budget * 100) - total);
      var remaining = remainingCents / 100;
      var ratio = remainingCents / (budget * 100);
      var colour = ratio > 0.3 ? "var(--accent)"
        : ratio >= 0.1 ? "#d99b26" : "#d64545";
      var perDay = remaining / daysLeft(period.to);
      els.budgetHint.textContent = "Noch " + euro.format(remaining) +
        " übrig · ca. " + euro.format(perDay) + " / Tag";
      drawDonut(Math.min(1, Math.max(0, ratio)), colour);
    } else {
      els.budgetHint.textContent = "Ausgaben";
      drawDonut(total > 0 ? 0.72 : 0.04, "var(--accent)");
    }
    if (els.ringIndicator) {
      els.ringIndicator.textContent = ringMode === "budget" ? "● ○" : "○ ●";
    }

    renderCategories(data.categories || [], total);
  }

  function drawDonut(ratio, colour) {
    var svg = els.donut;
    if (!svg) { return; }
    svg.textContent = "";
    var r = 62;
    var c = 2 * Math.PI * r;
    var track = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    track.setAttribute("cx", "80");
    track.setAttribute("cy", "80");
    track.setAttribute("r", String(r));
    track.setAttribute("class", "track");
    svg.appendChild(track);
    var value = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    value.setAttribute("cx", "80");
    value.setAttribute("cy", "80");
    value.setAttribute("r", String(r));
    value.setAttribute("class", "value");
    value.setAttribute("stroke-dasharray", String(c));
    value.setAttribute("stroke-dashoffset", String(c * (1 - Math.max(0, Math.min(1, ratio)))));
    if (colour) { value.style.stroke = colour; }
    svg.appendChild(value);
  }

  function renderCategories(categories, total) {
    els.bars.textContent = "";
    if (!categories.length) {
      els.empty.hidden = false;
      return;
    }
    els.empty.hidden = true;
    categories.forEach(function (entry) {
      var row = document.createElement("button");
      row.type = "button";
      row.className = "category-row";
      row.setAttribute("aria-label", entry.category + " filtern");

      var name = document.createElement("span");
      name.className = "cat-name";
      name.textContent = entry.category;
      var value = document.createElement("span");
      value.className = "cat-value";
      value.textContent = euro.format(entry.total_cents / 100);
      var track = document.createElement("span");
      track.className = "category-track";
      var fill = document.createElement("span");
      fill.className = "category-fill";
      var share = total > 0 ? entry.total_cents / total : 0;
      fill.style.width = Math.max(4, Math.round(share * 100)) + "%";
      track.appendChild(fill);

      row.appendChild(name);
      row.appendChild(value);
      row.appendChild(track);
      row.addEventListener("click", function () {
        NS.emit("open-receipts", { category: entry.category });
      });
      els.bars.appendChild(row);
    });
  }

  NS.views = NS.views || {};
  NS.views.overview = { init: init, reload: load };
})(window);
