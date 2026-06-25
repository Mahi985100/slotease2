from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import Http404

from .models import Tenant, TenantUser


def get_user_role(user, tenant=None):
    """Return the TenantUser role string for `user` ('owner' / 'manager' / 'staff'),
    or None if the user has no membership at all."""
    if not user.is_authenticated:
        return None
    if tenant is not None:
        if tenant.owner_id == user.id:
            return "owner"
        tu = TenantUser.objects.filter(tenant=tenant, user=user).first()
        return tu.role if tu else None
    # No tenant given: look up the user's own tenant first.
    t = Tenant.objects.filter(owner=user).first()
    if t:
        return "owner"
    tu = TenantUser.objects.filter(user=user).select_related("tenant").first()
    return tu.role if tu else None


def get_user_tenant(user):
    """Return the first tenant this user owns or belongs to, else None."""
    if not user.is_authenticated:
        return None
    t = Tenant.objects.filter(owner=user).first()
    if t:
        return t
    tu = TenantUser.objects.filter(user=user).select_related("tenant").first()
    return tu.tenant if tu else None


def require_tenant(user):
    """Return the tenant the user belongs to, or raise 404 (no cross-tenant leakage
    via a generic 'not found' response rather than a 403 that confirms existence)."""
    t = get_user_tenant(user)
    if not t:
        raise Http404("No tenant for user")
    return t


# Roles allowed to manage services/staff/availability and change appointment status.
MANAGE_ROLES = {"owner", "manager"}


def require_manage_role(user, tenant):
    """Raise PermissionDenied unless the user's role on `tenant` permits management
    actions (owner or manager). Staff-role members get read-only dashboard access."""
    role = get_user_role(user, tenant)
    if role not in MANAGE_ROLES:
        raise PermissionDenied("You do not have permission to manage this resource.")
    return role


def manage_required(view_func):
    """Decorator for dashboard views that mutate data (create/edit/delete).
    Must be used on a view that already resolved `tenant = require_tenant(request.user)`
    and called this *before* touching any other tenant's objects. Usage:

        @login_required
        @manage_required
        def my_view(request, tenant, *args, **kwargs):
            ...

    This decorator itself looks up the tenant and role, then passes `tenant` to the
    wrapped view as a keyword argument so every protected view shares one code path.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        tenant = require_tenant(request.user)
        require_manage_role(request.user, tenant)
        return view_func(request, tenant=tenant, *args, **kwargs)
    return _wrapped


def tenant_required(view_func):
    """Decorator for dashboard views that only need read access (any role: owner,
    manager, or staff). Resolves the tenant and passes it in as a keyword argument."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        tenant = require_tenant(request.user)
        return view_func(request, tenant=tenant, *args, **kwargs)
    return _wrapped
