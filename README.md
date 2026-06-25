# SlotEase - Multi-tenant Salon Booking SaaS

Django 4.x + PostgreSQL + TailwindCSS (CDN).

## Quick Start

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Configure database

Either set `DATABASE_URL` env var, or edit `.env`:

```
SECRET_KEY=change-me
DEBUG=True
DATABASE_URL=postgres://user:pass@localhost:5432/slotease
```

If you don't have PostgreSQL handy, the project falls back to SQLite when `DATABASE_URL` is unset.

### Run

```bash
python manage.py makemigrations accounts tenants bookings
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000/

## URLs

- `/`                        Landing (lists demo tenants)
- `/register/`               Tenant registration (creates owner + tenant)
- `/login/`  `/logout/`      Auth
- `/dashboard/`              Tenant dashboard
- `/dashboard/services/`     Manage services
- `/dashboard/staff/`        Manage staff + availability
- `/dashboard/appointments/` Manage appointments (filter, status, CSV export)
- `/<slug>/book/`            Public booking flow (4 steps)
- `/<slug>/booking/<id>/`    Booking confirmation
- `/admin/`                  Django admin

## Apps

- `accounts` — custom user (AbstractUser)
- `tenants`  — Tenant, TenantUser, Service, StaffMember, Availability
- `bookings` — Appointment + public booking views

## Roles & permissions

Every dashboard view resolves the logged-in user's tenant and role
(`owner` / `manager` / `staff`) via `tenants.mixins.TenantRequiredMixin` /
`ManageRoleRequiredMixin`:

- **owner / manager** — full access: create/edit/delete services, staff,
  and availability; change appointment status; export CSV.
- **staff** — read-only: can view the dashboard, service list, staff list,
  and appointments, but mutating actions return `403 Forbidden`. Templates
  also hide the corresponding buttons for staff-role users.

All tenant-scoped lookups (`Service`, `StaffMember`, `Availability`,
`Appointment`) are filtered by `tenant=<the logged-in user's tenant>`, so a
request for another tenant's object id returns `404` instead of leaking
whether it exists. This is covered by `tenants/tests.py::TenantIsolationTests`
and `RolePermissionTests`.

## Security notes

- **CSRF** — enabled globally (`CsrfViewMiddleware`); every POST form in the
  templates includes `{% csrf_token %}`.
- **Tenant isolation** — see "Roles & permissions" above.
- **Double-booking** — `Appointment.clean()` rejects overlapping slots for
  the same staff member at the model level. The public booking view calls
  `Appointment.book_safely(...)`, which wraps the conflict check in a
  `transaction.atomic()` block with `select_for_update()` on PostgreSQL, so
  two customers can't both win the same slot in a race.
- **Production hardening** — when `DEBUG=False`, `settings.py` turns on
  secure cookies, HSTS, and SSL redirect automatically. Set `DEBUG=False`,
  a real `SECRET_KEY`, and a specific `ALLOWED_HOSTS` before deploying.

## Running tests

```bash
python manage.py test
```

23 tests cover registration, tenant isolation, role permissions, the public
booking wizard (all 4 steps + confirmation), slot-conflict handling, and
graceful handling of protected-FK deletes (services/staff with existing
appointments).

## Error pages

Custom-styled `403.html`, `404.html`, and `500.html` templates are included
so a permission error, missing page, or unexpected server error never shows
Django's bare default page in production (`DEBUG=False`).
