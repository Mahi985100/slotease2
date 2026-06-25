from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    phone = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.username

    @property
    def tenant(self):
        """The single Tenant this user owns or is a member of, or None.
        Lets views/templates use the `request.user.tenant` pattern for
        tenant-scoped queries (e.g. `Service.objects.filter(tenant=request.user.tenant)`)
        without importing the tenants app at module load time (would be circular,
        since tenants.models imports settings.AUTH_USER_MODEL)."""
        from tenants.utils import get_user_tenant
        return get_user_tenant(self)

    @property
    def tenant_role(self):
        """This user's role ('owner' / 'manager' / 'staff') on their tenant, or None."""
        from tenants.utils import get_user_role
        return get_user_role(self)
