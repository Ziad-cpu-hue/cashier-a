from django.contrib import admin
from .models import (
    Product, Customer, Sale, SaleItem,
    InstallmentPlan, InstallmentPayment, Warranty,
    Investor, InvestorTransaction, Expense, ProfitDistribution, InvestorDistributionShare,
)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "cost_price", "quantity", "warranty_months")
    search_fields = ("name", "barcode")
    list_filter = ("category",)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "total_due")
    search_fields = ("name", "phone")


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "customer", "payment_method", "total", "status", "sale_date")
    list_filter = ("payment_method", "status")
    search_fields = ("invoice_number",)
    inlines = [SaleItemInline]


class InstallmentPaymentInline(admin.TabularInline):
    model = InstallmentPayment
    extra = 0


@admin.register(InstallmentPlan)
class InstallmentPlanAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "total_amount", "remaining_amount", "monthly_amount", "status")
    list_filter = ("status",)
    inlines = [InstallmentPaymentInline]


@admin.register(Warranty)
class WarrantyAdmin(admin.ModelAdmin):
    list_display = ("product_name", "serial_number", "customer", "start_date", "end_date")
    search_fields = ("serial_number", "product_name")


class InvestorTransactionInline(admin.TabularInline):
    model = InvestorTransaction
    extra = 0


@admin.register(Investor)
class InvestorAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "current_capital", "ownership_percentage", "dividends_due", "status")
    list_filter = ("status", "distribution_method")
    search_fields = ("name", "phone")
    inlines = [InvestorTransactionInline]


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("category", "amount", "date", "note")
    list_filter = ("category",)


class InvestorDistributionShareInline(admin.TabularInline):
    model = InvestorDistributionShare
    extra = 0


@admin.register(ProfitDistribution)
class ProfitDistributionAdmin(admin.ModelAdmin):
    list_display = ("period_start", "period_end", "total_revenue", "net_profit", "created_at")
    inlines = [InvestorDistributionShareInline]
