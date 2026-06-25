from django.contrib import admin
from .models import Tenant, TenantUser, Service, StaffMember, Availability, SubscriptionPlan, TenantSubscription


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owner", "is_active", "created_at")
    search_fields = ("name", "slug")


@admin.register(TenantUser)
class TenantUserAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant", "role")


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "duration_minutes", "price", "is_active")


@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "is_active")


@admin.register(Availability)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ("staff", "day_of_week", "start_time", "end_time", "is_active")


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("display_name", "name", "price_monthly", "max_staff", "max_branches")


@admin.register(TenantSubscription)
class TenantSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("tenant", "plan", "status", "started_at", "expires_at")
    list_filter = ("status", "plan")
