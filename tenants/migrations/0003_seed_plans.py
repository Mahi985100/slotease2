from django.db import migrations


def seed_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model('tenants', 'SubscriptionPlan')
    plans = [
        {
            'name': 'free',
            'display_name': 'Free',
            'price_monthly': 0,
            'max_staff': 3,
            'max_branches': 1,
            'features': ['Basic booking', 'Customer reviews', 'Basic dashboard'],
        },
        {
            'name': 'professional',
            'display_name': 'Professional',
            'price_monthly': 999,
            'max_staff': -1,
            'max_branches': 1,
            'features': ['Unlimited staff', 'Advanced analytics', 'Waiting list', 'SMS/Email reminders', 'Google Calendar sync', 'CSV export'],
        },
        {
            'name': 'enterprise',
            'display_name': 'Enterprise',
            'price_monthly': 2999,
            'max_staff': -1,
            'max_branches': -1,
            'features': ['Multiple branches', 'Unlimited staff', 'All Professional features', 'Priority support', 'Custom integrations', 'White-label option'],
        },
    ]
    for p in plans:
        SubscriptionPlan.objects.get_or_create(name=p['name'], defaults=p)


def unseed_plans(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0002_subscription'),
    ]

    operations = [
        migrations.RunPython(seed_plans, unseed_plans),
    ]
