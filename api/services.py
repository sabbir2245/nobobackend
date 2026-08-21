import math
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from .models import Area, PendingPool, Batch, BatchItem, Order, OrderItem


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between two lat/lon points."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)


def district_centroid(union):
    """Return the (latitude, longitude) of a location's district node, or (None, None)."""
    if union is None:
        return None, None
    district = union.parent_chain().get('district')
    if district is None:
        return None, None
    return district.latitude, district.longitude


def area_for_post(post):
    """Return the active Area for a post's union/upazila, or None."""
    if post.location is None:
        return None
    upazila = post.location if post.location.level == 'upazila' else post.location.parent
    if upazila is None:
        return None
    return Area.objects.filter(upazilas=upazila, is_active=True).first()


def build_batch(area, union, product_type):
    """Bundle all approved contributing OrderItems for this union+product into a Batch.

    Each OrderItem becomes a BatchItem, linked to the batch via its parent Order.
    """
    contributing_items = list(
        OrderItem.objects.filter(
            order__status='approved',
            post__location=union,
            post__product_type=product_type,
            batch_items__isnull=True,
        ).select_related('order', 'post', 'farmer')
    )
    if not contributing_items:
        return None

    total_qty = sum((item.effective_weight_kg for item in contributing_items), Decimal('0'))
    total_value = sum((item.subtotal for item in contributing_items), Decimal('0'))

    batch = Batch.objects.create(
        area=area,
        union=union,
        product_type=product_type,
        total_quantity_kg=total_qty,
        total_value=total_value,
        status='pending',
    )
    for item in contributing_items:
        BatchItem.objects.create(
            batch=batch,
            order=item.order,
            quantity_kg=item.effective_weight_kg,
            farmer=item.farmer,
        )
    return batch


def add_order_to_pool(order):
    """Feed each OrderItem in an approved order into the pooling/batching engine.

    Each item goes to its own pool (area + union + product_type). When a pool
    reaches the area threshold, a Batch is created.
    """
    if order.status != 'approved':
        return

    for item in order.items.select_related('post').all():
        post = item.post
        area = area_for_post(post)
        if area is None:
            continue

        union = post.location

        pool, created = PendingPool.objects.select_for_update().get_or_create(
            area=area,
            union=union,
            product_type=post.product_type,
            defaults={'pending_quantity_kg': item.effective_weight_kg},
        )
        if not created:
            pool.pending_quantity_kg += item.effective_weight_kg
            pool.save(update_fields=['pending_quantity_kg'])

        if pool.pending_quantity_kg >= area.threshold_kg:
            build_batch(area, union, post.product_type)
            pool.pending_quantity_kg = Decimal('0')
            pool.save(update_fields=['pending_quantity_kg'])


def process_new_order(order):
    """Helper to be called after an Order is created."""
    with transaction.atomic():
        add_order_to_pool(order)


def notify_batch_users(batch, notification_type, title, message=None):
    """Create a Notification for every user affected by a batch event.

    Notified users: the customers of every order in the batch, the batch's
    farmers (via BatchItem), and the assigned deliveryman. Returns the list of
    created Notification objects.
    """
    from .models import Notification, Order

    users = set()
    order_ids = []

    for item in batch.items.select_related('order', 'farmer').all():
        order = item.order
        if order:
            users.add(order.customer_id)
            order_ids.append(order.id)
        users.add(item.farmer_id)
    if batch.deliveryman_id:
        users.add(batch.deliveryman_id)

    notifications = []
    for user_id in users:
        notification = Notification.objects.create(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            message=message or '',
            batch=batch,
            order_id=order_ids[0] if order_ids else None,
        )
        notifications.append(notification)
    return notifications