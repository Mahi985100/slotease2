"""
Email reminder utilities for SlotEase.

Sends reminders 24 hours and 1 hour before appointments via Django's
email backend. Call send_pending_reminders() from a scheduled task
(e.g. a cron job or management command running every 15 minutes).
"""
from datetime import datetime, timedelta, timezone as dt_tz

from django.core.mail import send_mail
from django.utils import timezone


def _appointment_datetime(appt):
    """Return a timezone-aware datetime combining appt.date + appt.start_time."""
    naive = datetime.combine(appt.date, appt.start_time)
    return naive.replace(tzinfo=dt_tz.utc)


def _send_reminder(appt, hours_before):
    if not appt.customer_email:
        return False
    subject = f"Reminder: Your appointment in {hours_before} hour{'s' if hours_before != 1 else ''}"
    body = (
        f"Hi {appt.customer_name},\n\n"
        f"This is a reminder that you have an appointment scheduled:\n\n"
        f"  Service : {appt.service.name}\n"
        f"  Staff   : {appt.staff.name}\n"
        f"  Date    : {appt.date.strftime('%A, %B %d %Y')}\n"
        f"  Time    : {appt.start_time.strftime('%I:%M %p')}\n"
        f"  Salon   : {appt.tenant.name}\n\n"
        f"See you soon!\n— {appt.tenant.name} team"
    )
    try:
        send_mail(subject, body, None, [appt.customer_email], fail_silently=False)
        return True
    except Exception:
        return False


def send_pending_reminders():
    """
    Check all upcoming confirmed/pending appointments and send email reminders
    for those within 24 h or 1 h windows that haven't been sent yet.
    Designed to be called frequently (every 5–15 min) from a cron job or
    management command.
    """
    from .models import Appointment

    now = timezone.now()
    window_start = now
    window_end = now + timedelta(hours=25)  # look slightly beyond 24 h

    upcoming = Appointment.objects.filter(
        status__in=["pending", "confirmed"],
        customer_email__gt="",
    ).select_related("service", "staff", "tenant")

    sent_count = 0
    for appt in upcoming:
        appt_dt = _appointment_datetime(appt)
        delta = appt_dt - now
        total_seconds = delta.total_seconds()

        # 24-hour reminder: between 23h and 25h before
        if not appt.reminder_24h_sent and 23 * 3600 <= total_seconds <= 25 * 3600:
            if _send_reminder(appt, 24):
                appt.reminder_24h_sent = True
                appt.save(update_fields=["reminder_24h_sent"])
                sent_count += 1

        # 1-hour reminder: between 45 min and 75 min before
        elif not appt.reminder_1h_sent and 45 * 60 <= total_seconds <= 75 * 60:
            if _send_reminder(appt, 1):
                appt.reminder_1h_sent = True
                appt.save(update_fields=["reminder_1h_sent"])
                sent_count += 1

    return sent_count
