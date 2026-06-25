import csv
import json
from collections import defaultdict
from datetime import timedelta, date as date_cls
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
from django.db import transaction
from django.db.models import Avg, Count, ProtectedError, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import DeleteView, FormView, ListView, TemplateView

from bookings.models import Appointment, LeaveRequest, Review, WaitingList
from .forms import AvailabilityForm, LeaveRequestForm, RegisterForm, ServiceForm, StaffForm
from .mixins import ManageRoleRequiredMixin, TenantRequiredMixin, subscription_allows_staff, subscription_allows_feature
from .models import Availability, Service, StaffMember, Tenant, TenantUser, SubscriptionPlan, TenantSubscription


def landing(request):
    tenants = Tenant.objects.filter(is_active=True).order_by("-created_at")[:50]
    return render(request, "public/landing.html", {"tenants": tenants})


def staff_login_view(request):
    """Dedicated login page for staff members — same auth, styled differently."""
    from django.contrib.auth import authenticate, login as auth_login
    from django.contrib.auth.forms import AuthenticationForm
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            auth_login(request, user)
            return redirect(request.GET.get("next", "dashboard"))
    else:
        form = AuthenticationForm(request)
    return render(request, "registration/staff_login.html", {"form": form})


class RegisterView(FormView):
    template_name = "registration/register.html"
    form_class = RegisterForm

    def form_valid(self, form):
        with transaction.atomic():
            user = form.save()
            tenant = Tenant.objects.create(
                name=form.cleaned_data["business_name"],
                owner=user,
                phone=form.cleaned_data.get("phone", ""),
                address=form.cleaned_data.get("address", ""),
            )
            TenantUser.objects.create(tenant=tenant, user=user, role="owner")
            # Auto-assign free plan on registration
            free_plan = SubscriptionPlan.objects.filter(name="free").first()
            if free_plan:
                import datetime as dt
                TenantSubscription.objects.create(
                    tenant=tenant,
                    plan=free_plan,
                    status="active",
                    expires_at=None,  # Free plan never expires
                )
        login(self.request, user)
        return redirect("dashboard")


register = RegisterView.as_view()


class DashboardView(TenantRequiredMixin, TemplateView):
    template_name = "dashboard/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        week_ago = today - timedelta(days=7)
        qs = Appointment.objects.filter(tenant=self.tenant)
        revenue = sum((a.service.price for a in qs.filter(status="completed")), Decimal("0"))

        # Subscription info
        sub = getattr(self.tenant, 'subscription', None)
        ctx['current_sub'] = sub

        # Staff portal: if user is staff role, filter to their own appointments
        if self.role == "staff":
            staff_member = StaffMember.objects.filter(
                tenant=self.tenant, user=self.request.user
            ).first()
            if staff_member:
                qs_staff = Appointment.objects.filter(
                    tenant=self.tenant, staff=staff_member
                )
                ctx.update({
                    "is_staff_view": True,
                    "staff_member": staff_member,
                    "today_appts": qs_staff.filter(date=today).select_related("service", "staff").order_by("start_time"),
                    "upcoming_appts": qs_staff.filter(
                        date__gt=today, status__in=["pending", "confirmed"]
                    ).select_related("service", "staff").order_by("date", "start_time")[:10],
                    "leave_requests": staff_member.leave_requests.all().order_by("-created_at")[:5],
                })

        ctx.update({
            "today_count": qs.filter(date=today).count(),
            "week_count": qs.filter(date__gte=week_ago).count(),
            "revenue": revenue,
            "recent": qs.select_related("service", "staff").order_by("-created_at")[:10],
        })
        return ctx


dashboard = DashboardView.as_view()


