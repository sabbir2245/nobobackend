import math
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from .models import Area, PendingPool, Batch, BatchItem, Order


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
    """Bundle all pending contributing orders for this union+product into a Batch."""
    contributing_orders = list(
        Order.objects.filter(
            status='pending',
            post__location=union,
            post__product_type=product_type,
            batch_items__isnull=True,
        ).select_related('post__farmer')
    )
    if not contributing_orders:
        return None

    total_qty = sum((o.quantity_kg for o in contributing_orders), Decimal('0'))
    total_value = sum((o.total_paid for o in contributing_orders), Decimal('0'))

    batch = Batch.objects.create(
        area=area,
        union=union,
        product_type=product_type,
        total_quantity_kg=total_qty,
        total_value=total_value,
        status='pending',
    )
    for order in contributing_orders:
        BatchItem.objects.create(
            batch=batch,
            order=order,
            quantity_kg=order.quantity_kg,
            farmer=order.post.farmer,
        )
    return batch


def add_order_to_pool(order):
    """Increment the pending pool for the order's area→union + product.

    Runs inside the caller's transaction (with row locking on the pool). Creates a
    Batch when the pool reaches the area threshold, then resets the pool to zero.
    """
    post = order.post
    area = area_for_post(post)
    if area is None:
        return

    union = post.location

    pool, created = PendingPool.objects.select_for_update().get_or_create(
        area=area,
        union=union,
        product_type=post.product_type,
        defaults={'pending_quantity_kg': order.quantity_kg},
    )
    if not created:
        pool.pending_quantity_kg += order.quantity_kg
        pool.save(update_fields=['pending_quantity_kg'])

    if pool.pending_quantity_kg >= area.threshold_kg:
        build_batch(area, union, post.product_type)
        pool.pending_quantity_kg = Decimal('0')
        pool.save(update_fields=['pending_quantity_kg'])


def process_new_order(order):
    """Helper to be called after an Order is created."""
    with transaction.atomic():
        add_order_to_pool(order)