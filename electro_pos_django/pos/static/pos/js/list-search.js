/* Generic instant (as-you-type) table filter, used on the Products,
   Customers, and Warranties list pages. No page reload, no Enter key
   needed — matches against a `data-search` attribute set on each row. */

function initLiveSearch({ inputId, rowSelector, emptyId }) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const wrap = input.closest(".search-box");
  const clearBtn = wrap ? wrap.querySelector(".clear-btn") : null;
  const emptyEl = emptyId ? document.getElementById(emptyId) : null;

  function applyFilter() {
    const q = input.value.trim().toLowerCase();
    if (wrap) wrap.classList.toggle("has-value", q.length > 0);

    const rows = document.querySelectorAll(rowSelector);
    let visibleCount = 0;
    rows.forEach((row) => {
      const haystack = (row.dataset.search || "").toLowerCase();
      const match = !q || haystack.includes(q);
      row.style.display = match ? "" : "none";
      if (match) visibleCount += 1;
    });

    if (emptyEl) emptyEl.style.display = visibleCount === 0 ? "block" : "none";
  }

  input.addEventListener("input", applyFilter);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") e.preventDefault(); // filtering is already live; don't submit/reload
  });
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      input.value = "";
      applyFilter();
      input.focus();
    });
  }

  applyFilter();
}
