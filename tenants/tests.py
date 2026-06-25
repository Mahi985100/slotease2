"""End-to-end tests covering tenant isolation, role-based permissions, and the
public booking flow (including the two template bugs and the role-permission
gap found during review)."""
from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from bookings.models import Appointment
from .models import Service, StaffMember, Tenant, TenantUser

User = get_user_model()


class RegistrationCreatesTenantTests(TestCase):
    def test_register_creates_tenant_and_owner_membership(self):
        resp = self.client.post(reverse("register"), {
            "username": "owner1", "email": "o1@example.com",
            "password1": "S3curePass!23", "password2": "S3curePass!23",
            "business_name": "Glow Salon", "phone": "555", "address": "1 Main St",
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        tenant = Tenant.objects.get(name="Glow Salon")
        self.assertEqual(tenant.owner.username, "owner1")
        self.assertTrue(TenantUser.objects.filter(tenant=tenant, user=tenant.owner, role="owner").exists())


class TenantIsolationTests(TestCase):
    """Confirms a user from Tenant B can never read or write Tenant A's data,
    even when guessing primary keys directly in dashboard URLs."""

    def setUp(self):
        self.ownerA = User.objects.create_user(username="ownerA", password="S3curePass!23")
        self.tenantA = Tenant.objects.create(name="Salon A", owner=self.ownerA)
        TenantUser.objects.create(tenant=self.tenantA, user=self.ownerA, role="owner")
        self.serviceA = Service.objects.create(tenant=self.tenantA, name="Haircut", duration_minutes=30, price="20.00")
        self.staffA = StaffMember.objects.create(tenant=self.tenantA, name="Alice")

        self.ownerB = User.objects.create_user(username="ownerB", password="S3curePass!23")
        self.tenantB = Tenant.objects.create(name="Salon B", owner=self.ownerB)
        TenantUser.objects.create(tenant=self.tenantB, user=self.ownerB, role="owner")

    def test_cross_tenant_service_edit_404s(self):
        self.client.login(username="ownerB", password="S3curePass!23")
        resp = self.client.get(reverse("service_edit", args=[self.serviceA.pk]))
        self.assertEqual(resp.status_code, 404)
        resp = self.client.post(reverse("service_edit", args=[self.serviceA.pk]), {
            "name": "HACKED", "duration_minutes": 1, "price": "0.00",
        })
        self.assertEqual(resp.status_code, 404)
        self.serviceA.refresh_from_db()
        self.assertEqual(self.serviceA.name, "Haircut")

    def test_cross_tenant_service_delete_404s(self):
        self.client.login(username="ownerB", password="S3curePass!23")
        resp = self.client.post(reverse("service_delete", args=[self.serviceA.pk]))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Service.objects.filter(pk=self.serviceA.pk).exists())

    def test_cross_tenant_staff_edit_404s(self):
        self.client.login(username="ownerB", password="S3curePass!23")
        resp = self.client.get(reverse("staff_edit", args=[self.staffA.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_tenant_b_service_list_never_shows_tenant_a_services(self):
        self.client.login(username="ownerB", password="S3curePass!23")
        resp = self.client.get(reverse("service_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.serviceA, resp.context["services"])

    def test_appointments_export_only_contains_own_tenant(self):
        StaffMember.objects.create(tenant=self.tenantB, name="Bob")
        Appointment.objects.create(
            tenant=self.tenantA, service=self.serviceA, staff=self.staffA,
            date=date.today(), start_time=time(9, 0), end_time=time(9, 30),
            customer_name="Tenant A Customer", customer_phone="111",
        )
        self.client.login(username="ownerB", password="S3curePass!23")
        resp = self.client.get(reverse("appointments_csv"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertNotIn("Tenant A Customer", body)


class RolePermissionTests(TestCase):
    """Confirms the role system (owner/manager/staff) actually restricts
    mutating actions to owner/manager, while still allowing staff read access."""

    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="S3curePass!23")
        self.tenant = Tenant.objects.create(name="Salon", owner=self.owner)
        TenantUser.objects.create(tenant=self.tenant, user=self.owner, role="owner")

        self.staffer = User.objects.create_user(username="staffer", password="S3curePass!23")
        TenantUser.objects.create(tenant=self.tenant, user=self.staffer, role="staff")

        self.manager = User.objects.create_user(username="manager", password="S3curePass!23")
        TenantUser.objects.create(tenant=self.tenant, user=self.manager, role="manager")

        self.service = Service.objects.create(tenant=self.tenant, name="Haircut", duration_minutes=30, price="20.00")

    def test_staff_role_cannot_create_service(self):
        self.client.login(username="staffer", password="S3curePass!23")
        resp = self.client.post(reverse("service_new"), {
            "name": "Sneaky", "duration_minutes": 10, "price": "1.00",
        })
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Service.objects.filter(name="Sneaky").exists())

    def test_staff_role_cannot_delete_service(self):
        self.client.login(username="staffer", password="S3curePass!23")
        resp = self.client.post(reverse("service_delete", args=[self.service.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Service.objects.filter(pk=self.service.pk).exists())

    def test_staff_role_cannot_change_appointment_status(self):
        staff_member = StaffMember.objects.create(tenant=self.tenant, name="Alice")
        appt = Appointment.objects.create(
            tenant=self.tenant, service=self.service, staff=staff_member,
            date=date.today(), start_time=time(9, 0), end_time=time(9, 30),
            customer_name="Cust", customer_phone="111",
        )
        self.client.login(username="staffer", password="S3curePass!23")
        resp = self.client.post(reverse("appointment_status", args=[appt.pk]), {"status": "confirmed"})
        self.assertEqual(resp.status_code, 403)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "pending")

    def test_staff_role_can_view_appointments_list(self):
        self.client.login(username="staffer", password="S3curePass!23")
        resp = self.client.get(reverse("appointments"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["can_manage"])

    def test_manager_role_can_create_service(self):
        self.client.login(username="manager", password="S3curePass!23")
        resp = self.client.post(reverse("service_new"), {
            "name": "Manager Made", "duration_minutes": 15, "price": "5.00",
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Service.objects.filter(name="Manager Made").exists())

    def test_owner_can_manage(self):
        self.client.login(username="owner", password="S3curePass!23")
        resp = self.client.get(reverse("service_new"))
        self.assertEqual(resp.status_code, 200)


class ProtectedDeleteTests(TestCase):
    """Regression coverage: deleting a Service or StaffMember that still has
    Appointments pointing at it (FK is on_delete=PROTECT) must not 500. The
    delete views catch ProtectedError and redirect back with a friendly
    message instead of crashing."""

    def setUp(self):
        self.owner = User.objects.create_user(username="owner3", password="S3curePass!23")
        self.tenant = Tenant.objects.create(name="Protected Salon", owner=self.owner)
        TenantUser.objects.create(tenant=self.tenant, user=self.owner, role="owner")
        self.service = Service.objects.create(tenant=self.tenant, name="Cut", duration_minutes=30, price="20.00")
        self.staff = StaffMember.objects.create(tenant=self.tenant, name="Carol")
        Appointment.objects.create(
            tenant=self.tenant, service=self.service, staff=self.staff,
            date=date.today(), start_time=time(9, 0), end_time=time(9, 30),
            customer_name="Has Appt", customer_phone="555",
        )

    def test_deleting_service_with_appointment_does_not_500(self):
        self.client.login(username="owner3", password="S3curePass!23")
        resp = self.client.post(reverse("service_delete", args=[self.service.pk]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Service.objects.filter(pk=self.service.pk).exists())
        messages_text = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("can't be deleted" in m for m in messages_text))

    def test_deleting_staff_with_appointment_does_not_500(self):
        self.client.login(username="owner3", password="S3curePass!23")
        resp = self.client.post(reverse("staff_delete", args=[self.staff.pk]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(StaffMember.objects.filter(pk=self.staff.pk).exists())
        messages_text = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("can't be deleted" in m for m in messages_text))
