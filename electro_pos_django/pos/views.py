"""
Views for Electro POS.

The cashier flow (search -> cart -> POST /api/sale/) is the heart of the
system: it validates stock, writes the sale + line items, debits inventory,
opens an installment plan when relevant, and registers a warranty for any
line item that was given a serial number — all inside one atomic transaction.
"""

import json
from decimal import Decimal, InvalidOperation

from dateutil.relativedelta import relativedelta

from django.contrib import messages
from django.db import transaction
from django.db.models import Sum, Q, Count
from django.http import JsonResponse, HttpResponseNotFound
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .models import (
    Product, Customer, Sale, SaleItem,
    InstallmentPlan, InstallmentPayment, Warranty,
    Investor, InvestorTransaction, Expense, ProfitDistribution, InvestorDistributionShare,
)


def _dec(value, default="0"):
    """Safely coerce incoming JSON/form values to Decimal."""
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

def home(request):
    return redirect("pos:cashier")


# ---------------------------------------------------------------------------
# CASHIER SCREEN
# ---------------------------------------------------------------------------

@ensure_csrf_cookie
def cashier(request):
    products = list(Product.objects.all())
    customers = Customer.objects.all()
    products_json = [p.as_dict() for p in products]
    customers_json = [c.as_dict() for c in customers]
    return render(request, "pos/cashier.html", {
        "products": products,
        "products_json": json.dumps(products_json),
        "customers": customers,
        "customers_json": json.dumps(customers_json),
    })


def api_product_search(request):
    q = request.GET.get("q", "").strip()
    qs = Product.objects.all()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(barcode__icontains=q))
    qs = qs.order_by("name")[:20]
    return JsonResponse([p.as_dict() for p in qs], safe=False)


