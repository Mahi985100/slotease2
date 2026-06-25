from datetime import datetime, timedelta, date as date_cls, time as time_cls

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from tenants.models import Service, StaffMember, Tenant
from .forms import CustomerForm, ReviewForm, OwnerReplyForm, WaitingListForm
from .models import Appointment, Review, WaitingList


def _parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _available_slots(staff, service, day):
    dow = day.weekday()
    windows = staff.availabilities.filter(day_of_week=dow, is_active=True)
    if not windows:
        return []
    dur = timedelta(minutes=service.duration_minutes)
    step = timedelta(minutes=15)
    taken = list(Appointment.objects.filter(
        staff=staff, date=day, status__in=["pending", "confirmed"]
    ).values_list("start_time", "end_time"))

    def overlaps(s, e):
        for ts, te in taken:
            if s < te and ts < e:
                return True
        return False

    slots = []
    for w in windows:
        cur = datetime.combine(day, w.start_time)
        end = datetime.combine(day, w.end_time)
        while cur + dur <= end:
            s_t = cur.time()
            e_t = (cur + dur).time()
            if not overlaps(s_t, e_t):
                slots.append(s_t.strftime("%H:%M"))
            cur += step
    return slots


class BookingWizardView(View):
    def get(self, request, slug):
        tenant = get_object_or_404(Tenant, slug=slug, is_active=True)
        step = request.GET.get("step", "1")
        service_id = request.GET.get("service")
        staff_id = request.GET.get("staff")
        date_str = request.GET.get("date")
        time_str = request.GET.get("time")

        ctx = {"tenant": tenant, "step": step}

        if step == "1":
            ctx["services"] = tenant.services.filter(is_active=True)
            return render(request, "booking/step1_service.html", ctx)

        service = get_object_or_404(Service, pk=service_id, tenant=tenant, is_active=True)
        ctx["service"] = service

        if step == "2":
            ctx["staff_list"] = service.staff.filter(is_active=True, tenant=tenant)
            return render(request, "booking/step2_staff.html", ctx)

        staff = get_object_or_404(StaffMember, pk=staff_id, tenant=tenant, is_active=True)
        ctx["staff"] = staff

        if step == "3":
            day = _parse_date(date_str) if date_str else date_cls.today()
            ctx["day"] = day
            ctx["slots"] = _available_slots(staff, service, day)
            ctx["next_days"] = [date_cls.today() + timedelta(days=i) for i in range(0, 14)]
            return render(request, "booking/step3_datetime.html", ctx)

        day = _parse_date(date_str)
        ctx["day"] = day
        ctx["time"] = time_str

        if step == "4":
            ctx["form"] = CustomerForm()
            return render(request, "booking/step4_customer.html", ctx)

        return redirect(reverse("book", args=[tenant.slug]))

    def post(self, request, slug):
        tenant = get_object_or_404(Tenant, slug=slug, is_active=True)
        service_id = request.GET.get("service")
        staff_id = request.GET.get("staff")
        date_str = request.GET.get("date")
        time_str = request.GET.get("time")

        service = get_object_or_404(Service, pk=service_id, tenant=tenant, is_active=True)
        staff = get_object_or_404(StaffMember, pk=staff_id, tenant=tenant, is_active=True)
        day = _parse_date(date_str)

        ctx = {
            "tenant": tenant, "step": "4", "service": service, "staff": staff,
            "day": day, "time": time_str,
        }

        form = CustomerForm(request.POST)
        if form.is_valid() and day and time_str:
            try:
                h, m = map(int, time_str.split(":"))
                start_t = time_cls(h, m)
                end_dt = datetime.combine(day, start_t) + timedelta(minutes=service.duration_minutes)
                appt = Appointment.book_safely(
                    tenant=tenant, service=service, staff=staff,
                    date=day, start_time=start_t, end_time=end_dt.time(),
                    customer_name=form.cleaned_data["customer_name"],
                    customer_phone=form.cleaned_data["customer_phone"],
                    customer_email=form.cleaned_data.get("customer_email", ""),
                    notes=form.cleaned_data.get("notes", ""),
                    status="pending",
                )
                # Try to add to Google Calendar (silently ignores if not configured)
                try:
                    from .google_calendar import create_calendar_event
                    create_calendar_event(appt)
                except Exception:
                    pass
                return redirect("booking_detail", slug=tenant.slug, pk=appt.pk)
            except ValidationError as e:
                messages.error(request, "; ".join(e.messages))

        ctx["form"] = form
        return render(request, "booking/step4_customer.html", ctx)


