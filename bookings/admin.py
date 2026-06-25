from django.contrib import admin
from .models import Appointment, Review, LeaveRequest, WaitingList


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("customer_name", "service", "staff", "date", "start_time", "status", "tenant")
    list_filter = ("status", "date", "tenant")
    search_fields = ("customer_name", "customer_phone", "customer_email")


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("appointment", "rating", "created_at")


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("staff", "start_date", "end_date", "status")
    list_filter = ("status",)


@admin.register(WaitingList)
class WaitingListAdmin(admin.ModelAdmin):
    list_display = ("customer_name", "service", "date", "tenant", "notified", "created_at")
    list_filter = ("notified", "date")
