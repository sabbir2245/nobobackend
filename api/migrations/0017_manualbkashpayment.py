from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('api', '0016_order_est_weight_kg_order_quantity_type_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='ManualBkashPayment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sender_number', models.CharField(help_text='bKash number money was sent FROM', max_length=20)),
                ('amount', models.DecimalField(decimal_places=2, help_text='Amount sent via bKash', max_digits=10)),
                ('trx_id', models.CharField(help_text='bKash Send Money Transaction ID', max_length=50)),
                ('payment_type', models.CharField(choices=[('advance', 'Advance (50%)'), ('final', 'Final (50%)')], default='advance', help_text='advance (50%) or final (50%)', max_length=10)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending', max_length=10)),
                ('admin_note', models.TextField(blank=True, default='', help_text='Admin note on approve/reject')),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_manual_bkash_payments', to=settings.AUTH_USER_MODEL)),
                ('order', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='manual_bkash_payments', to='api.order')),
                ('payment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='manual_bkash_submissions', to='api.payment')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='manual_bkash_payments', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
