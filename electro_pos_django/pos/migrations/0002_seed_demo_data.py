"""
Seeds a handful of realistic electrical-appliance products and one demo
customer, so the system is immediately explorable after `migrate` instead
of opening to an empty shell. Safe to run more than once (it checks first).
"""

from django.db import migrations


def seed_data(apps, schema_editor):
    Product = apps.get_model("pos", "Product")
    Customer = apps.get_model("pos", "Customer")

    if Product.objects.exists():
        return

    Product.objects.bulk_create([
        Product(name="ثلاجة 18 قدم نو فروست", barcode="6291041234561",
                category="ثلاجات", price=10000, cost_price=8200,
                quantity=5, low_stock_threshold=2, warranty_months=24),
        Product(name="غسالة أوتوماتيك 9 كيلو", barcode="6291041234578",
                category="غسالات", price=7500, cost_price=6100,
                quantity=8, low_stock_threshold=2, warranty_months=12),
        Product(name='تلفاز LED سمارت 55 بوصة', barcode="6291041234585",
                category="تلفزيونات", price=12500, cost_price=10400,
                quantity=6, low_stock_threshold=2, warranty_months=12),
        Product(name="تكييف سبليت 1.5 حصان", barcode="6291041234592",
                category="تكييفات", price=15800, cost_price=13000,
                quantity=4, low_stock_threshold=2, warranty_months=18),
        Product(name="ميكروويف 25 لتر", barcode="6291041234608",
                category="أجهزة صغيرة", price=2400, cost_price=1850,
                quantity=12, low_stock_threshold=3, warranty_months=6),
        Product(name="سخان مياه كهربائي 50 لتر", barcode="6291041234615",
                category="سخانات", price=3200, cost_price=2500,
                quantity=2, low_stock_threshold=2, warranty_months=12),
    ])

    Customer.objects.create(
        name="أحمد مصطفى", phone="01012345678", address="الفيوم، مصر"
    )


def unseed_data(apps, schema_editor):
    Product = apps.get_model("pos", "Product")
    Customer = apps.get_model("pos", "Customer")
    Product.objects.filter(barcode__startswith="629104123").delete()
    Customer.objects.filter(name="أحمد مصطفى").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_data, unseed_data),
    ]
