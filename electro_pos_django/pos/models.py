"""
Data model for Electro POS.

Money fields use DecimalField (not float) since this is real financial data —
Decimal avoids the rounding drift that binary floating point introduces over
many additions/subtractions (invoice totals, installment balances, etc).
"""

from decimal import Decimal

from django.db import models
from django.utils import timezone
from dateutil.relativedelta import relativedelta


class Product(models.Model):
    name = models.CharField(max_length=200)
    barcode = models.CharField(max_length=64, unique=True, null=True, blank=True)
    category = models.CharField(max_length=100, default="عام")
    price = models.DecimalField(max_digits=12, decimal_places=2)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantity = models.IntegerField(default=0)
    low_stock_threshold = models.IntegerField(default=3)
    warranty_months = models.IntegerField(default=12)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_low_stock(self):
        return 0 < self.quantity <= self.low_stock_threshold

    @property
    def is_out_of_stock(self):
        return self.quantity <= 0

    def as_dict(self):
        """Plain-dict representation used to feed the cashier screen's JS."""
        return {
            "id": self.id,
            "name": self.name,
            "barcode": self.barcode or "",
            "category": self.category,
            "price": float(self.price),
            "cost_price": float(self.cost_price),
            "quantity": self.quantity,
            "low_stock_threshold": self.low_stock_threshold,
            "warranty_months": self.warranty_months,
        }


class Customer(models.Model):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=40, blank=True, default="")
    address = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["phone"],
                condition=~models.Q(phone=""),
                name="unique_customer_phone_when_set",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def total_due(self):
        total = self.installment_plans.filter(status="active").aggregate(
            models.Sum("remaining_amount")
        )["remaining_amount__sum"]
        return total or 0

    def as_dict(self):
        return {"id": self.id, "name": self.name, "phone": self.phone or ""}


class Sale(models.Model):
    CASH = "cash"
    INSTALLMENT = "installment"
    PAYMENT_METHOD_CHOICES = [(CASH, "Cash"), (INSTALLMENT, "Installment")]

    STATUS_COMPLETED = "completed"
    STATUS_PARTIAL = "partially_paid"
    STATUS_PAID_OFF = "paid_off"
    STATUS_CHOICES = [
        (STATUS_COMPLETED, "Completed"),
        (STATUS_PARTIAL, "Partially Paid"),
        (STATUS_PAID_OFF, "Paid Off"),
    ]

    invoice_number = models.CharField(max_length=32, unique=True)
    customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="sales"
    )
    sale_date = models.DateTimeField(default=timezone.now)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remaining_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_COMPLETED)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.invoice_number

    @staticmethod
    def next_invoice_number():
        count = Sale.objects.count() + 1
        return f"INV-{count:06d}"


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, null=True, on_delete=models.SET_NULL, related_name="+")
    product_name = models.CharField(max_length=200)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantity = models.IntegerField()
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    serial_number = models.CharField(max_length=120, blank=True, default="")
    warranty_months = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.product_name} x{self.quantity}"


class InstallmentPlan(models.Model):
    ACTIVE = "active"
    CLOSED = "closed"
    STATUS_CHOICES = [(ACTIVE, "Active"), (CLOSED, "Closed")]

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="installment_plan")
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="installment_plans")
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    down_payment = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remaining_amount = models.DecimalField(max_digits=12, decimal_places=2)
    monthly_amount = models.DecimalField(max_digits=12, decimal_places=2)
    num_months = models.IntegerField()
    start_date = models.DateTimeField(default=timezone.now)
    next_due_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"Plan #{self.id} for {self.customer}"

    @property
    def days_until_due(self):
        """Positive = days remaining, 0 = due today, negative = overdue by that many days."""
        if not self.next_due_date:
            return None
        return (self.next_due_date.date() - timezone.localdate()).days


class InstallmentPayment(models.Model):
    plan = models.ForeignKey(InstallmentPlan, on_delete=models.CASCADE, related_name="payments")
    payment_date = models.DateTimeField(default=timezone.now)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-payment_date"]

    def __str__(self):
        return f"{self.amount} on {self.payment_date:%Y-%m-%d}"


class Warranty(models.Model):
    sale_item = models.ForeignKey(SaleItem, on_delete=models.CASCADE, related_name="warranty")
    product_name = models.CharField(max_length=200)
    serial_number = models.CharField(max_length=120)
    customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="warranties"
    )
    warranty_months = models.IntegerField()
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.product_name} · {self.serial_number}"

    @property
    def is_active(self):
        return self.end_date >= timezone.now()

    @staticmethod
    def compute_end_date(start_date, months):
        return start_date + relativedelta(months=months)


# =============================================================================
# INVESTOR MANAGEMENT
#
# Deliberately NOT tied to individual sales. The chain is always:
#   sales revenue -> minus cost of goods sold -> minus operating expenses
#   -> net profit/loss -> split across investors by capital share.
# A ProfitDistribution is the one place that computation happens; investors
# only ever see the result of it, never a cut of a single invoice.
# =============================================================================

