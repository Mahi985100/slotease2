"""Management command: send pending appointment email reminders.

Run this every 15 minutes via cron or a process scheduler, e.g.:
    */15 * * * * /path/to/venv/bin/python manage.py send_reminders
"""
from django.core.management.base import BaseCommand
from bookings.reminders import send_pending_reminders


class Command(BaseCommand):
    help = "Send 24-hour and 1-hour email reminders for upcoming appointments."

    def handle(self, *args, **options):
        count = send_pending_reminders()
        self.stdout.write(self.style.SUCCESS(f"Sent {count} reminder email(s)."))
