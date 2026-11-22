/* FairBon — Tab 1: monthly overview, SVG donut and category breakdown (ES5). */
(function (global) {
  "use strict";

  var NS = global.FairBon = global.FairBon || {};
  var euro = NS.euro;
  var els = {};
  var months = [];
  var monthIndex = 0;

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
    if (!els.label) { return; }

    $("month-prev").addEventListener("click", function () { shiftMonth(1); });
    $("month-next").addEventListener("click", function () { shiftMonth(-1); });

    NS.on("receipts-changed", load);
    load();
  }

  function shiftMonth(delta) {
    var next = monthIndex + delta;
    if (next < 0) { next = 0; }
    if (next >= months.length) { next = months.length - 1; }
    if (next === monthIndex) { return; }
    monthIndex = next;
    render(months[monthIndex]);
  }

  function load() {
    NS.api.get("/api/v1/receipts/stats")
      .then(function (data) {
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
      .catch(function () {
        render(currentMonth());
      });
  }

  function currentMonth() {
    var now = new Date();
    return now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0");
  }

  function render(month, data) {
    var entry = null;
    (data && data.by_month || []).forEach(function (row) {
      if (row.month === month) { entry = row; }
    });
    if (!data) {
      NS.api.get("/api/v1/receipts/stats?month=" + encodeURIComponent(month))
        .then(function (fresh) { render(month, fresh); })
        .catch(function () {});
      return;
    }
    els.label.textContent = NS.formatMonth(month);

    var demoCard = $("demo-card");
    if (demoCard) {
      demoCard.hidden = (data.by_month || []).length > 0;
    }

    var total = data.total_cents || 0;
    els.total.textContent = euro.format(total / 100);
    els.average.textContent = euro.format((data.average_cents || 0) / 100);
    els.count.textContent = String(data.receipt_count || 0);
    els.shared.textContent = String(data.shared_count || 0);

    var budget = Number(NS.state.budget) || 0;
    if (budget > 0) {
      var ratio = Math.min(1, total / 100 / budget);
      els.budgetHint.textContent = Math.round(ratio * 100) + " % von " + euro.format(budget);
      drawDonut(ratio, ratio >= 1);
    } else {
      els.budgetHint.textContent = "Ausgaben";
      drawDonut(total > 0 ? 0.72 : 0.04, false);
    }

    renderCategories(data.categories || [], total);
  }

  function drawDonut(ratio, overBudget) {
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
    if (overBudget) { value.style.stroke = "var(--danger)"; }
    svg.appendChild(value);
  }

  function renderCategories(categories, total) {
    els.bars.textContent = "";
    if (!categories.length) {
      els.empty.hidden = false;
      return;
    }
    els.empty.hidden = true;
    var max = categories[0].total_cents || 1;
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
      fill.style.width = Math.max(4, Math.round((entry.total_cents / max) * 100)) + "%";
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
