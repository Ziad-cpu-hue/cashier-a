/* Cashier screen behaviour: product grid, cart/ticket state, and checkout. */

(function () {
  let cart = {};            // product_id -> { product, qty, serial }
  let paymentMethod = "cash";
  let activeCategory = "الكل";

  const grid = document.getElementById("product-grid");
  const chipsWrap = document.getElementById("category-chips");
  const searchInput = document.getElementById("product-search");
  const ticketItemsEl = document.getElementById("ticket-items");
  const cartErrorEl = document.getElementById("cart-error");
  const completeBtn = document.getElementById("complete-sale");

  // ---------------------------------------------------------------------
  // CSRF helper (Django requires the csrftoken cookie echoed as a header
  // on any state-changing request, since /api/sale/ is called via fetch
  // rather than a plain HTML <form>).
  // ---------------------------------------------------------------------
  function getCookie(name) {
    const match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return match ? decodeURIComponent(match[2]) : null;
  }

  // ---------------------------------------------------------------------
  // Category chips
  // ---------------------------------------------------------------------
  function renderChips() {
    const categories = ["الكل", ...new Set(PRODUCTS.map((p) => p.category))];
    chipsWrap.innerHTML = categories
      .map(
        (c) =>
          `<div class="chip ${c === activeCategory ? "active" : ""}" data-cat="${escapeHtml(c)}">${escapeHtml(c)}</div>`
      )
      .join("");
    chipsWrap.querySelectorAll(".chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        activeCategory = chip.dataset.cat;
        renderChips();
        renderGrid();
      });
    });
  }

  // ---------------------------------------------------------------------
  // Product grid
  // ---------------------------------------------------------------------
  function renderGrid() {
    const q = searchInput.value.trim().toLowerCase();
    let list = PRODUCTS;
    if (activeCategory !== "الكل") {
      list = list.filter((p) => p.category === activeCategory);
    }
    if (q) {
      list = list.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          (p.barcode || "").toLowerCase().includes(q)
      );
    }

    if (list.length === 0) {
      grid.innerHTML = `<div class="empty" style="grid-column:1/-1;">لا توجد منتجات مطابقة لبحثك.</div>`;
      return;
    }

    grid.innerHTML = list
      .map((p) => {
        const out = p.quantity <= 0;
        const low = p.quantity > 0 && p.quantity <= p.low_stock_threshold;
        return `
        <div class="product-card ${out ? "out-of-stock" : ""}" data-id="${p.id}">
          <div class="cat">${escapeHtml(p.category)}</div>
          <div class="name">${escapeHtml(p.name)}</div>
          <div class="stock ${low ? "low" : ""}">${out ? "نفد المخزون" : "متوفر: " + p.quantity}</div>
          <div class="price">${p.price.toFixed(2)} ج.م</div>
        </div>`;
      })
      .join("");

    grid.querySelectorAll(".product-card:not(.out-of-stock)").forEach((card) => {
      card.addEventListener("click", () => addToCart(parseInt(card.dataset.id, 10)));
    });
  }

  searchInput.addEventListener("input", renderGrid);

  // ---------------------------------------------------------------------
  // Cart operations
  // ---------------------------------------------------------------------
  function findProduct(id) {
    return PRODUCTS.find((p) => p.id === id);
  }

  function addToCart(productId) {
    const product = findProduct(productId);
    if (!product || product.quantity <= 0) return;

    if (!cart[productId]) {
      cart[productId] = { product, qty: 0, serial: "" };
    }
    if (cart[productId].qty >= product.quantity) {
      showCartError(`لا يوجد سوى ${product.quantity} قطعة من "${product.name}" متاحة.`);
      return;
    }
    cart[productId].qty += 1;
    clearCartError();
    renderTicket();
  }

  function changeQty(productId, delta) {
    const line = cart[productId];
    if (!line) return;
    const newQty = line.qty + delta;
    if (newQty <= 0) {
      delete cart[productId];
    } else if (newQty > line.product.quantity) {
      showCartError(`لا يوجد سوى ${line.product.quantity} قطعة من "${line.product.name}" متاحة.`);
      return;
    } else {
      line.qty = newQty;
    }
    clearCartError();
    renderTicket();
  }

  function removeLine(productId) {
    delete cart[productId];
    renderTicket();
  }

  function showCartError(msg) {
    cartErrorEl.textContent = msg;
    cartErrorEl.style.display = "block";
  }
  function clearCartError() {
    cartErrorEl.style.display = "none";
    cartErrorEl.textContent = "";
  }

  // ---------------------------------------------------------------------
  // Ticket / totals rendering
  // ---------------------------------------------------------------------
  function renderTicket() {
    const lines = Object.values(cart);
    if (lines.length === 0) {
      ticketItemsEl.innerHTML = `<div class="ticket-empty">السلة فارغة. اضغط على منتج لإضافته.</div>`;
    } else {
      ticketItemsEl.innerHTML = lines
        .map((line) => {
          const p = line.product;
          const lineTotal = p.price * line.qty;
          const showSerial = p.warranty_months > 0;
          return `
          <div class="ticket-item" data-id="${p.id}">
            <div class="ticket-item-top">
              <div class="ticket-item-name">${escapeHtml(p.name)}</div>
              <div class="ticket-item-remove" data-remove="${p.id}">&times;</div>
            </div>
            <div class="ticket-item-controls">
              <button type="button" class="qty-btn" data-dec="${p.id}">−</button>
              <div class="qty-val">${line.qty}</div>
              <button type="button" class="qty-btn" data-inc="${p.id}">+</button>
              <div class="ticket-item-price mono">${lineTotal.toFixed(2)}</div>
            </div>
            ${
              showSerial
                ? `<div class="ticket-item-serial">
                     <input type="text" placeholder="الرقم التسلسلي (للضمان)" data-serial="${p.id}" value="${escapeHtml(line.serial)}">
                   </div>`
                : ""
            }
          </div>`;
        })
        .join("");

      ticketItemsEl.querySelectorAll("[data-inc]").forEach((btn) =>
        btn.addEventListener("click", () => changeQty(parseInt(btn.dataset.inc, 10), 1))
      );
      ticketItemsEl.querySelectorAll("[data-dec]").forEach((btn) =>
        btn.addEventListener("click", () => changeQty(parseInt(btn.dataset.dec, 10), -1))
      );
      ticketItemsEl.querySelectorAll("[data-remove]").forEach((btn) =>
        btn.addEventListener("click", () => removeLine(parseInt(btn.dataset.remove, 10)))
      );
      ticketItemsEl.querySelectorAll("[data-serial]").forEach((input) =>
        input.addEventListener("input", () => {
          const id = parseInt(input.dataset.serial, 10);
          if (cart[id]) cart[id].serial = input.value;
        })
      );
    }

    renderTotals();
  }

  function cartSubtotal() {
    return Object.values(cart).reduce((sum, line) => sum + line.product.price * line.qty, 0);
  }

  function renderTotals() {
    const subtotal = cartSubtotal();
    const discount = Math.min(parseFloat(document.getElementById("discount").value) || 0, subtotal);
    const total = Math.max(subtotal - discount, 0);

    document.getElementById("sum-subtotal").textContent = subtotal.toFixed(2);
    document.getElementById("sum-discount").textContent = discount.toFixed(2);
    document.getElementById("sum-total").textContent = total.toFixed(2);

    renderInstallmentPreview(total);

    const hasItems = Object.keys(cart).length > 0;
    completeBtn.disabled = !hasItems;
  }

  function renderInstallmentPreview(total) {
    const box = document.getElementById("installment-preview");
    if (paymentMethod !== "installment") {
      box.textContent = "";
      return;
    }
    const down = Math.min(parseFloat(document.getElementById("down-payment").value) || 0, total);
    const months = Math.max(parseInt(document.getElementById("num-months").value) || 1, 1);
    const remaining = Math.max(total - down, 0);
    const monthly = remaining / months;
    box.textContent = `${remaining.toFixed(2)} ج.م على ${months} شهر ← ${monthly.toFixed(2)} ج.م / الشهر`;
  }

  document.getElementById("discount").addEventListener("input", renderTotals);
  document.getElementById("down-payment").addEventListener("input", () => renderInstallmentPreview(parseFloat(document.getElementById("sum-total").textContent)));
  document.getElementById("num-months").addEventListener("input", () => renderInstallmentPreview(parseFloat(document.getElementById("sum-total").textContent)));

  // ---------------------------------------------------------------------
  // Payment method toggle
  // ---------------------------------------------------------------------
  const cashBtn = document.getElementById("pay-cash");
  const installmentBtn = document.getElementById("pay-installment");
  const installmentBox = document.getElementById("installment-box");

  cashBtn.addEventListener("click", () => {
    paymentMethod = "cash";
    cashBtn.classList.add("active");
    installmentBtn.classList.remove("active");
    installmentBox.classList.remove("show");
    renderTotals();
  });
  installmentBtn.addEventListener("click", () => {
    paymentMethod = "installment";
    installmentBtn.classList.add("active");
    cashBtn.classList.remove("active");
    installmentBox.classList.add("show");
    renderTotals();
  });

  // ---------------------------------------------------------------------
  // Searchable customer picker
  // ---------------------------------------------------------------------
  const pickerWrap = document.getElementById("customer-picker");
  const customerSearchInput = document.getElementById("customer-search-input");
  const customerDropdown = document.getElementById("customer-dropdown");
  const newCustomerFields = document.getElementById("new-customer-fields");

  const WALKIN = { id: "", name: "عميل مباشر", phone: "" };
  const NEW_CUSTOMER = { id: "new", name: "+ عميل جديد…", phone: "" };
  let selectedCustomer = WALKIN;
  let highlightedIndex = -1;

  function customerMatches(list, q) {
    if (!q) return list;
    const needle = q.trim().toLowerCase();
    return list.filter(
      (c) => c.name.toLowerCase().includes(needle) || (c.phone || "").includes(needle)
    );
  }

  function renderCustomerDropdown() {
    const q = customerSearchInput.value;
    const matches = customerMatches(CUSTOMERS, q);
    const rows = [];

    if (!q || "عميل مباشر".includes(q.trim())) rows.push(WALKIN);
    matches.forEach((c) => rows.push(c));
    if (!q || NEW_CUSTOMER.name.includes(q.trim())) rows.push(NEW_CUSTOMER);

    if (rows.length === 0) {
      customerDropdown.innerHTML = `<div class="searchable-option empty">لا يوجد عميل مطابق</div>`;
      highlightedIndex = -1;
      return;
    }

    customerDropdown.innerHTML = rows
      .map((c, i) => {
        const isSpecial = c === WALKIN || c === NEW_CUSTOMER;
        return `
        <div class="searchable-option ${isSpecial ? "special" : ""}" data-index="${i}">
          <span>${escapeHtml(c.name)}</span>
          ${c.phone ? `<span class="phone">${escapeHtml(c.phone)}</span>` : ""}
        </div>`;
      })
      .join("");

    customerDropdown._rows = rows;
    highlightedIndex = 0;
    updateHighlight();

    customerDropdown.querySelectorAll(".searchable-option[data-index]").forEach((el) => {
      el.addEventListener("click", () => {
        selectCustomer(rows[parseInt(el.dataset.index, 10)]);
      });
    });
  }

  function updateHighlight() {
    customerDropdown.querySelectorAll(".searchable-option[data-index]").forEach((el) => {
      el.classList.toggle("highlighted", parseInt(el.dataset.index, 10) === highlightedIndex);
    });
  }

  function selectCustomer(c) {
    selectedCustomer = c;
    if (c === NEW_CUSTOMER) {
      customerSearchInput.value = "";
      newCustomerFields.style.display = "block";
    } else {
      customerSearchInput.value = c === WALKIN ? "" : c.name;
      newCustomerFields.style.display = "none";
    }
    closeDropdown();
  }

  function openDropdown() {
    pickerWrap.classList.add("open");
    renderCustomerDropdown();
  }
  function closeDropdown() {
    pickerWrap.classList.remove("open");
  }

  customerSearchInput.addEventListener("focus", openDropdown);
  customerSearchInput.addEventListener("input", () => {
    if (selectedCustomer !== WALKIN && selectedCustomer !== NEW_CUSTOMER) {
      // typing again after a selection starts a fresh search
      selectedCustomer = WALKIN;
    }
    openDropdown();
  });
  customerSearchInput.addEventListener("keydown", (e) => {
    const rows = customerDropdown._rows || [];
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!pickerWrap.classList.contains("open")) { openDropdown(); return; }
      highlightedIndex = Math.min(highlightedIndex + 1, rows.length - 1);
      updateHighlight();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      highlightedIndex = Math.max(highlightedIndex - 1, 0);
      updateHighlight();
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (rows[highlightedIndex]) selectCustomer(rows[highlightedIndex]);
    } else if (e.key === "Escape") {
      closeDropdown();
    }
  });
  document.addEventListener("click", (e) => {
    if (!pickerWrap.contains(e.target)) closeDropdown();
  });

  // ---------------------------------------------------------------------
  // Checkout
  // ---------------------------------------------------------------------
  completeBtn.addEventListener("click", async () => {
    clearCartError();
    const items = Object.values(cart).map((line) => ({
      product_id: line.product.id,
      quantity: line.qty,
      serial_number: line.serial || "",
    }));

    if (items.length === 0) return;

    const payload = {
      payment_method: paymentMethod,
      discount: parseFloat(document.getElementById("discount").value) || 0,
      items: items,
    };

    if (selectedCustomer === NEW_CUSTOMER) {
      const name = document.getElementById("new-customer-name").value.trim();
      if (!name) {
        showCartError("يرجى إدخال اسم العميل الجديد.");
        return;
      }
      payload.new_customer_name = name;
      payload.new_customer_phone = document.getElementById("new-customer-phone").value.trim();
    } else if (selectedCustomer !== WALKIN) {
      payload.customer_id = selectedCustomer.id;
    }

    if (paymentMethod === "installment") {
      if (!payload.customer_id && !payload.new_customer_name) {
        showCartError("عمليات البيع بالتقسيط تتطلب اختيار عميل أو إضافة عميل جديد.");
        return;
      }
      payload.down_payment = parseFloat(document.getElementById("down-payment").value) || 0;
      payload.num_months = parseInt(document.getElementById("num-months").value) || 0;
    }

    completeBtn.disabled = true;
    completeBtn.textContent = "جارٍ المعالجة…";

    try {
      const res = await fetch(SALE_API_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        showCartError(data.error || "حدث خطأ أثناء إتمام عملية البيع.");
        completeBtn.disabled = false;
        completeBtn.textContent = "إتمام عملية البيع";
        return;
      }
      window.location.href = INVOICE_URL_BASE + data.sale_id + "/";
    } catch (err) {
      showCartError("حدث خطأ في الشبكة — يرجى المحاولة مرة أخرى.");
      completeBtn.disabled = false;
      completeBtn.textContent = "إتمام عملية البيع";
    }
  });

  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  renderChips();
  renderGrid();
  renderTicket();
})();
