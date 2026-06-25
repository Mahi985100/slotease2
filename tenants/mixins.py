"""Shared mixins for tenant-scoped class-based views.

These mixins enforce the two security properties required by the spec:

1. Tenant isolation — a logged-in user can only ever see/edit objects that
   belong to *their own* tenant. Every queryset used by a protected view is
   filtered by `tenant=self.tenant`, and `get_object_or_404` semantics are
   preserved so that a request for another tenant's object 404s instead of
   leaking a 403 (which would confirm the object's existence).
2. Role-based permissions — "owner" and "manager" can manage services,
   staff, availability, and appointment status. "staff" role members get
   read-only dashboard access (can view appointments but not mutate
   services/staff or change appointment status).
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404

from .utils import MANAGE_ROLES, get_user_role, get_user_tenant


class TenantRequiredMixin(LoginRequiredMixin):
    """Resolves `self.tenant` and `self.role` for the logged-in user before
    the view runs. Unauthenticated users are redirected to login (handled by
    LoginRequiredMixin); authenticated users with no tenant membership get a
    404 rather than a 403, since a 403 would confirm something exists."""

    #: Subclasses set this to True to additionally require an owner/manager role.
    require_manage_role = False

    def _resolve_tenant_and_role(self, request):
        self.tenant = get_user_tenant(request.user)
        if self.tenant is None:
            raise Http404("No tenant for user")
        self.role = get_user_role(request.user, self.tenant)
        if self.require_manage_role and self.role not in MANAGE_ROLES:
            raise PermissionDenied("You do not have permission to manage this resource.")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            self._resolve_tenant_and_role(request)
        return super().dispatch(request, *args, **kwargs)

    @property
    def can_manage(self):
        return getattr(self, "role", None) in MANAGE_ROLES

    def get_context_data(self, **kwargs):
        """Mixed in before generic views' own get_context_data via MRO;
        always exposes tenant/role/can_manage so templates can show or hide
        management controls without every view repeating this boilerplate."""
        ctx = super().get_context_data(**kwargs) if hasattr(super(), "get_context_data") else {}
        ctx.setdefault("tenant", getattr(self, "tenant", None))
        ctx.setdefault("role", getattr(self, "role", None))
        ctx.setdefault("can_manage", self.can_manage)
        return ctx


class ManageRoleRequiredMixin(TenantRequiredMixin):
    """Like TenantRequiredMixin, but additionally requires the 'owner' or
    'manager' role for any view that creates, edits, or deletes data. Plain
    'staff' role members are denied with 403 (they're real members of the
    tenant, just without management rights)."""
    require_manage_role = True


class TenantQuerysetMixin:
    """For ListView/UpdateView/DeleteView: restricts the queryset to the
    current tenant so a cross-tenant pk in the URL 404s instead of leaking
    another tenant's row."""

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(tenant=self.tenant)


def get_tenant_object_or_404(model, tenant, **kwargs):
    """Helper for non-generic lookups that still need strict tenant scoping."""
    return get_object_or_404(model, tenant=tenant, **kwargs)


# ---------------------------------------------------------------------------
# Subscription enforcement helpers
# ---------------------------------------------------------------------------

def get_tenant_subscription(tenant):
    """Return the TenantSubscription for tenant, or None."""
    return getattr(tenant, 'subscription', None)


def subscription_allows_staff(tenant, current_count=None):
    """Return (allowed: bool, limit: int|-1, plan_name: str)."""
    sub = get_tenant_subscription(tenant)
    if sub is None or not sub.is_active:
        # No active sub → treat as free
        max_staff = 3
        plan_name = "Free"
    else:
        max_staff = sub.plan.max_staff
        plan_name = sub.plan.display_name

    if max_staff == -1:
        return True, -1, plan_name

    if current_count is None:
        from .models import StaffMember
        current_count = StaffMember.objects.filter(tenant=tenant, is_active=True).count()

    return current_count < max_staff, max_staff, plan_name


def subscription_allows_feature(tenant, feature_key):
    """Check if tenant's plan includes a specific feature key."""
    FEATURE_PLANS = {
        "waiting_list": {"professional", "enterprise"},
        "advanced_analytics": {"professional", "enterprise"},
        "csv_export": {"professional", "enterprise"},
        "multiple_branches": {"enterprise"},
        "priority_support": {"enterprise"},
    }
    required = FEATURE_PLANS.get(feature_key, set())
    if not required:
        return True  # feature not gated

    sub = get_tenant_subscription(tenant)
    if sub is None or not sub.is_active:
        return False
    return sub.plan.name in required