@require_POST
def api_create_sale(request):
    """
    Create a sale from the cashier's cart.
    Expected JSON body:
    {
      "customer_id": int|null,
      "new_customer_name": str|null,
      "new_customer_phone": str|null,
      "payment_method": "cash"|"installment",
      "discount": number,
      "down_payment": number,     (installment only)
      "num_months": int,         (installment only)
      "items": [{"product_id": int, "quantity": int, "serial_number": str}]
    }
    """
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "بيانات الطلب غير صالحة."}, status=400)

    items = data.get("items") or []
    if not items:
        return JsonResponse({"error": "السلة فارغة."}, status=400)

    payment_method = data.get("payment_method", "cash")
    discount = _dec(data.get("discount"))

    try:
        with transaction.atomic():
            # --- Resolve / create customer -----------------------------------
            customer = None
            customer_id = data.get("customer_id")
            new_name = (data.get("new_customer_name") or "").strip()
            if customer_id:
                customer = get_object_or_404(Customer, id=customer_id)
            elif new_name:
                new_phone = (data.get("new_customer_phone") or "").strip()
                if new_phone and Customer.objects.filter(phone=new_phone).exists():
                    return JsonResponse({
                        "error": f"رقم الهاتف {new_phone} مسجّل بالفعل لعميل آخر. ابحث عنه في قائمة العملاء بدلاً من إضافته من جديد."
                    }, status=400)
                customer = Customer.objects.create(name=new_name, phone=new_phone)

            if payment_method == "installment" and not customer:
                return JsonResponse({"error": "عمليات البيع بالتقسيط تتطلب وجود عميل."}, status=400)

            # --- Validate stock & compute totals -------------------------------
            subtotal = Decimal("0")
            resolved = []
            for it in items:
                product = Product.objects.select_for_update().filter(id=it.get("product_id")).first()
                if not product:
                    return JsonResponse({"error": f"المنتج رقم {it.get('product_id')} غير موجود."}, status=400)
                qty = int(it.get("quantity", 1) or 0)
                if qty <= 0:
                    return JsonResponse({"error": f"كمية غير صالحة للمنتج {product.name}."}, status=400)
                if product.quantity < qty:
                    return JsonResponse({
                        "error": f"الكمية غير كافية من '{product.name}'. المتبقي {product.quantity} فقط."
                    }, status=400)
                line_total = product.price * qty
                subtotal += line_total
                resolved.append({
                    "product": product,
                    "qty": qty,
                    "line_total": line_total,
                    "serial_number": (it.get("serial_number") or "").strip(),
                })

            total = max(subtotal - discount, Decimal("0"))

            # --- Installment math -----------------------------------------------
            down_payment = _dec(data.get("down_payment"))
            num_months = int(data.get("num_months") or 0)
            if payment_method == "installment":
                if num_months <= 0:
                    return JsonResponse({"error": "عدد الأشهر يجب أن يكون أكبر من صفر."}, status=400)
                if down_payment > total:
                    return JsonResponse({"error": "الدفعة المقدمة لا يمكن أن تتجاوز الإجمالي."}, status=400)
                remaining = total - down_payment
                paid_amount = down_payment
            else:
                remaining = Decimal("0")
                paid_amount = total

            sale_date = timezone.now()
            status = Sale.STATUS_COMPLETED if payment_method == "cash" else (
                Sale.STATUS_PARTIAL if remaining > 0 else Sale.STATUS_PAID_OFF
            )

            sale = Sale.objects.create(
                invoice_number=Sale.next_invoice_number(),
                customer=customer,
                sale_date=sale_date,
                payment_method=payment_method,
                subtotal=subtotal,
                discount=discount,
                total=total,
                paid_amount=paid_amount,
                remaining_amount=remaining,
                status=status,
            )

            # --- Line items, inventory debit, warranties -------------------------
            for r in resolved:
                p = r["product"]
                item = SaleItem.objects.create(
                    sale=sale,
                    product=p,
                    product_name=p.name,
                    unit_price=p.price,
                    unit_cost=p.cost_price,
                    quantity=r["qty"],
                    line_total=r["line_total"],
                    serial_number=r["serial_number"],
                    warranty_months=p.warranty_months,
                )
                p.quantity -= r["qty"]
                p.save(update_fields=["quantity"])

                if r["serial_number"] and p.warranty_months > 0:
                    end_date = Warranty.compute_end_date(sale_date, p.warranty_months)
                    Warranty.objects.create(
                        sale_item=item,
                        product_name=p.name,
                        serial_number=r["serial_number"],
                        customer=customer,
                        warranty_months=p.warranty_months,
                        start_date=sale_date,
                        end_date=end_date,
                    )

            # --- Installment plan --------------------------------------------------
            if payment_method == "installment":
                monthly_amount = (remaining / num_months) if num_months else Decimal("0")
                monthly_amount = monthly_amount.quantize(Decimal("0.01"))
                is_closed = remaining <= 0
                InstallmentPlan.objects.create(
                    sale=sale,
                    customer=customer,
                    total_amount=total,
                    down_payment=down_payment,
                    remaining_amount=remaining,
                    monthly_amount=monthly_amount,
                    num_months=num_months,
                    start_date=sale_date,
                    next_due_date=None if is_closed else sale_date + relativedelta(months=1),
                    status=InstallmentPlan.CLOSED if is_closed else InstallmentPlan.ACTIVE,
                )

        return JsonResponse({"success": True, "sale_id": sale.id, "invoice_number": sale.invoice_number})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


def invoice(request, sale_id):
    sale = get_object_or_404(Sale, id=sale_id)
    items = sale.items.all()
    plan = sale.installment_plan.first()
    return render(request, "pos/invoice.html", {
        "sale": sale, "items": items, "customer": sale.customer, "plan": plan,
    })


# ---------------------------------------------------------------------------
# MANAGEMENT CONSOLE - DASHBOARD
# ---------------------------------------------------------------------------

