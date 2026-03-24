/**
 * Sortable Table System
 *
 * Auto-discovers tables with class="sortable-table" and adds:
 *   - Click-to-sort on any <th data-sort="column_key">
 *   - Arrow indicators (↑↓) showing current sort
 *   - Row number auto-renumbering after sort
 *   - Search/filter via <input data-table-search="tableId">
 *   - Fetch-and-append via data-table-fetch="/api/..." for surfacing
 *     players not currently in the table
 *
 * Data attribute convention:
 *   <table class="sortable-table" id="my-table"
 *          data-default-sort="projected_points" data-default-dir="desc">
 *     <thead><tr>
 *       <th data-sort="name">Player</th>
 *       <th data-sort="projected_points">Proj Pts</th>
 *     </tr></thead>
 *     <tbody>
 *       <tr data-name="Mike Trout" data-projected_points="245.3">...</tr>
 *     </tbody>
 *   </table>
 *   <input data-table-search="my-table"
 *          data-table-fetch="/api/points/search?type=hitter" />
 */

(function () {
  "use strict";

  // State per table: { tableId: { column, ascending } }
  const sortState = {};

  function initSortableTable(table) {
    const id = table.id;
    if (!id) return;

    const defaultSort = table.dataset.defaultSort || "";
    const defaultDir = table.dataset.defaultDir || "desc";

    sortState[id] = {
      column: defaultSort,
      ascending: defaultDir === "asc",
    };

    // Style and wire up sortable headers
    const headers = table.querySelectorAll("th[data-sort]");
    headers.forEach((th) => {
      th.classList.add("cursor-pointer");
      th.classList.add("select-none");
      th.addEventListener("mouseenter", () =>
        th.classList.add("text-blue-400")
      );
      th.addEventListener("mouseleave", () =>
        th.classList.remove("text-blue-400")
      );

      // Add sort indicator span if not present
      if (!th.querySelector(".sort-ind")) {
        const span = document.createElement("span");
        span.className = "sort-ind text-gray-500 ml-0.5";
        th.appendChild(span);
      }

      th.addEventListener("click", () => {
        const col = th.dataset.sort;
        const state = sortState[id];
        if (state.column === col) {
          state.ascending = !state.ascending;
        } else {
          state.column = col;
          state.ascending = false; // default descending for new column
        }
        doSort(table);
      });
    });

    // Apply default sort indicators (no re-sort needed — server already sorted)
    updateIndicators(table);
  }

  function doSort(table) {
    const id = table.id;
    const state = sortState[id];
    const tbody = table.querySelector("tbody");
    if (!tbody) return;

    const rows = Array.from(tbody.querySelectorAll("tr"));
    const col = state.column;
    const asc = state.ascending;

    rows.sort((a, b) => {
      const aVal = a.dataset[col] ?? "";
      const bVal = b.dataset[col] ?? "";

      const aNum = parseFloat(aVal);
      const bNum = parseFloat(bVal);
      if (!isNaN(aNum) && !isNaN(bNum)) {
        return asc ? aNum - bNum : bNum - aNum;
      }
      return asc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    });

    rows.forEach((row) => tbody.appendChild(row));
    renumber(tbody);
    updateIndicators(table);
  }

  function renumber(tbody) {
    const visibleRows = Array.from(tbody.querySelectorAll("tr")).filter(
      (r) => r.style.display !== "none"
    );
    visibleRows.forEach((row, i) => {
      const numCell = row.querySelector("td.row-number");
      if (numCell) numCell.textContent = i + 1;
    });
  }

  function updateIndicators(table) {
    const id = table.id;
    const state = sortState[id];
    table.querySelectorAll("th[data-sort] .sort-ind").forEach((el) => {
      const col = el.closest("th").dataset.sort;
      if (col === state.column) {
        el.textContent = state.ascending ? " \u2191" : " \u2193";
        el.classList.remove("text-gray-500");
        el.classList.add("text-blue-400");
      } else {
        el.textContent = "";
        el.classList.remove("text-blue-400");
        el.classList.add("text-gray-500");
      }
    });
  }

  // ── Search & Filter ──

  function initSearch(input) {
    const tableId = input.dataset.tableSearch;
    const fetchUrl = input.dataset.tableFetch || "";
    let debounceTimer = null;
    let lastFetchQuery = "";

    input.addEventListener("input", () => {
      const query = input.value.trim().toLowerCase();

      // Always filter existing rows immediately
      filterRows(tableId, query);

      // Fetch additional results if URL configured and query is long enough
      if (fetchUrl && query.length >= 2) {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          if (query !== lastFetchQuery) {
            lastFetchQuery = query;
            fetchResults(tableId, fetchUrl, query);
          }
        }, 400);
      }

      // If query cleared, remove fetched rows and show all originals
      if (!query) {
        lastFetchQuery = "";
        removeFetchedRows(tableId);
        showAllRows(tableId);
      }
    });
  }

  function filterRows(tableId, query) {
    const table = document.getElementById(tableId);
    if (!table) return;
    const tbody = table.querySelector("tbody");
    if (!tbody) return;

    const rows = tbody.querySelectorAll("tr:not(.fetched-row)");
    rows.forEach((row) => {
      if (!query) {
        row.style.display = "";
        return;
      }
      const name = (row.dataset.name || "").toLowerCase();
      const team = (row.dataset.team || "").toLowerCase();
      const pos = (row.dataset.position || "").toLowerCase();
      const matches =
        name.includes(query) || team.includes(query) || pos.includes(query);
      row.style.display = matches ? "" : "none";
    });

    renumber(tbody);
  }

  function showAllRows(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;
    const tbody = table.querySelector("tbody");
    if (!tbody) return;
    tbody
      .querySelectorAll("tr:not(.fetched-row)")
      .forEach((r) => (r.style.display = ""));
    renumber(tbody);
  }

  function removeFetchedRows(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;
    table.querySelectorAll(".fetched-row").forEach((r) => r.remove());
  }

  async function fetchResults(tableId, baseUrl, query) {
    const table = document.getElementById(tableId);
    if (!table) return;
    const tbody = table.querySelector("tbody");
    if (!tbody) return;

    // Build URL with query param
    const sep = baseUrl.includes("?") ? "&" : "?";
    const url = `${baseUrl}${sep}q=${encodeURIComponent(query)}`;

    try {
      const resp = await fetch(url);
      if (!resp.ok) return;
      const players = await resp.json();

      // Remove previous fetched rows
      removeFetchedRows(tableId);

      // Get existing player names to avoid duplicates
      const existing = new Set();
      tbody.querySelectorAll("tr:not(.fetched-row)").forEach((r) => {
        if (r.dataset.name) existing.add(r.dataset.name.toLowerCase());
      });

      // Get column order from headers
      const headers = [];
      table
        .querySelectorAll("th[data-sort]")
        .forEach((th) => headers.push(th.dataset.sort));

      players.forEach((p) => {
        if (existing.has((p.name || "").toLowerCase())) return;

        const tr = document.createElement("tr");
        tr.className =
          "fetched-row border-b border-gray-700/50 bg-blue-900/10";

        // Set data attributes for sorting/filtering
        Object.keys(p).forEach((key) => {
          tr.dataset[key] = p[key] ?? "";
        });

        // Build cells matching the table's column structure
        const headerCells = table.querySelectorAll("thead th");
        headerCells.forEach((th) => {
          const td = document.createElement("td");
          td.className = "py-2 px-3 text-sm";
          const sortKey = th.dataset.sort;

          if (th.classList.contains("row-number")) {
            td.className += " row-number text-gray-500";
            td.textContent = "-";
          } else if (sortKey === "name") {
            td.className += " text-blue-300";
            const ownerBadge = p.fantasy_team
              ? `<span class="text-[10px] ml-1 ${p.is_my_team ? "text-blue-400" : "text-gray-600"}">${p.fantasy_team}</span>`
              : '<span class="text-[10px] ml-1 text-gray-700">FA</span>';
            td.innerHTML = `${p.name || ""} <span class="text-gray-500 text-xs">${p.team || ""}, ${p.position || ""}</span> ${ownerBadge}`;
          } else if (sortKey && p[sortKey] !== undefined) {
            td.className += " text-right text-gray-400";
            const val = p[sortKey];
            td.textContent =
              typeof val === "number" ? val.toFixed(1) : val || "-";
          } else if (!sortKey && th.textContent.trim() === "#") {
            td.className += " row-number text-gray-500";
            td.textContent = "-";
          } else {
            td.textContent = "";
          }

          tr.appendChild(td);
        });

        tbody.appendChild(tr);
      });
    } catch (e) {
      // Silently fail — search is best-effort
    }
  }

  // ── Initialization ──

  function init() {
    document
      .querySelectorAll(".sortable-table")
      .forEach((t) => initSortableTable(t));
    document
      .querySelectorAll("input[data-table-search]")
      .forEach((i) => initSearch(i));
  }

  // Init on DOM ready and after HTMX swaps (for dynamically loaded content)
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  document.addEventListener("htmx:afterSettle", init);

  // Expose for programmatic use (e.g., dynamically rendered tables)
  window.initSortableTable = initSortableTable;
})();