# -----------------------------------------------------------------------
# Staff portal: mark appointment completed, request leave
# -----------------------------------------------------------------------
class StaffMarkCompletedView(TenantRequiredMixin, View):
    def post(self, request, pk):
        staff_member = None
        if self.role == "staff":
            staff_member = StaffMember.objects.filter(
                tenant=self.tenant, user=request.user
            ).first()
        appt = get_object_or_404(
            Appointment, pk=pk, tenant=self.tenant,
            **({} if self.role in ("owner", "manager") else {"staff": staff_member})
        )
        if appt.status in ("confirmed", "pending"):
            appt.status = "completed"
            appt.save(update_fields=["status"])
            messages.success(request, f"Appointment for {appt.customer_name} marked as completed.")
        next_url = request.POST.get("next", "dashboard")
        return redirect(next_url)


staff_mark_completed = StaffMarkCompletedView.as_view()


class StaffLeaveRequestView(TenantRequiredMixin, View):
    def get(self, request):
        staff_member = StaffMember.objects.filter(
            tenant=self.tenant, user=request.user
        ).first()
        if not staff_member:
            messages.error(request, "No staff profile found for your account.")
            return redirect("dashboard")
        form = LeaveRequestForm()
        pending = staff_member.leave_requests.all().order_by("-created_at")
        return render(request, "dashboard/leave_request.html", {
            "form": form, "leave_requests": pending,
            "tenant": self.tenant, "role": self.role,
        })

    def post(self, request):
        staff_member = StaffMember.objects.filter(
            tenant=self.tenant, user=request.user
        ).first()
        if not staff_member:
            return redirect("dashboard")
        form = LeaveRequestForm(request.POST)
        if form.is_valid():
            lr = form.save(commit=False)
            lr.staff = staff_member
            lr.save()
            messages.success(request, "Leave request submitted.")
            return redirect("leave_request")
        pending = staff_member.leave_requests.all().order_by("-created_at")
        return render(request, "dashboard/leave_request.html", {
            "form": form, "leave_requests": pending,
            "tenant": self.tenant, "role": self.role,
        })


staff_leave_request = StaffLeaveRequestView.as_view()


class LeaveApprovalView(ManageRoleRequiredMixin, View):
    def post(self, request, pk):
        lr = get_object_or_404(LeaveRequest, pk=pk, staff__tenant=self.tenant)
        new_status = request.POST.get("status")
        if new_status in ("approved", "rejected"):
            lr.status = new_status
            lr.save(update_fields=["status"])
            messages.success(request, f"Leave request {new_status}.")
        return redirect("leave_approvals")


leave_approval = LeaveApprovalView.as_view()


class LeaveApprovalListView(ManageRoleRequiredMixin, ListView):
    template_name = "dashboard/leave_approvals.html"
    context_object_name = "leave_requests"

    def get_queryset(self):
        return LeaveRequest.objects.filter(
            staff__tenant=self.tenant
        ).select_related("staff").order_by("-created_at")


leave_approvals = LeaveApprovalListView.as_view()


