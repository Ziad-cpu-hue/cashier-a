"""
Makes the count of soon-due/overdue installment plans AND soon-due investor
dividends available to every template, so the sidebar badge covers both
without every view having to remember to compute it.
"""

from django.utils import timezone


def installment_alerts(request):
    try:
        from .models import InstallmentPlan, Investor
        cutoff = timezone.now() + timezone.timedelta(days=5)
        installment_count = InstallmentPlan.objects.filter(
            status=InstallmentPlan.ACTIVE,
            next_due_date__isnull=False,
            next_due_date__lte=cutoff,
        ).count()
        investor_count = sum(
            1 for inv in Investor.objects.filter(status=Investor.ACTIVE, dividends_due__gt=0)
            if inv.days_until_dividend_due is not None and inv.days_until_dividend_due <= 5
        )
        count = installment_count + investor_count
    except Exception:
        # During initial migrations the tables may not exist yet.
        count = 0
    return {"nav_alerts_count": count}
