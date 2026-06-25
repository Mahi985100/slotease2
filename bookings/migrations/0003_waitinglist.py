from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0002_appointment_reminders_review_leave'),
        ('tenants', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='WaitingList',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('customer_name', models.CharField(max_length=120)),
                ('customer_phone', models.CharField(max_length=30)),
                ('customer_email', models.EmailField(blank=True)),
                ('notes', models.TextField(blank=True)),
                ('notified', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('service', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tenants.service')),
                ('staff', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='tenants.staffmember')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='waiting_list', to='tenants.tenant')),
            ],
            options={
                'ordering': ['created_at'],
            },
        ),
    ]
