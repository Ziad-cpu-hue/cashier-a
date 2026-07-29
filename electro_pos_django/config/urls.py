from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("django-admin/", admin.site.urls),   # Django's built-in admin (optional, superuser-only)
    path("", include("pos.urls")),
]