# -----------------------------------------------------------------------
# Analytics dashboard
# -----------------------------------------------------------------------
class AnalyticsView(ManageRoleRequiredMixin, View):
    def get(self, request):
        # Feature gate: advanced analytics requires pro+
        has_advanced = subscription_allows_feature(self.tenant, "advanced_analytics")

        period = request.GET.get("period", "monthly")
        today = timezone.localdate()

        if period == "daily":
            start = today - timedelta(days=29)
            labels, booking_data, revenue_data = [], [], []
            for i in range(30):
                d = start + timedelta(days=i)
                appts = Appointment.objects.filter(tenant=self.tenant, date=d)
                labels.append(d.strftime("%b %d"))
                booking_data.append(appts.count())
                revenue_data.append(float(
                    sum((a.service.price for a in appts.filter(status="completed")), Decimal("0"))
                ))
        elif period == "weekly":
            labels, booking_data, revenue_data = [], [], []
            for i in range(11, -1, -1):
                week_end = today - timedelta(days=i * 7)
                week_start = week_end - timedelta(days=6)
                appts = Appointment.objects.filter(
                    tenant=self.tenant, date__gte=week_start, date__lte=week_end
                )
                labels.append(f"W/{week_end.strftime('%b %d')}")
                booking_data.append(appts.count())
                revenue_data.append(float(
                    sum((a.service.price for a in appts.filter(status="completed")), Decimal("0"))
                ))
        else:
            labels, booking_data, revenue_data = [], [], []
            for i in range(11, -1, -1):
                month_date = date_cls(today.year, today.month, 1)
                total_months = month_date.month - 1 - i
                year = month_date.year + total_months // 12
                month = total_months % 12 + 1
                if month <= 0:
                    month += 12
                    year -= 1
                appts = Appointment.objects.filter(
                    tenant=self.tenant, date__year=year, date__month=month,
                )
                import calendar
                labels.append(f"{calendar.month_abbr[month]} {year}")
                booking_data.append(appts.count())
                revenue_data.append(float(
                    sum((a.service.price for a in appts.filter(status="completed")), Decimal("0"))
                ))

        service_qs = (
            Appointment.objects.filter(tenant=self.tenant)
            .values("service__name")
            .annotate(count=Count("id"))
            .order_by("-count")[:8]
        )
        service_labels = [s["service__name"] for s in service_qs]
        service_counts = [s["count"] for s in service_qs]

        total = Appointment.objects.filter(tenant=self.tenant).count()
        cancelled = Appointment.objects.filter(tenant=self.tenant, status="cancelled").count()
        cancel_rate = round((cancelled / total * 100) if total else 0, 1)

        from django.db.models import Count as DjCount
        repeat_count = (
            Appointment.objects.filter(tenant=self.tenant)
            .values("customer_phone")
            .annotate(cnt=DjCount("id"))
            .filter(cnt__gt=1)
            .count()
        )

        staff_perf = []
        for sm in StaffMember.objects.filter(tenant=self.tenant, is_active=True):
            avg = Review.objects.filter(
                appointment__staff=sm, appointment__tenant=self.tenant
            ).aggregate(avg=Avg("rating"))["avg"]
            appt_count = Appointment.objects.filter(
                tenant=self.tenant, staff=sm, status="completed"
            ).count()
            staff_perf.append({
                "name": sm.name,
                "avg_rating": round(avg, 1) if avg else None,
                "completed": appt_count,
            })

        overall_avg = Review.objects.filter(
            appointment__tenant=self.tenant
        ).aggregate(avg=Avg("rating"))["avg"]

        ctx = {
            "tenant": self.tenant,
            "role": self.role,
            "period": period,
            "has_advanced": has_advanced,
            "labels_json": json.dumps(labels),
            "booking_data_json": json.dumps(booking_data),
            "revenue_data_json": json.dumps(revenue_data),
            "service_labels_json": json.dumps(service_labels),
            "service_counts_json": json.dumps(service_counts),
            "cancel_rate": cancel_rate,
            "repeat_count": repeat_count,
            "total_bookings": total,
            "staff_perf": staff_perf,
            "overall_avg": round(overall_avg, 1) if overall_avg else None,
        }
        return render(request, "dashboard/analytics.html", ctx)


analytics = AnalyticsView.as_view()