def dashboard(request):
    today = timezone.localdate()
    today_sales_qs = Sale.objects.filter(sale_date__date=today)
    today_sales = {
        "c": today_sales_qs.count(),
        "t": today_sales_qs.aggregate(t=Sum("total"))["t"] or 0,
    }
    low_stock = [p for p in Product.objects.all() if p.quantity <= p.low_stock_threshold]
    low_stock.sort(key=lambda p: p.quantity)
    outstanding = InstallmentPlan.objects.filter(status="active").aggregate(
        r=Sum("remaining_amount")
    )["r"] or 0
    recent_sales = Sale.objects.select_related("customer").all()[:8]

    total_products = Product.objects.count()
    healthy_products = total_products - len(low_stock)
    stock_health_pct = round((healthy_products / total_products) * 100) if total_products else 100

    all_plans = InstallmentPlan.objects.all()
    plans_total = all_plans.aggregate(t=Sum("total_amount"))["t"] or 0
    plans_collected = plans_total - outstanding
    collection_pct = round((plans_collected / plans_total) * 100) if plans_total else 100

    alert_cutoff = timezone.now() + timezone.timedelta(days=5)
    due_alerts = (
        InstallmentPlan.objects.filter(
            status=InstallmentPlan.ACTIVE,
            next_due_date__isnull=False,
            next_due_date__lte=alert_cutoff,
        )
        .select_related("customer")
        .order_by("next_due_date")
    )

    investor_alerts = [
        inv for inv in Investor.objects.filter(status=Investor.ACTIVE, dividends_due__gt=0)
        if inv.days_until_dividend_due is not None and inv.days_until_dividend_due <= 5
    ]
    investor_alerts.sort(key=lambda inv: inv.days_until_dividend_due)

    total_capital = Investor.total_active_capital()

    return render(request, "pos/dashboard.html", {
        "product_count": Product.objects.count(),
        "customer_count": Customer.objects.count(),
        "today_sales": today_sales,
        "low_stock": low_stock,
        "outstanding": outstanding,
        "recent_sales": recent_sales,
        "stock_health_pct": stock_health_pct,
        "collection_pct": collection_pct,
        "due_alerts": due_alerts,
        "investor_alerts": investor_alerts,
        "total_capital": total_capital,
        "investor_count": Investor.objects.filter(status=Investor.ACTIVE).count(),
    })


# ---------------------------------------------------------------------------
# MANAGEMENT CONSOLE - PRODUCTS
# ---------------------------------------------------------------------------

def products_list(request):
    products = Product.objects.all()
    return render(request, "pos/products.html", {"products": products})


def _product_from_form(request, instance=None):
    product = instance or Product()
    product.name = request.POST["name"].strip()
    product.barcode = request.POST.get("barcode", "").strip() or None
    product.category = request.POST.get("category", "عام").strip() or "عام"
    product.price = _dec(request.POST.get("price"))
    product.cost_price = _dec(request.POST.get("cost_price"))
    product.quantity = int(request.POST.get("quantity") or 0)
    product.low_stock_threshold = int(request.POST.get("low_stock_threshold") or 3)
    product.warranty_months = int(request.POST.get("warranty_months") or 12)
    return product


def product_new(request):
    if request.method == "POST":
        try:
            product = _product_from_form(request)
            product.save()
            messages.success(request, f"تمت إضافة المنتج '{product.name}' بنجاح.")
            return redirect("pos:products_list")
        except Exception as e:
            messages.error(request, f"تعذّر حفظ المنتج: {e}")
    return render(request, "pos/product_form.html", {"product": None})


