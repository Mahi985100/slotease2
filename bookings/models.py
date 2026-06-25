from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import models, transaction
from tenants.models import Tenant, Service, StaffMember


class Appointment(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("confirmed", "Confirmed"),
        ("cancelled", "Cancelled"),
        ("completed", "Completed"),
    ]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="appointments")
    customer_name = models.CharField(max_length=120)
    customer_phone = models.CharField(max_length=30)
    customer_email = models.EmailField(blank=True)
    service = models.ForeignKey(Service, on_delete=models.PROTECT)
    staff = models.ForeignKey(StaffMember, on_delete=models.PROTECT)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Reminder tracking
    reminder_24h_sent = models.BooleanField(default=False)
    reminder_1h_sent = models.BooleanField(default=False)
    # Google Calendar
    google_calendar_event_id = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-date", "-start_time"]

    def clean(self):
        if self.start_time >= self.end_time:
            raise ValidationError("Start time must be before end time.")
        if self.service.tenant_id != self.tenant_id or self.staff.tenant_id != self.tenant_id:
            raise ValidationError("Service and staff must belong to the same tenant.")
        conflict_qs = Appointment.objects.filter(
            staff=self.staff,
            date=self.date,
            status__in=["pending", "confirmed"],
        ).exclude(pk=self.pk).filter(
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
        )
        if conflict_qs.exists():
            raise ValidationError("This staff member already has an appointment in that time slot.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    @transaction.atomic
    def book_safely(cls, **fields):
        appt = cls(**fields)
        list(
            cls.objects.select_for_update()
            .filter(staff=appt.staff, date=appt.date, status__in=["pending", "confirmed"])
        )
        appt.save()
        return appt

    def __str__(self):
        return f"{self.customer_name} - {self.service} @ {self.date} {self.start_time}"


class Review(models.Model):
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE, related_name="review")
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)])
    comment = models.TextField(blank=True)
    owner_reply = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Review for {self.appointment} — {self.rating}★"


class LeaveRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]
    staff = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name="leave_requests")
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.staff.name} leave {self.start_date}–{self.end_date} ({self.status})"


class WaitingList(models.Model):
    """Customer joins the waiting list when a slot is fully booked."""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="waiting_list")
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    staff = models.ForeignKey(StaffMember, on_delete=models.CASCADE, null=True, blank=True)
    date = models.DateField()
    customer_name = models.CharField(max_length=120)
    customer_phone = models.CharField(max_length=30)
    customer_email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    notified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Waitlist: {self.customer_name} for {self.service} on {self.date}"


# ---------------------------------------------------------------------------
# Signal: auto-notify waiting list when an appointment is cancelled
# ---------------------------------------------------------------------------
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.conf import settings as django_settings


@receiver(post_save, sender=Appointment)
def notify_waitlist_on_cancellation(sender, instance, created, **kwargs):
    """When an appointment is cancelled, notify the first un-notified waiting-list
    entry for the same tenant / service / date combination."""
    if created:
        return
    if instance.status != "cancelled":
        return

    # Find the earliest un-notified waiting list entry for same service+date
    entry = WaitingList.objects.filter(
        tenant=instance.tenant,
        service=instance.service,
        date=instance.date,
        notified=False,
    ).order_by("created_at").first()

    if entry is None:
        return

    # Mark as notified
    entry.notified = True
    entry.save(update_fields=["notified"])

    # Send email notification if customer provided email
    if entry.customer_email:
        try:
            subject = f"Good news! A slot opened up at {instance.tenant.name}"
            message = (
                f"Hi {entry.customer_name},\n\n"
                f"A cancellation just opened up for {entry.service.name} "
                f"on {entry.date} at {instance.tenant.name}.\n\n"
                f"Book your slot now: "
                f"http://localhost:8000/{instance.tenant.slug}/book/"
                f"?service={entry.service_id}"
                f"&date={entry.date}\n\n"
                f"Hurry — slots fill up fast!\n\n"
                f"— {instance.tenant.name} via SlotEase"
            )
            send_mail(
                subject,
                message,
                django_settings.DEFAULT_FROM_EMAIL,
                [entry.customer_email],
                fail_silently=True,
            )
        except Exception:
            pass  # Never let notification failure break the save
