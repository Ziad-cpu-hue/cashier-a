from django.urls import path
from . import views

app_name = "pos"

urlpatterns = [
    path("", views.home, name="home"),

    # Cashier / point-of-sale
    path("cashier/", views.cashier, name="cashier"),
    path("api/products/search/", views.api_product_search, name="api_product_search"),
    path("api/sale/", views.api_create_sale, name="api_create_sale"),
    path("invoice/<int:sale_id>/", views.invoice, name="invoice"),

    # Management console
    path("manage/", views.dashboard, name="dashboard"),
    path("manage/products/", views.products_list, name="products_list"),
    path("manage/products/new/", views.product_new, name="product_new"),
    path("manage/products/<int:product_id>/edit/", views.product_edit, name="product_edit"),
    path("manage/products/<int:product_id>/delete/", views.product_delete, name="product_delete"),
    path("manage/inventory/", views.inventory, name="inventory"),
    path("manage/inventory/<int:product_id>/restock/", views.restock, name="restock"),
    path("manage/customers/", views.customers_list, name="customers_list"),
    path("manage/customers/new/", views.customer_new, name="customer_new"),
    path("manage/customers/<int:customer_id>/", views.customer_detail, name="customer_detail"),
    path("manage/customers/<int:customer_id>/delete/", views.customer_delete, name="customer_delete"),
    path("manage/installments/<int:plan_id>/pay/", views.installment_pay, name="installment_pay"),
    path("manage/installments/payments/<int:payment_id>/receipt/", views.installment_payment_receipt, name="installment_payment_receipt"),
    path("manage/alerts/", views.alerts_list, name="alerts_list"),
    path("manage/warranties/", views.warranties_list, name="warranties_list"),
    path("manage/reports/", views.reports, name="reports"),

    # Investor management
    path("manage/investors/", views.investors_list, name="investors_list"),
    path("manage/investors/new/", views.investor_new, name="investor_new"),
    path("manage/investors/<int:investor_id>/", views.investor_detail, name="investor_detail"),
    path("manage/investors/<int:investor_id>/add-capital/", views.investor_add_capital, name="investor_add_capital"),
    path("manage/investors/<int:investor_id>/withdraw/", views.investor_withdraw, name="investor_withdraw"),
    path("manage/investors/<int:investor_id>/pay-dividend/", views.investor_pay_dividend, name="investor_pay_dividend"),
    path("manage/investors/<int:investor_id>/edit/", views.investor_edit, name="investor_edit"),
    path("manage/investors/<int:investor_id>/delete/", views.investor_delete, name="investor_delete"),
    path("manage/expenses/", views.expenses_list, name="expenses_list"),
    path("manage/expenses/new/", views.expense_new, name="expense_new"),
    path("manage/expenses/<int:expense_id>/delete/", views.expense_delete, name="expense_delete"),
    path("manage/distributions/", views.distributions_list, name="distributions_list"),
    path("manage/distributions/new/", views.distribution_new, name="distribution_new"),
    path("manage/distributions/<int:distribution_id>/", views.distribution_detail, name="distribution_detail"),
]
