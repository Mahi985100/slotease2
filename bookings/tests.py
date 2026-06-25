"""Tests for the public booking flow: all four wizard steps render without
crashing (regression test for the dead {% for %} tags that previously broke
every booking page), the slot-conflict guard, and tenant-scoped lookups."""
from datetime import date, time

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from tenants.models import Availability, Service, StaffMember, Tenant

from .models import Appointment

User = get_user_model()


class BookingWizardRendersTests(TestCase):
    """Regression coverage for the booking/_layout.html dead template tag
    that previously raised ValueError on every single booking page."""

    def setUp(self):
        owner = User.objects.create_user(username="owner", password="S3curePass!23")
        self.tenant = Tenant.objects.create(name="Glow Salon", owner=owner)
        self.service = Service.objects.create(tenant=self.tenant, name="Haircut", duration_minutes=30, price="20.00")
        self.staff = StaffMember.objects.create(tenant=self.tenant, name="Alice")
        self.staff.services.add(self.service)
        Availability.objects.create(
            staff=self.staff, day_of_week=date.today().weekday(),
            start_time=time(9, 0), end_time=time(17, 0),
        )

    def test_step1_service_selection_renders(self):
        resp = self.client.get(reverse("book", args=[self.tenant.slug]), {"step": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Haircut")

    def test_step2_staff_selection_renders(self):
        resp = self.client.get(reverse("book", args=[self.tenant.slug]),
                                {"step": "2", "service": self.service.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Alice")

    def test_step3_datetime_renders_with_slots(self):
        resp = self.client.get(reverse("book", args=[self.tenant.slug]), {
            "step": "3", "service": self.service.pk, "staff": self.staff.pk,
            "date": date.today().isoformat(),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "09:00")

    def test_step4_customer_form_renders(self):
        resp = self.client.get(reverse("book", args=[self.tenant.slug]), {
            "step": "4", "service": self.service.pk, "staff": self.staff.pk,
            "date": date.today().isoformat(), "time": "09:00",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Confirm booking")

    def test_full_booking_flow_creates_appointment_and_detail_page_renders(self):
        resp = self.client.post(
            reverse("book", args=[self.tenant.slug]),
            {"customer_name": "Jane Doe", "customer_phone": "555-1234", "customer_email": "jane@example.com"},
            **{
                "QUERY_STRING": f"step=4&service={self.service.pk}&staff={self.staff.pk}"
                                 f"&date={date.today().isoformat()}&time=09:00"
            },
        )
        self.assertEqual(resp.status_code, 302)
        appt = Appointment.objects.get(customer_name="Jane Doe")
        self.assertEqual(appt.status, "pending")

        detail_resp = self.client.get(reverse("booking_detail", args=[self.tenant.slug, appt.pk]))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, "Jane Doe")


class SlotConflictTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user(username="owner2", password="S3curePass!23")
        self.tenant = Tenant.objects.create(name="Salon", owner=owner)
        self.service = Service.objects.create(tenant=self.tenant, name="Cut", duration_minutes=30, price="10.00")
        self.staff = StaffMember.objects.create(tenant=self.tenant, name="Bob")

    def test_overlapping_appointment_rejected(self):
        Appointment.objects.create(
            tenant=self.tenant, service=self.service, staff=self.staff,
            date=date.today(), start_time=time(10, 0), end_time=time(10, 30),
            customer_name="First", customer_phone="111",
        )
        with self.assertRaises(ValidationError):
            Appointment.objects.create(
                tenant=self.tenant, service=self.service, staff=self.staff,
                date=date.today(), start_time=time(10, 15), end_time=time(10, 45),
                customer_name="Second", customer_phone="222",
            )

    def test_book_safely_rejects_concurrent_conflict(self):
        Appointment.book_safely(
            tenant=self.tenant, service=self.service, staff=self.staff,
            date=date.today(), start_time=time(11, 0), end_time=time(11, 30),
            customer_name="First", customer_phone="111",
        )
        with self.assertRaises(ValidationError):
            Appointment.book_safely(
                tenant=self.tenant, service=self.service, staff=self.staff,
                date=date.today(), start_time=time(11, 0), end_time=time(11, 30),
                customer_name="Second", customer_phone="222",
            )

    def test_non_overlapping_appointment_allowed(self):
        Appointment.objects.create(
            tenant=self.tenant, service=self.service, staff=self.staff,
            date=date.today(), start_time=time(10, 0), end_time=time(10, 30),
            customer_name="First", customer_phone="111",
        )
        appt2 = Appointment.objects.create(
            tenant=self.tenant, service=self.service, staff=self.staff,
            date=date.today(), start_time=time(10, 30), end_time=time(11, 0),
            customer_name="Second", customer_phone="222",
        )
        self.assertIsNotNone(appt2.pk)


class CrossTenantBookingTests(TestCase):
    """A booking link for tenant A must never expose or accept tenant B's
    services/staff, even if a malicious customer mixes IDs across slugs."""

    def setUp(self):
        ownerA = User.objects.create_user(username="ownerA2", password="S3curePass!23")
        self.tenantA = Tenant.objects.create(name="Salon A2", owner=ownerA)
        self.serviceA = Service.objects.create(tenant=self.tenantA, name="A Service", duration_minutes=30, price="10.00")
        self.staffA = StaffMember.objects.create(tenant=self.tenantA, name="A Staff")

        ownerB = User.objects.create_user(username="ownerB2", password="S3curePass!23")
        self.tenantB = Tenant.objects.create(name="Salon B2", owner=ownerB)
        self.serviceB = Service.objects.create(tenant=self.tenantB, name="B Service", duration_minutes=30, price="10.00")

    def test_booking_b_slug_with_a_service_id_404s(self):
        resp = self.client.get(reverse("book", args=[self.tenantB.slug]),
                                {"step": "2", "service": self.serviceA.pk})
        self.assertEqual(resp.status_code, 404)
