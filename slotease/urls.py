from django.contrib import admin
from django.urls import path, include
from tenants import views as tenant_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", tenant_views.landing, name="landing"),
    path("register/", tenant_views.register, name="register"),
    path("staff-login/", tenant_views.staff_login_view, name="staff_login"),
    path("", include("django.contrib.auth.urls")),
    path("dashboard/", include("tenants.dashboard_urls")),
    path("", include("bookings.urls")),  # tenant-slug routes last
]
