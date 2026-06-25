from django.conf import settings
from django.db import models
from django.utils.text import slugify

class Tenant(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_tenants")
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "salon"
            slug = base
            i = 2
            while Tenant.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{i}"; i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self): return self.name


class TenantUser(models.Model):
    ROLE_CHOICES = [("owner", "Owner"), ("manager", "Manager"), ("staff", "Staff")]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tenant_memberships")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="owner")
    class Meta:
        unique_together = [("tenant", "user")]
    def __str__(self): return f"{self.user} @ {self.tenant} ({self.role})"


class Service(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="services")
    name = models.CharField(max_length=120)
    duration_minutes = models.PositiveIntegerField(default=30)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    def __str__(self): return f"{self.name} ({self.duration_minutes}m)"


class StaffMember(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="staff")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="staff_profiles")
    name = models.CharField(max_length=120)
    bio = models.TextField(blank=True)
    services = models.ManyToManyField(Service, related_name="staff", blank=True)
    is_active = models.BooleanField(default=True)
    def __str__(self): return self.name


class Availability(models.Model):
    DAYS = [(0, "Mon"), (1, "Tue"), (2, "Wed"), (3, "Thu"), (4, "Fri"), (5, "Sat"), (6, "Sun")]
    staff = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name="availabilities")
    day_of_week = models.IntegerField(choices=DAYS)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    class Meta:
        ordering = ["day_of_week", "start_time"]
    def __str__(self): return f"{self.staff} {self.get_day_of_week_display()} {self.start_time}-{self.end_time}"


class SubscriptionPlan(models.Model):
    PLAN_CHOICES = [
        ("free", "Free"),
        ("professional", "Professional"),
        ("enterprise", "Enterprise"),
    ]
    name = models.CharField(max_length=50, choices=PLAN_CHOICES, unique=True)
    display_name = models.CharField(max_length=80)
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_staff = models.IntegerField(default=3)            # -1 = unlimited
    max_branches = models.IntegerField(default=1)         # -1 = unlimited
    features = models.JSONField(default=list)             # list of feature strings

    def __str__(self): return self.display_name


class TenantSubscription(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("expired", "Expired"),
        ("cancelled", "Cancelled"),
    ]
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self): return f"{self.tenant} — {self.plan} ({self.status})"

    @property
    def is_active(self):
        from django.utils import timezone
        if self.status != "active":
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return True
