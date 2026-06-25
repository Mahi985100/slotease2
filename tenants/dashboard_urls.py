from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("analytics/", views.analytics, name="analytics"),
    path("services/", views.service_list, name="service_list"),
    path("services/new/", views.service_edit, name="service_new"),
    path("services/<int:pk>/edit/", views.service_edit, name="service_edit"),
    path("services/<int:pk>/delete/", views.service_delete, name="service_delete"),
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/new/", views.staff_edit, name="staff_new"),
    path("staff/<int:pk>/edit/", views.staff_edit, name="staff_edit"),
    path("staff/<int:pk>/delete/", views.staff_delete, name="staff_delete"),
    path("staff/<int:staff_pk>/availability/", views.availability_edit, name="availability_edit"),
    path("availability/<int:pk>/delete/", views.availability_delete, name="availability_delete"),
    path("appointments/", views.appointments, name="appointments"),
    path("appointments/<int:pk>/status/", views.appointment_status, name="appointment_status"),
    path("appointments/<int:pk>/complete/", views.staff_mark_completed, name="staff_mark_completed"),
    path("appointments/export.csv", views.appointments_csv, name="appointments_csv"),
    path("reviews/", views.reviews_list, name="reviews_list"),
    path("reviews/<int:pk>/reply/", views.review_reply, name="review_reply"),
    path("leave/", views.staff_leave_request, name="leave_request"),
    path("leave/approvals/", views.leave_approvals, name="leave_approvals"),
    path("leave/<int:pk>/approve/", views.leave_approval, name="leave_approval"),
    # Staff portal
    path("my-schedule/", views.staff_schedule, name="staff_schedule"),
    # Subscriptions
    path("subscription/", views.subscription_plans, name="subscription_plans"),
    path("subscription/subscribe/", views.subscribe, name="subscribe"),
    path("subscription/cancel/", views.cancel_subscription, name="cancel_subscription"),
    # Waiting list management
    path("waiting-list/", views.waiting_list_manage, name="waiting_list_manage"),
    path("waiting-list/<int:pk>/notify/", views.waiting_list_notify, name="waiting_list_notify"),
    path("waiting-list/<int:pk>/delete/", views.waiting_list_delete_entry, name="waiting_list_delete_entry"),
]
