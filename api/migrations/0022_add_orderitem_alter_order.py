import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0021_merge_20260821_0359'),
    ]

    operations = [
        # Create OrderItem first (additive, no data loss)
        migrations.CreateModel(
            name='OrderItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity_kg', models.DecimalField(decimal_places=2, max_digits=10)),
                ('quantity_type', models.CharField(choices=[('kg', 'Per KG'), ('piece', 'Per Piece')], default='kg', max_length=10)),
                ('est_weight_kg', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('price_per_kg', models.DecimalField(decimal_places=2, max_digits=10)),
                ('subtotal', models.DecimalField(decimal_places=2, max_digits=10)),
                ('farmer', models.ForeignKey(limit_choices_to={'role': 'farmer'}, on_delete=django.db.models.deletion.PROTECT, related_name='order_items', to=settings.AUTH_USER_MODEL)),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='api.order')),
                ('post', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='order_items', to='api.post')),
            ],
        ),
        # Alter Order fields (add defaults for existing rows)
        migrations.AlterField(
            model_name='order',
            name='farmer_payout',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AlterField(
            model_name='order',
            name='platform_fee',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AlterField(
            model_name='order',
            name='total_paid',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        # Remove unique constraint on Payment.transaction_id
        migrations.AlterField(
            model_name='payment',
            name='transaction_id',
            field=models.CharField(db_index=True, max_length=100),
        ),
    ]
