/* Shared UI chrome: a glass-styled confirmation modal (replacing the native
   browser confirm()) and animated toast notifications (replacing the plain
   inline flash banner). Both follow the same design tokens as the rest of
   the app. */

(function () {
  // -------------------------------------------------------------------
  // Confirmation modal
  // -------------------------------------------------------------------
  function confirmAction(message, options) {
    options = options || {};
    const title = options.title || "تأكيد الإجراء";
    const confirmLabel = options.confirmLabel || "تأكيد";
    const cancelLabel = options.cancelLabel || "إلغاء";
    const tone = options.tone || "danger"; // "danger" | "info"

    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "modal-overlay";
      overlay.innerHTML = `
        <div class="modal-card" role="alertdialog" aria-modal="true">
          <div class="modal-icon ${tone === "info" ? "info" : ""}">
            ${
              tone === "info"
                ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>'
                : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>'
            }
          </div>
          <div class="modal-title">${title}</div>
          <div class="modal-message">${message}</div>
          <div class="modal-actions">
            <button type="button" class="btn modal-cancel">${cancelLabel}</button>
            <button type="button" class="btn ${tone === "info" ? "btn-primary" : "btn-danger"} modal-confirm" style="${tone === "danger" ? "background:linear-gradient(160deg,#f87171,#ef4444);border-color:transparent;color:#fff;" : ""}">${confirmLabel}</button>
          </div>
        </div>`;
      document.body.appendChild(overlay);
      document.body.style.overflow = "hidden";

      requestAnimationFrame(() => overlay.classList.add("show"));

      function close(result) {
        overlay.classList.remove("show");
        document.body.style.overflow = "";
        setTimeout(() => overlay.remove(), 250);
        resolve(result);
      }

      overlay.querySelector(".modal-confirm").addEventListener("click", () => close(true));
      overlay.querySelector(".modal-cancel").addEventListener("click", () => close(false));
      overlay.addEventListener("click", (e) => {
        if (e.target === overlay) close(false);
      });
      const escHandler = (e) => {
        if (e.key === "Escape") {
          close(false);
          document.removeEventListener("keydown", escHandler);
        }
      };
      document.addEventListener("keydown", escHandler);
    });
  }
  window.confirmAction = confirmAction;

  // Auto-wire any form with a data-confirm attribute — no per-page JS needed.
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      const message = form.dataset.confirm;
      const tone = form.dataset.confirmTone || "danger";
      const confirmLabel = form.dataset.confirmLabel || undefined;
      confirmAction(message, { tone, confirmLabel }).then((ok) => {
        if (ok) form.submit();
      });
    });
  });

  // -------------------------------------------------------------------
  // Toast notifications (rendered server-side from Django messages,
  // animated in here, auto-dismissed after a few seconds)
  // -------------------------------------------------------------------
  const toasts = document.querySelectorAll(".toast");
  toasts.forEach((toast, i) => {
    setTimeout(() => toast.classList.add("show"), 60 + i * 90);

    const dismiss = () => {
      toast.classList.remove("show");
      setTimeout(() => toast.remove(), 400);
    };
    const closeBtn = toast.querySelector(".toast-close");
    if (closeBtn) closeBtn.addEventListener("click", dismiss);

    setTimeout(dismiss, 6000 + i * 400);
  });
})();