book = BookingWizardView.as_view()


class BookingDetailView(View):
    def get(self, request, slug, pk):
        tenant = get_object_or_404(Tenant, slug=slug)
        appt = get_object_or_404(Appointment, pk=pk, tenant=tenant)
        return render(request, "booking/detail.html", {"tenant": tenant, "appt": appt})


booking_detail = BookingDetailView.as_view()


class ReviewView(View):
    """Public view: customer submits a review after a completed appointment."""

    def get(self, request, slug, pk):
        tenant = get_object_or_404(Tenant, slug=slug)
        appt = get_object_or_404(Appointment, pk=pk, tenant=tenant, status="completed")
        if hasattr(appt, "review"):
            return render(request, "booking/review_done.html", {"tenant": tenant, "appt": appt})
        form = ReviewForm()
        return render(request, "booking/review_form.html", {
            "tenant": tenant, "appt": appt, "form": form,
        })

    def post(self, request, slug, pk):
        tenant = get_object_or_404(Tenant, slug=slug)
        appt = get_object_or_404(Appointment, pk=pk, tenant=tenant, status="completed")
        if hasattr(appt, "review"):
            return redirect("booking_detail", slug=slug, pk=pk)
        form = ReviewForm(request.POST)
        if form.is_valid():
            Review.objects.create(
                appointment=appt,
                rating=form.cleaned_data["rating"],
                comment=form.cleaned_data.get("comment", ""),
            )
            messages.success(request, "Thank you for your review!")
            return redirect("booking_detail", slug=slug, pk=pk)
        return render(request, "booking/review_form.html", {
            "tenant": tenant, "appt": appt, "form": form,
        })


review_view = ReviewView.as_view()


class WaitingListView(View):
    """Public view: customer joins waiting list when slots are full."""

    def get(self, request, slug):
        tenant = get_object_or_404(Tenant, slug=slug, is_active=True)
        service_id = request.GET.get("service")
        staff_id = request.GET.get("staff")
        date_str = request.GET.get("date")
        service = get_object_or_404(Service, pk=service_id, tenant=tenant) if service_id else None
        staff = get_object_or_404(StaffMember, pk=staff_id, tenant=tenant) if staff_id else None
        form = WaitingListForm(initial={
            "service": service,
            "staff": staff,
            "date": date_str,
        })
        return render(request, "booking/waiting_list.html", {
            "tenant": tenant, "form": form, "service": service, "staff": staff, "date": date_str,
        })

    def post(self, request, slug):
        tenant = get_object_or_404(Tenant, slug=slug, is_active=True)
        form = WaitingListForm(request.POST)
        if form.is_valid():
            wl = form.save(commit=False)
            wl.tenant = tenant
            wl.save()
            messages.success(request, "You've been added to the waiting list! We'll notify you if a slot opens up.")
            return redirect(reverse("book", args=[tenant.slug]))
        return render(request, "booking/waiting_list.html", {
            "tenant": tenant, "form": form,
        })


waiting_list_view = WaitingListView.as_view()


class ReviewLookupView(View):
    """Public view: customer finds their completed appointments by phone/ID to leave a review."""

    def get(self, request, slug):
        tenant = get_object_or_404(Tenant, slug=slug, is_active=True)
        return render(request, "booking/review_lookup.html", {"tenant": tenant})

    def post(self, request, slug):
        tenant = get_object_or_404(Tenant, slug=slug, is_active=True)
        phone = request.POST.get("phone", "").strip()
        booking_id = request.POST.get("booking_id", "").strip()
        ctx = {"tenant": tenant, "phone": phone, "booking_id": booking_id}

        if not phone:
            ctx["error"] = "Please enter your mobile number."
            return render(request, "booking/review_lookup.html", ctx)

        qs = Appointment.objects.filter(
            tenant=tenant, customer_phone__icontains=phone, status="completed"
        ).select_related("service", "staff")

        if booking_id:
            try:
                qs = qs.filter(pk=int(booking_id))
            except ValueError:
                ctx["error"] = "Invalid Booking ID — please enter numbers only."
                return render(request, "booking/review_lookup.html", ctx)

        appointments = list(qs.order_by("-date")[:10])
        if not appointments:
            ctx["error"] = "No completed appointments found for that mobile number. Check the number and try again."
            return render(request, "booking/review_lookup.html", ctx)

        ctx["appointments"] = appointments
        return render(request, "booking/review_lookup.html", ctx)


review_lookup_view = ReviewLookupView.as_view()
