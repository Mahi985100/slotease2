from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SubscriptionPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50, choices=[('free','Free'),('professional','Professional'),('enterprise','Enterprise')], unique=True)),
                ('display_name', models.CharField(max_length=80)),
                ('price_monthly', models.DecimalField(max_digits=10, decimal_places=2, default=0)),
                ('max_staff', models.IntegerField(default=3)),
                ('max_branches', models.IntegerField(default=1)),
                ('features', models.JSONField(default=list)),
            ],
        ),
        migrations.CreateModel(
            name='TenantSubscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(max_length=20, choices=[('active','Active'),('expired','Expired'),('cancelled','Cancelled')], default='active')),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField(null=True, blank=True)),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenants.subscriptionplan')),
                ('tenant', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='subscription', to='tenants.tenant')),
            ],
        ),
    ]