def product_edit(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if request.method == "POST":
        try:
            product = _product_from_form(request, instance=product)
            product.save()
            messages.success(request, "تم تحديث المنتج.")
            return redirect("pos:products_list")
        except Exception as e:
            messages.error(request, f"تعذّر تحديث المنتج: {e}")
    return render(request, "pos/product_form.html", {"product": product})


@require_POST
def product_delete(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    product.delete()
    messages.success(request, "تم حذف المنتج.")
    return redirect("pos:products_list")


# ---------------------------------------------------------------------------
# MANAGEMENT CONSOLE - INVENTORY
# ---------------------------------------------------------------------------

def inventory(request):
    products = Product.objects.all().order_by("quantity")
    return render(request, "pos/inventory.html", {"products": products})


@require_POST
def restock(request, product_id):
    amount = int(request.POST.get("amount") or 0)
    if amount > 0:
        product = get_object_or_404(Product, id=product_id)
        product.quantity += amount
        product.save(update_fields=["quantity"])
        messages.success(request, f"تمت إضافة {amount} وحدة إلى المخزون.")
    return redirect("pos:inventory")


# ---------------------------------------------------------------------------
# MANAGEMENT CONSOLE - CUSTOMERS & INSTALLMENTS
# ---------------------------------------------------------------------------

def customers_list(request):
    customers = Customer.objects.all()
    return render(request, "pos/customers.html", {"customers": customers})


@require_POST
def customer_new(request):
    name = request.POST["name"].strip()
    phone = request.POST.get("phone", "").strip()
    address = request.POST.get("address", "").strip()

    if phone and Customer.objects.filter(phone=phone).exists():
        messages.error(request, f"رقم الهاتف {phone} مستخدم بالفعل لعميل آخر. لا يمكن تكرار رقم الهاتف.")
        return redirect("pos:customers_list")

    Customer.objects.create(name=name, phone=phone, address=address)
    messages.success(request, "تمت إضافة العميل.")
    return redirect("pos:customers_list")


def customer_detail(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    plans = customer.installment_plans.all().prefetch_related("payments")
    sales = customer.sales.all()
    warranties = customer.warranties.all()
    active_due = plans.filter(status="active").aggregate(r=Sum("remaining_amount"))["r"] or 0
    return render(request, "pos/customer_detail.html", {
        "customer": customer,
        "plans": plans,
        "sales": sales,
        "warranties": warranties,
        "active_due": active_due,
    })


@require_POST
def customer_delete(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    active_due = customer.installment_plans.filter(status="active").aggregate(
        r=Sum("remaining_amount")
    )["r"] or 0

    if active_due > 0:
        messages.error(
            request,
            f"لا يمكن حذف '{customer.name}' — لا يزال عليه قسط نشط بقيمة {active_due:,.2f} جنيه. "
            "قم بتحصيله بالكامل أولاً.",
        )
        return redirect("pos:customer_detail", customer_id=customer.id)

    name = customer.name
    customer.delete()
    messages.success(
        request,
        f"تم حذف العميل '{name}'. فواتيره وضماناته المسجّلة سابقاً محفوظة في السجلات.",
    )
    return redirect("pos:customers_list")


@require_POST
def installment_pay(request, plan_id):
    plan = get_object_or_404(InstallmentPlan, id=plan_id)
    amount = _dec(request.POST.get("amount"))

    if amount <= 0:
        messages.error(request, "أدخل مبلغ دفعة أكبر من صفر.")
        return redirect("pos:customer_detail", customer_id=plan.customer_id)

    with transaction.atomic():
        new_remaining = max(plan.remaining_amount - amount, Decimal("0"))
        plan.remaining_amount = new_remaining
        plan.status = InstallmentPlan.CLOSED if new_remaining <= 0 else InstallmentPlan.ACTIVE
        if new_remaining <= 0:
            plan.next_due_date = None
        elif plan.next_due_date:
            plan.next_due_date = plan.next_due_date + relativedelta(months=1)
        else:
            plan.next_due_date = timezone.now() + relativedelta(months=1)
        plan.save(update_fields=["remaining_amount", "status", "next_due_date"])

        InstallmentPayment.objects.create(
            plan=plan, amount=amount, note=request.POST.get("note", "")
        )

        sale = plan.sale
        sale.paid_amount += amount
        sale.remaining_amount = new_remaining
        sale.status = Sale.STATUS_PAID_OFF if new_remaining <= 0 else Sale.STATUS_PARTIAL
        sale.save(update_fields=["paid_amount", "remaining_amount", "status"])

    messages.success(request, f"تم تسجيل دفعة بقيمة {amount:,.2f} جنيه.")
    return redirect("pos:customer_detail", customer_id=plan.customer_id)


def installment_payment_receipt(request, payment_id):
    payment = get_object_or_404(InstallmentPayment, id=payment_id)
    plan = payment.plan
    return render(request, "pos/installment_receipt.html", {
        "payment": payment,
        "plan": plan,
        "customer": plan.customer,
        "sale": plan.sale,
    })


def alerts_list(request):
    plans = (
        InstallmentPlan.objects.filter(status=InstallmentPlan.ACTIVE, next_due_date__isnull=False)
        .select_related("customer")
        .order_by("next_due_date")
    )
    investors_due = [
        inv for inv in Investor.objects.filter(status=Investor.ACTIVE, dividends_due__gt=0)
        if inv.next_dividend_due_date is not None
    ]
    investors_due.sort(key=lambda inv: inv.next_dividend_due_date)
    return render(request, "pos/alerts.html", {"plans": plans, "investors_due": investors_due})


# ---------------------------------------------------------------------------
# MANAGEMENT CONSOLE - WARRANTIES
# ---------------------------------------------------------------------------

def warranties_list(request):
    warranties = Warranty.objects.select_related("customer").all()
    return render(request, "pos/warranties.html", {"warranties": warranties})


# ---------------------------------------------------------------------------
# MANAGEMENT CONSOLE - REPORTS
# ---------------------------------------------------------------------------

def reports(request):
    range_days = int(request.GET.get("days", 7))
    since = timezone.now() - timezone.timedelta(days=range_days)

    sales_qs = Sale.objects.filter(sale_date__gte=since)
    sales_count = sales_qs.count()
    total_revenue = sales_qs.aggregate(t=Sum("total"))["t"] or Decimal("0")
    total_cash = sales_qs.filter(payment_method="cash").aggregate(t=Sum("total"))["t"] or Decimal("0")
    total_installment = sales_qs.filter(payment_method="installment").aggregate(t=Sum("total"))["t"] or Decimal("0")

    items_qs = SaleItem.objects.filter(sale__sale_date__gte=since)
    total_profit = Decimal("0")
    for item in items_qs:
        total_profit += (item.unit_price - item.unit_cost) * item.quantity

    best_sellers = (
        items_qs.values("product_name")
        .annotate(units_sold=Sum("quantity"), revenue=Sum("line_total"))
        .order_by("-units_sold")[:10]
    )

    # Group revenue/cash/installment by calendar day (done in Python for sqlite portability)
    by_day = {}
    for s in sales_qs:
        day = timezone.localtime(s.sale_date).strftime("%Y-%m-%d")
        entry = by_day.setdefault(day, {"day": day, "revenue": Decimal("0"), "cash": Decimal("0"), "installment": Decimal("0")})
        entry["revenue"] += s.total
        if s.payment_method == "cash":
            entry["cash"] += s.total
        else:
            entry["installment"] += s.total
    money_by_day = sorted(by_day.values(), key=lambda d: d["day"])

    outstanding_total = InstallmentPlan.objects.filter(status="active").aggregate(
        r=Sum("remaining_amount")
    )["r"] or Decimal("0")

    return render(request, "pos/reports.html", {
        "range_days": range_days,
        "total_revenue": total_revenue,
        "total_cash": total_cash,
        "total_installment": total_installment,
        "total_profit": total_profit,
        "best_sellers": best_sellers,
        "money_by_day": money_by_day,
        "outstanding_total": outstanding_total,
        "sales_count": sales_count,
    })


# ---------------------------------------------------------------------------
# INVESTOR MANAGEMENT
#
# Investors are never linked to individual sales. Their money only moves
# when: (1) they add or withdraw capital directly, or (2) a ProfitDistribution
# is run for a period and splits the store's *net* profit (revenue - COGS -
# operating expenses) across active investors by capital share.
# ---------------------------------------------------------------------------

def investors_list(request):
    investors = Investor.objects.all()
    total_capital = Investor.total_active_capital()
    total_dividends_due = investors.filter(status=Investor.ACTIVE).aggregate(
        t=Sum("dividends_due")
    )["t"] or Decimal("0")
    return render(request, "pos/investors.html", {
        "investors": investors,
        "total_capital": total_capital,
        "total_dividends_due": total_dividends_due,
        "investor_count": investors.filter(status=Investor.ACTIVE).count(),
    })


@require_POST
def investor_new(request):
    name = request.POST.get("name", "").strip()
    phone = request.POST.get("phone", "").strip()
    address = request.POST.get("address", "").strip()
    initial_investment = _dec(request.POST.get("initial_investment"))
    distribution_method = request.POST.get("distribution_method", Investor.MONTHLY)

    if not name:
        messages.error(request, "اسم المستثمر مطلوب.")
        return redirect("pos:investors_list")
    if initial_investment <= 0:
        messages.error(request, "قيمة الاستثمار الأولي يجب أن تكون أكبر من صفر.")
        return redirect("pos:investors_list")

    with transaction.atomic():
        investor = Investor.objects.create(
            name=name, phone=phone, address=address,
            current_capital=initial_investment,
            distribution_method=distribution_method,
        )
        InvestorTransaction.objects.create(
            investor=investor, type=InvestorTransaction.INVESTMENT,
            amount=initial_investment, balance_after=initial_investment,
            note="استثمار أولي عند الانضمام",
        )

    messages.success(request, f"تمت إضافة المستثمر '{name}' برأس مال {initial_investment:,.2f} جنيه.")
    return redirect("pos:investor_detail", investor_id=investor.id)


def investor_detail(request, investor_id):
    investor = get_object_or_404(Investor, id=investor_id)
    txns = investor.transactions.all()
    shares = investor.distribution_shares.select_related("distribution").all()
    return render(request, "pos/investor_detail.html", {
        "investor": investor,
        "transactions": txns,
        "shares": shares,
    })


@require_POST
def investor_delete(request, investor_id):
    investor = get_object_or_404(Investor, id=investor_id)

    if investor.current_capital > 0:
        messages.error(
            request,
            f"لا يمكن حذف '{investor.name}' — لا يزال لديه رأس مال بقيمة "
            f"{investor.current_capital:,.2f} جنيه في المشروع. سجّل سحب المبلغ بالكامل أولاً.",
        )
        return redirect("pos:investor_detail", investor_id=investor.id)

    if investor.dividends_due > 0:
        messages.error(
            request,
            f"لا يمكن حذف '{investor.name}' — لا يزال له أرباح مستحقة غير مدفوعة بقيمة "
            f"{investor.dividends_due:,.2f} جنيه. ادفعها أولاً.",
        )
        return redirect("pos:investor_detail", investor_id=investor.id)

    name = investor.name
    investor.delete()
    messages.success(
        request,
        f"تم حذف المستثمر '{name}'. سجل توزيعات الأرباح السابقة محفوظ باسمه في السجلات.",
    )
    return redirect("pos:investors_list")


@require_POST
def investor_edit(request, investor_id):
    investor = get_object_or_404(Investor, id=investor_id)
    investor.name = request.POST.get("name", investor.name).strip() or investor.name
    investor.phone = request.POST.get("phone", "").strip()
    investor.address = request.POST.get("address", "").strip()
    investor.distribution_method = request.POST.get("distribution_method", investor.distribution_method)
    investor.status = request.POST.get("status", investor.status)
    investor.notes = request.POST.get("notes", "").strip()
    investor.save()
    messages.success(request, "تم تحديث بيانات المستثمر.")
    return redirect("pos:investor_detail", investor_id=investor.id)


@require_POST
def investor_add_capital(request, investor_id):
    investor = get_object_or_404(Investor, id=investor_id)
    amount = _dec(request.POST.get("amount"))
    note = request.POST.get("note", "").strip()

    if amount <= 0:
        messages.error(request, "أدخل مبلغاً أكبر من صفر.")
        return redirect("pos:investor_detail", investor_id=investor.id)

    with transaction.atomic():
        investor.current_capital += amount
        investor.save(update_fields=["current_capital"])
        InvestorTransaction.objects.create(
            investor=investor, type=InvestorTransaction.ADDITION,
            amount=amount, balance_after=investor.current_capital, note=note,
        )

    messages.success(request, f"تمت إضافة {amount:,.2f} جنيه إلى استثمار {investor.name}.")
    return redirect("pos:investor_detail", investor_id=investor.id)


@require_POST
def investor_withdraw(request, investor_id):
    investor = get_object_or_404(Investor, id=investor_id)
    amount = _dec(request.POST.get("amount"))
    note = request.POST.get("note", "").strip()

    if amount <= 0:
        messages.error(request, "أدخل مبلغاً أكبر من صفر.")
        return redirect("pos:investor_detail", investor_id=investor.id)
    if amount > investor.current_capital:
        messages.error(request, f"لا يمكن سحب أكثر من رأس المال الحالي ({investor.current_capital:,.2f} جنيه).")
        return redirect("pos:investor_detail", investor_id=investor.id)

    with transaction.atomic():
        investor.current_capital -= amount
        if investor.current_capital <= 0:
            investor.status = Investor.WITHDRAWN
        investor.save(update_fields=["current_capital", "status"])
        InvestorTransaction.objects.create(
            investor=investor, type=InvestorTransaction.WITHDRAWAL,
            amount=amount, balance_after=investor.current_capital, note=note,
        )

    messages.success(request, f"تم سحب {amount:,.2f} جنيه من استثمار {investor.name}.")
    return redirect("pos:investor_detail", investor_id=investor.id)


@require_POST
def investor_pay_dividend(request, investor_id):
    investor = get_object_or_404(Investor, id=investor_id)

    if investor.dividends_due <= 0:
        messages.error(request, "لا يوجد أرباح مستحقة لهذا المستثمر حالياً.")
        return redirect("pos:investor_detail", investor_id=investor.id)

    amount = investor.dividends_due
    with transaction.atomic():
        InvestorTransaction.objects.create(
            investor=investor, type=InvestorTransaction.DIVIDEND_PAYMENT,
            amount=amount, balance_after=investor.current_capital,
            note="دفع الأرباح المستحقة بالكامل",
        )
        investor.dividends_due = Decimal("0")
        investor.last_dividend_payment_date = timezone.now()
        investor.save(update_fields=["dividends_due", "last_dividend_payment_date"])

    messages.success(request, f"تم دفع {amount:,.2f} جنيه من الأرباح المستحقة لـ {investor.name}.")
    return redirect("pos:investor_detail", investor_id=investor.id)


# ---------------------------------------------------------------------------
# EXPENSES — the operating costs subtracted (alongside COGS) from revenue
# before anything is offered to investors.
# ---------------------------------------------------------------------------

def expenses_list(request):
    expenses = Expense.objects.all()
    this_month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month_total = expenses.filter(date__gte=this_month_start).aggregate(
        t=Sum("amount")
    )["t"] or Decimal("0")
    by_category = (
        expenses.filter(date__gte=this_month_start)
        .values("category")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    return render(request, "pos/expenses.html", {
        "expenses": expenses,
        "this_month_total": this_month_total,
        "by_category": by_category,
    })


@require_POST
def expense_new(request):
    category = request.POST.get("category", Expense.OTHER)
    amount = _dec(request.POST.get("amount"))
    note = request.POST.get("note", "").strip()
    date_str = request.POST.get("date", "").strip()

    if amount <= 0:
        messages.error(request, "أدخل مبلغاً أكبر من صفر.")
        return redirect("pos:expenses_list")

    expense = Expense(category=category, amount=amount, note=note)
    if date_str:
        try:
            naive = timezone.datetime.strptime(date_str, "%Y-%m-%d")
            expense.date = timezone.make_aware(naive)
        except ValueError:
            pass
    expense.save()

    messages.success(request, "تم تسجيل المصروف.")
    return redirect("pos:expenses_list")


@require_POST
def expense_delete(request, expense_id):
    expense = get_object_or_404(Expense, id=expense_id)
    expense.delete()
    messages.success(request, "تم حذف المصروف.")
    return redirect("pos:expenses_list")


# ---------------------------------------------------------------------------
# PROFIT DISTRIBUTION — the one place sales revenue, COGS, and expenses are
# combined into a net profit/loss figure and split across investors.
# ---------------------------------------------------------------------------

def _compute_period_financials(period_start, period_end):
    """Revenue -> minus COGS -> minus operating expenses -> net profit/loss."""
    sales_qs = Sale.objects.filter(sale_date__gte=period_start, sale_date__lt=period_end)
    total_revenue = sales_qs.aggregate(t=Sum("total"))["t"] or Decimal("0")

    items_qs = SaleItem.objects.filter(sale__in=sales_qs)
    total_cogs = Decimal("0")
    for item in items_qs:
        total_cogs += item.unit_cost * item.quantity

    total_expenses = Expense.objects.filter(
        date__gte=period_start, date__lt=period_end
    ).aggregate(t=Sum("amount"))["t"] or Decimal("0")

    gross_profit = total_revenue - total_cogs
    net_profit = gross_profit - total_expenses

    return {
        "total_revenue": total_revenue,
        "total_cogs": total_cogs,
        "total_expenses": total_expenses,
        "gross_profit": gross_profit,
        "net_profit": net_profit,
    }


def distributions_list(request):
    distributions = ProfitDistribution.objects.all()
    return render(request, "pos/distributions.html", {"distributions": distributions})


def distribution_new(request):
    preview = None
    period_start_str = request.GET.get("start", "")
    period_end_str = request.GET.get("end", "")

    if period_start_str and period_end_str:
        try:
            start = timezone.make_aware(timezone.datetime.strptime(period_start_str, "%Y-%m-%d"))
            end = timezone.make_aware(timezone.datetime.strptime(period_end_str, "%Y-%m-%d")) + timezone.timedelta(days=1)
            if end > start:
                financials = _compute_period_financials(start, end)
                active_investors = Investor.objects.filter(status=Investor.ACTIVE)
                total_capital = Investor.total_active_capital()
                breakdown = []
                for inv in active_investors:
                    pct = (inv.current_capital / total_capital * 100) if total_capital > 0 else Decimal("0")
                    breakdown.append({
                        "investor": inv,
                        "pct": pct,
                        "share": financials["net_profit"] * pct / 100,
                    })
                preview = {
                    "period_start": period_start_str,
                    "period_end": period_end_str,
                    **financials,
                    "breakdown": breakdown,
                    "has_investors": active_investors.exists(),
                }
            else:
                messages.error(request, "تاريخ النهاية يجب أن يكون بعد تاريخ البداية.")
        except ValueError:
            messages.error(request, "صيغة التاريخ غير صحيحة.")

    if request.method == "POST":
        start = timezone.make_aware(timezone.datetime.strptime(request.POST["period_start"], "%Y-%m-%d"))
        end = timezone.make_aware(timezone.datetime.strptime(request.POST["period_end"], "%Y-%m-%d")) + timezone.timedelta(days=1)
        loss_policy = request.POST.get("loss_policy", "")
        note = request.POST.get("note", "").strip()

        financials = _compute_period_financials(start, end)
        net_profit = financials["net_profit"]

        with transaction.atomic():
            distribution = ProfitDistribution.objects.create(
                period_start=start, period_end=end - timezone.timedelta(days=1),
                total_revenue=financials["total_revenue"],
                total_cogs=financials["total_cogs"],
                total_expenses=financials["total_expenses"],
                net_profit=net_profit,
                loss_policy=loss_policy if net_profit < 0 else "",
                note=note,
            )

            active_investors = Investor.objects.filter(status=Investor.ACTIVE)
            total_capital = Investor.total_active_capital()

            skip_investor_impact = net_profit < 0 and loss_policy == ProfitDistribution.OWNER_BEARS

            if not skip_investor_impact and total_capital > 0:
                for inv in active_investors:
                    pct = inv.current_capital / total_capital * 100
                    share = (net_profit * pct / 100).quantize(Decimal("0.01"))
                    capital_before = inv.current_capital

                    InvestorDistributionShare.objects.create(
                        distribution=distribution, investor=inv, investor_name_snapshot=inv.name,
                        ownership_percentage_snapshot=pct.quantize(Decimal("0.01")),
                        share_amount=share, capital_before=capital_before,
                        capital_after=capital_before,  # may be adjusted below
                    )

                    if share >= 0:
                        inv.dividends_due += share
                        inv.total_profit_earned += share
                        inv.save(update_fields=["dividends_due", "total_profit_earned"])
                        InvestorTransaction.objects.create(
                            investor=inv, type=InvestorTransaction.PROFIT,
                            amount=share, balance_after=inv.current_capital,
                            note=f"من توزيع الأرباح للفترة {period_start_str} إلى {period_end_str}",
                        )
                    else:
                        loss_amount = -share
                        inv.total_loss_borne += loss_amount
                        if loss_policy == ProfitDistribution.DEDUCT_FROM_CAPITAL:
                            inv.current_capital = max(inv.current_capital - loss_amount, Decimal("0"))
                            inv.save(update_fields=["current_capital", "total_loss_borne"])
                            InvestorDistributionShare.objects.filter(
                                distribution=distribution, investor=inv
                            ).update(capital_after=inv.current_capital)
                        else:
                            inv.save(update_fields=["total_loss_borne"])
                        InvestorTransaction.objects.create(
                            investor=inv, type=InvestorTransaction.LOSS,
                            amount=loss_amount, balance_after=inv.current_capital,
                            note=f"من توزيع الفترة {period_start_str} إلى {period_end_str}",
                        )

        messages.success(
            request,
            f"تم إنشاء توزيع الأرباح للفترة، بصافي {'ربح' if net_profit >= 0 else 'خسارة'} {abs(net_profit):,.2f} جنيه.",
        )
        return redirect("pos:distribution_detail", distribution_id=distribution.id)

    return render(request, "pos/distribution_new.html", {
        "preview": preview,
        "period_start_str": period_start_str,
        "period_end_str": period_end_str,
    })


def distribution_detail(request, distribution_id):
    distribution = get_object_or_404(ProfitDistribution, id=distribution_id)
    shares = distribution.shares.select_related("investor").all()
    return render(request, "pos/distribution_detail.html", {
        "distribution": distribution,
        "shares": shares,
    })