# -----------------------------------------------------------------------
# Reviews management (owner replies)
# -----------------------------------------------------------------------
class ReviewsListView(ManageRoleRequiredMixin, ListView):
    template_name = "dashboard/reviews.html"
    context_object_name = "reviews"

    def get_queryset(self):
        return Review.objects.filter(
            appointment__tenant=self.tenant
        ).select_related("appointment__staff", "appointment__service").order_by("-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        avg = self.get_queryset().aggregate(avg=Avg("rating"))["avg"]
        ctx["overall_avg"] = round(avg, 1) if avg else None
        return ctx


reviews_list = ReviewsListView.as_view()


class ReviewReplyView(ManageRoleRequiredMixin, View):
    def post(self, request, pk):
        review = get_object_or_404(Review, pk=pk, appointment__tenant=self.tenant)
        reply = request.POST.get("owner_reply", "").strip()
        if reply:
            review.owner_reply = reply
            review.save(update_fields=["owner_reply"])
        return redirect("reviews_list")


review_reply = ReviewReplyView.as_view()


# -----------------------------------------------------------------------
# Services CRUD
# -----------------------------------------------------------------------
class SafeDeleteMixin:
    protected_message = "This item can't be deleted because it still has related records."

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        try:
            return super().post(request, *args, **kwargs)
        except ProtectedError:
            messages.error(request, self.protected_message)
            return redirect(self.success_url)


class ServiceListView(TenantRequiredMixin, ListView):
    template_name = "dashboard/services.html"
    context_object_name = "services"

    def get_queryset(self):
        return Service.objects.filter(tenant=self.tenant)


service_list = ServiceListView.as_view()


class ServiceEditView(ManageRoleRequiredMixin, View):
    def get_instance(self, pk):
        if pk is None:
            return None
        return get_object_or_404(Service, pk=pk, tenant=self.tenant)

    def get(self, request, pk=None):
        instance = self.get_instance(pk)
        form = ServiceForm(instance=instance)
        return render(request, "dashboard/service_form.html",
                      {"form": form, "tenant": self.tenant, "instance": instance})

    def post(self, request, pk=None):
        instance = self.get_instance(pk)
        form = ServiceForm(request.POST, instance=instance)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.tenant = self.tenant
            obj.save()
            return redirect("service_list")
        return render(request, "dashboard/service_form.html",
                      {"form": form, "tenant": self.tenant, "instance": instance})


service_edit = ServiceEditView.as_view()


class ServiceDeleteView(SafeDeleteMixin, ManageRoleRequiredMixin, DeleteView):
    model = Service
    template_name = "dashboard/confirm_delete.html"
    success_url = reverse_lazy("service_list")
    protected_message = (
        "This service can't be deleted because it has existing appointments. "
        "Mark it inactive instead, or cancel/complete those appointments first."
    )

    def get_queryset(self):
        return Service.objects.filter(tenant=self.tenant)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["obj"] = self.object
        ctx["kind"] = "Service"
        return ctx


service_delete = ServiceDeleteView.as_view()


# -----------------------------------------------------------------------
# Staff CRUD + availability — with subscription enforcement
# -----------------------------------------------------------------------
class StaffListView(TenantRequiredMixin, ListView):
    template_name = "dashboard/staff.html"
    context_object_name = "staff"

    def get_queryset(self):
        return StaffMember.objects.filter(tenant=self.tenant).prefetch_related(
            "services", "availabilities"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        active_count = StaffMember.objects.filter(tenant=self.tenant, is_active=True).count()
        allowed, max_staff, plan_name = subscription_allows_staff(self.tenant, active_count)
        ctx["can_add_staff"] = allowed
        ctx["max_staff"] = max_staff
        ctx["staff_plan_name"] = plan_name
        ctx["active_staff_count"] = active_count
        return ctx


staff_list = StaffListView.as_view()


class StaffEditView(ManageRoleRequiredMixin, View):
    def get_instance(self, pk):
        if pk is None:
            return None
        return get_object_or_404(StaffMember, pk=pk, tenant=self.tenant)

    def get(self, request, pk=None):
        instance = self.get_instance(pk)
        # Enforce staff limit on new staff creation
        if instance is None:
            active_count = StaffMember.objects.filter(tenant=self.tenant, is_active=True).count()
            allowed, max_staff, plan_name = subscription_allows_staff(self.tenant, active_count)
            if not allowed:
                messages.error(
                    request,
                    f"Your {plan_name} plan allows a maximum of {max_staff} active staff members. "
                    f"Upgrade your plan to add more staff."
                )
                return redirect("staff_list")
        form = StaffForm(instance=instance, tenant=self.tenant)
        return render(request, "dashboard/staff_form.html",
                      {"form": form, "tenant": self.tenant, "instance": instance})

    def post(self, request, pk=None):
        instance = self.get_instance(pk)
        # Enforce staff limit on new creation (not editing existing)
        if instance is None:
            active_count = StaffMember.objects.filter(tenant=self.tenant, is_active=True).count()
            allowed, max_staff, plan_name = subscription_allows_staff(self.tenant, active_count)
            if not allowed:
                messages.error(
                    request,
                    f"Your {plan_name} plan allows a maximum of {max_staff} active staff members."
                )
                return redirect("staff_list")
        form = StaffForm(request.POST, instance=instance, tenant=self.tenant)
        if form.is_valid():
            with transaction.atomic():
                obj = form.save(commit=False)
                obj.tenant = self.tenant
                uname = form.cleaned_data.get("username") or ""
                email = form.cleaned_data.get("email") or ""
                pwd = form.cleaned_data.get("password") or ""
                if uname:
                    if obj.user_id:
                        u = obj.user
                        u.username = uname
                        if email:
                            u.email = email
                        if pwd:
                            u.set_password(pwd)
                        u.save()
                    else:
                        from accounts.models import User
                        u = User.objects.create_user(
                            username=uname, email=email, password=pwd,
                        )
                        obj.user = u
                    # Ensure a TenantUser membership with staff role
                    TenantUser.objects.get_or_create(
                        tenant=self.tenant, user=obj.user,
                        defaults={"role": "staff"},
                    )
                obj.save()
                form.save_m2m()
            messages.success(request, "Staff saved." + (f" Login: {uname}" if uname else ""))
            return redirect("staff_list")
        return render(request, "dashboard/staff_form.html",
                      {"form": form, "tenant": self.tenant, "instance": instance})


staff_edit = StaffEditView.as_view()


class StaffDeleteView(SafeDeleteMixin, ManageRoleRequiredMixin, DeleteView):
    model = StaffMember
    template_name = "dashboard/confirm_delete.html"
    success_url = reverse_lazy("staff_list")
    protected_message = (
        "This staff member can't be deleted because they have existing appointments. "
        "Mark them inactive instead, or cancel/complete those appointments first."
    )

    def get_queryset(self):
        return StaffMember.objects.filter(tenant=self.tenant)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["obj"] = self.object
        ctx["kind"] = "Staff"
        return ctx


staff_delete = StaffDeleteView.as_view()


class AvailabilityEditView(ManageRoleRequiredMixin, View):
    def get(self, request, staff_pk):
        staff = get_object_or_404(StaffMember, pk=staff_pk, tenant=self.tenant)
        form = AvailabilityForm()
        return render(request, "dashboard/availability.html", {
            "tenant": self.tenant, "staff": staff, "form": form,
            "items": staff.availabilities.all(),
        })

    def post(self, request, staff_pk):
        staff = get_object_or_404(StaffMember, pk=staff_pk, tenant=self.tenant)
        form = AvailabilityForm(request.POST)
        if form.is_valid():
            av = form.save(commit=False)
            av.staff = staff
            av.save()
            return redirect("availability_edit", staff_pk=staff.pk)
        return render(request, "dashboard/availability.html", {
            "tenant": self.tenant, "staff": staff, "form": form,
            "items": staff.availabilities.all(),
        })


availability_edit = AvailabilityEditView.as_view()


class AvailabilityDeleteView(ManageRoleRequiredMixin, View):
    def post(self, request, pk):
        av = get_object_or_404(Availability, pk=pk, staff__tenant=self.tenant)
        staff_pk = av.staff.pk
        av.delete()
        return redirect("availability_edit", staff_pk=staff_pk)

    def get(self, request, pk):
        get_object_or_404(Availability, pk=pk, staff__tenant=self.tenant)
        return redirect("staff_list")


availability_delete = AvailabilityDeleteView.as_view()


# -----------------------------------------------------------------------
# Appointments management
# -----------------------------------------------------------------------
class AppointmentListView(TenantRequiredMixin, ListView):
    template_name = "dashboard/appointments.html"
    context_object_name = "appointments"

    def get_queryset(self):
        qs = Appointment.objects.filter(tenant=self.tenant).select_related("service", "staff")
        # Staff can only see their own appointments
        if self.role == "staff":
            staff_member = StaffMember.objects.filter(
                tenant=self.tenant, user=self.request.user
            ).first()
            if staff_member:
                qs = qs.filter(staff=staff_member)
        status = self.request.GET.get("status")
        date = self.request.GET.get("date")
        staff_id = self.request.GET.get("staff")
        if status:
            qs = qs.filter(status=status)
        if date:
            qs = qs.filter(date=date)
        if staff_id and self.role != "staff":
            qs = qs.filter(staff_id=staff_id)
        return qs.order_by("-date", "-start_time")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["staff_list"] = StaffMember.objects.filter(tenant=self.tenant)
        ctx["filters"] = {
            "status": self.request.GET.get("status", ""),
            "date": self.request.GET.get("date", ""),
            "staff": self.request.GET.get("staff", ""),
        }
        return ctx


appointments = AppointmentListView.as_view()


class AppointmentStatusView(ManageRoleRequiredMixin, View):
    def post(self, request, pk):
        appt = get_object_or_404(Appointment, pk=pk, tenant=self.tenant)
        new_status = request.POST.get("status")
        if new_status in dict(Appointment.STATUS_CHOICES):
            appt.status = new_status
            appt.save(update_fields=["status"])
            # Signal will auto-notify waitlist if cancelled
            if new_status == "cancelled" and appt.google_calendar_event_id:
                try:
                    from bookings.google_calendar import delete_calendar_event
                    delete_calendar_event(appt)
                except Exception:
                    pass
            if new_status == "cancelled":
                messages.success(request, "Appointment cancelled. Waiting list has been automatically notified if applicable.")
        return redirect("appointments")


appointment_status = AppointmentStatusView.as_view()


class AppointmentsCsvView(TenantRequiredMixin, View):
    def get(self, request):
        # Feature gate
        if not subscription_allows_feature(self.tenant, "csv_export"):
            messages.error(request, "CSV export requires a Professional or Enterprise plan.")
            return redirect("appointments")
        tenant = self.tenant
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="appointments-{tenant.slug}.csv"'
        w = csv.writer(resp)
        w.writerow(["id", "date", "start_time", "end_time", "service", "staff",
                    "customer_name", "phone", "email", "status", "price"])
        for a in Appointment.objects.filter(tenant=tenant).select_related("service", "staff"):
            w.writerow([a.id, a.date, a.start_time, a.end_time, a.service.name, a.staff.name,
                        a.customer_name, a.customer_phone, a.customer_email, a.status, a.service.price])
        return resp


appointments_csv = AppointmentsCsvView.as_view()


# -----------------------------------------------------------------------
# Staff Portal: Personal Schedule
# -----------------------------------------------------------------------
class StaffScheduleView(TenantRequiredMixin, View):
    def get(self, request):
        staff_member = StaffMember.objects.filter(
            tenant=self.tenant, user=request.user
        ).first()
        if not staff_member:
            messages.error(request, "No staff profile linked to your account.")
            return redirect("dashboard")
        today = timezone.localdate()
        schedule = []
        for i in range(14):
            day = today + timedelta(days=i)
            appts = Appointment.objects.filter(
                tenant=self.tenant, staff=staff_member, date=day
            ).select_related("service").order_by("start_time")
            avail = staff_member.availabilities.filter(
                day_of_week=day.weekday(), is_active=True
            )
            schedule.append({"day": day, "appointments": list(appts), "availability": list(avail)})
        return render(request, "dashboard/staff_schedule.html", {
            "tenant": self.tenant, "role": self.role,
            "staff_member": staff_member, "schedule": schedule, "today": today,
        })


staff_schedule = StaffScheduleView.as_view()


# -----------------------------------------------------------------------
# Subscription plans
# -----------------------------------------------------------------------
class SubscriptionPlansView(TenantRequiredMixin, View):
    def get(self, request):
        plans = SubscriptionPlan.objects.all().order_by("price_monthly")
        current_sub = getattr(self.tenant, "subscription", None)
        active_staff = StaffMember.objects.filter(tenant=self.tenant, is_active=True).count()
        return render(request, "dashboard/subscription.html", {
            "tenant": self.tenant, "role": self.role,
            "plans": plans, "current_sub": current_sub,
            "active_staff": active_staff,
        })


subscription_plans = SubscriptionPlansView.as_view()


class SubscribeView(ManageRoleRequiredMixin, View):
    def post(self, request):
        plan_name = request.POST.get("plan")
        plan = get_object_or_404(SubscriptionPlan, name=plan_name)
        import datetime
        from django.utils import timezone as tz

        # Determine expiry: free plan never expires, paid plans expire in 30 days
        expires = None if plan.price_monthly == 0 else tz.now() + datetime.timedelta(days=30)

        sub, created = TenantSubscription.objects.get_or_create(
            tenant=self.tenant,
            defaults={"plan": plan, "status": "active", "expires_at": expires},
        )
        if not created:
            sub.plan = plan
            sub.status = "active"
            sub.expires_at = expires
            sub.save()
        messages.success(request, f"Successfully subscribed to {plan.display_name}!")
        return redirect("subscription_plans")


subscribe = SubscribeView.as_view()


class CancelSubscriptionView(ManageRoleRequiredMixin, View):
    def post(self, request):
        sub = getattr(self.tenant, "subscription", None)
        if sub and sub.plan.name != "free":
            # Downgrade to free instead of full cancel
            free_plan = SubscriptionPlan.objects.filter(name="free").first()
            if free_plan:
                sub.plan = free_plan
                sub.status = "active"
                sub.expires_at = None
                sub.save()
                messages.success(request, "Subscription cancelled. You've been downgraded to the Free plan.")
        return redirect("subscription_plans")


cancel_subscription = CancelSubscriptionView.as_view()


# -----------------------------------------------------------------------
# Waiting list management (owner/manager view)
# -----------------------------------------------------------------------
class WaitingListManageView(ManageRoleRequiredMixin, ListView):
    template_name = "dashboard/waiting_list.html"
    context_object_name = "waiting_entries"

    def get(self, request, *args, **kwargs):
        # Feature gate: waiting list requires pro+
        if not subscription_allows_feature(self.tenant, "waiting_list"):
            messages.error(request, "The Waiting List feature requires a Professional or Enterprise plan.")
            return redirect("subscription_plans")
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return WaitingList.objects.filter(
            tenant=self.tenant
        ).select_related("service", "staff").order_by("date", "created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["unnotified_count"] = WaitingList.objects.filter(
            tenant=self.tenant, notified=False
        ).count()
        return ctx


waiting_list_manage = WaitingListManageView.as_view()


class WaitingListNotifyView(ManageRoleRequiredMixin, View):
    def post(self, request, pk):
        entry = get_object_or_404(WaitingList, pk=pk, tenant=self.tenant)
        entry.notified = True
        entry.save(update_fields=["notified"])
        messages.success(request, f"Marked {entry.customer_name} as notified.")
        return redirect("waiting_list_manage")


waiting_list_notify = WaitingListNotifyView.as_view()


class WaitingListDeleteView(ManageRoleRequiredMixin, View):
    def post(self, request, pk):
        entry = get_object_or_404(WaitingList, pk=pk, tenant=self.tenant)
        entry.delete()
        messages.success(request, "Waiting list entry removed.")
        return redirect("waiting_list_manage")


waiting_list_delete_entry = WaitingListDeleteView.as_view()
