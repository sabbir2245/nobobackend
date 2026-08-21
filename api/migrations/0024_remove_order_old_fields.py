"""Remove old single-product fields from Order (data already migrated to OrderItem)."""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0023_data_migrate_order_items'),
    ]

    operations = [
        migrations.RemoveField(model_name='order', name='post'),
        migrations.RemoveField(model_name='order', name='quantity_kg'),
        migrations.RemoveField(model_name='order', name='quantity_type'),
        migrations.RemoveField(model_name='order', name='est_weight_kg'),
    ]
