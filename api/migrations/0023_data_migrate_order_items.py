"""Data migration: create OrderItem rows from existing single-product Orders."""
from decimal import Decimal
from django.db import migrations


def forwards(apps, schema_editor):
    Order = apps.get_model('api', 'Order')
    OrderItem = apps.get_model('api', 'OrderItem')
    Post = apps.get_model('api', 'Post')

    for order in Order.objects.select_related('post', 'post__farmer').all():
        if order.post_id and not order.items.exists():
            post = Post.objects.select_for_update().get(pk=order.post_id)
            price_per_kg = post.price_per_kg
            subtotal = round(order.quantity_kg * price_per_kg, 2)
            OrderItem.objects.create(
                order=order,
                post_id=order.post_id,
                farmer_id=post.farmer_id,
                quantity_kg=order.quantity_kg,
                quantity_type=order.quantity_type,
                est_weight_kg=order.est_weight_kg,
                price_per_kg=price_per_kg,
                subtotal=subtotal,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0022_add_orderitem_alter_order'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