class Investor(models.Model):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"
    DISTRIBUTION_CHOICES = [
        (MONTHLY, "شهري"),
        (QUARTERLY, "كل 3 أشهر"),
        (SEMI_ANNUAL, "كل 6 أشهر"),
        (ANNUAL, "سنوي"),
    ]
    DISTRIBUTION_MONTHS = {MONTHLY: 1, QUARTERLY: 3, SEMI_ANNUAL: 6, ANNUAL: 12}

    ACTIVE = "active"
    WITHDRAWN = "withdrawn"
    STATUS_CHOICES = [(ACTIVE, "نشط"), (WITHDRAWN, "منسحب")]

    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=40, blank=True, default="")
    address = models.CharField(max_length=255, blank=True, default="")
    join_date = models.DateTimeField(default=timezone.now)

    current_capital = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    dividends_due = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_profit_earned = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_loss_borne = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    last_dividend_payment_date = models.DateTimeField(null=True, blank=True)

    distribution_method = models.CharField(max_length=20, choices=DISTRIBUTION_CHOICES, default=MONTHLY)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE)
    notes = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-current_capital"]

    def __str__(self):
        return self.name

    @staticmethod
    def total_active_capital():
        return Investor.objects.filter(status=Investor.ACTIVE).aggregate(
            t=models.Sum("current_capital")
        )["t"] or Decimal("0")

    @property
    def ownership_percentage(self):
        if self.status != Investor.ACTIVE or self.current_capital <= 0:
            return Decimal("0")
        total = Investor.total_active_capital()
        if total <= 0:
            return Decimal("0")
        return (self.current_capital / total) * 100

    @property
    def next_dividend_due_date(self):
        """When this investor's next payout is expected, based on their own
        chosen frequency — only meaningful while they're owed money."""
        if self.status != Investor.ACTIVE or self.dividends_due <= 0:
            return None
        base = self.last_dividend_payment_date or self.join_date
        months = Investor.DISTRIBUTION_MONTHS[self.distribution_method]
        return base + relativedelta(months=months)

    @property
    def days_until_dividend_due(self):
        d = self.next_dividend_due_date
        if not d:
            return None
        return (d.date() - timezone.localdate()).days


class InvestorTransaction(models.Model):
    INVESTMENT = "investment"
    ADDITION = "addition"
    WITHDRAWAL = "withdrawal"
    PROFIT = "profit"
    LOSS = "loss"
    DIVIDEND_PAYMENT = "dividend_payment"
    TYPE_CHOICES = [
        (INVESTMENT, "استثمار أولي"),
        (ADDITION, "إضافة استثمار"),
        (WITHDRAWAL, "سحب"),
        (PROFIT, "ربح"),
        (LOSS, "خسارة"),
        (DIVIDEND_PAYMENT, "دفع أرباح مستحقة"),
    ]

    investor = models.ForeignKey(Investor, on_delete=models.CASCADE, related_name="transactions")
    date = models.DateTimeField(default=timezone.now)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.get_type_display()} — {self.amount}"


class Expense(models.Model):
    SALARIES = "salaries"
    ELECTRICITY = "electricity"
    RENT = "rent"
    TRANSPORTATION = "transportation"
    MAINTENANCE = "maintenance"
    TAXES = "taxes"
    OTHER = "other"
    CATEGORY_CHOICES = [
        (SALARIES, "رواتب"),
        (ELECTRICITY, "كهرباء"),
        (RENT, "إيجار"),
        (TRANSPORTATION, "مواصلات"),
        (MAINTENANCE, "صيانة"),
        (TAXES, "ضرائب"),
        (OTHER, "أخرى"),
    ]

    date = models.DateTimeField(default=timezone.now)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=OTHER)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.get_category_display()} — {self.amount}"


class ProfitDistribution(models.Model):
    DEDUCT_FROM_CAPITAL = "deduct_from_capital"
    RECORD_ONLY = "record_only"
    OWNER_BEARS = "owner_bears"
    LOSS_POLICY_CHOICES = [
        (DEDUCT_FROM_CAPITAL, "تُخصم من رأس مال المستثمر"),
        (RECORD_ONLY, "تُسجَّل فقط دون خصم (تُعوَّض من أرباح لاحقة)"),
        (OWNER_BEARS, "يتحملها صاحب المشروع بالكامل"),
    ]

    period_start = models.DateTimeField()
    period_end = models.DateTimeField()

    total_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_cogs = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_expenses = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_profit = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    loss_policy = models.CharField(max_length=20, choices=LOSS_POLICY_CHOICES, blank=True, default="")
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_end", "-id"]

    def __str__(self):
        return f"{self.period_start:%Y-%m-%d} → {self.period_end:%Y-%m-%d}"

    @property
    def gross_profit(self):
        return self.total_revenue - self.total_cogs

    @property
    def is_loss(self):
        return self.net_profit < 0


class InvestorDistributionShare(models.Model):
    distribution = models.ForeignKey(ProfitDistribution, on_delete=models.CASCADE, related_name="shares")
    investor = models.ForeignKey(
        Investor, null=True, blank=True, on_delete=models.SET_NULL, related_name="distribution_shares"
    )
    investor_name_snapshot = models.CharField(max_length=200, blank=True, default="")
    ownership_percentage_snapshot = models.DecimalField(max_digits=6, decimal_places=2)
    share_amount = models.DecimalField(max_digits=14, decimal_places=2)  # + profit, - loss
    capital_before = models.DecimalField(max_digits=14, decimal_places=2)
    capital_after = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["-share_amount"]

    def __str__(self):
        return f"{self.display_name}: {self.share_amount}"

    @property
    def display_name(self):
        """The investor's name even after their record has been deleted."""
        return self.investor.name if self.investor else (self.investor_name_snapshot or "مستثمر محذوف")
