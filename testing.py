#!/usr/bin/env python
"""
Comprehensive end-to-end test for the Nobanno backend.

Runs the FULL API flow over Django's in-process HTTP client (no live server
needed), including order placement, DEMO PAY (bypassing the real bKash gateway),
batch delivery and reviews. A throwaway PostgreSQL test database is created,
used and dropped, so the real database is never touched.

Usage:
    .venv/bin/python testing.py
"""
import os
import sys
from decimal import Decimal

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nobanno.settings')

import django
django.setup()

from django.test.runner import DiscoverRunner
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from api.models import (
    BangladeshLocation, ProductType, Area, Payment, Order, Batch,
)

User = get_user_model()

# --------------------------------------------------------------------------
# tiny test harness
# --------------------------------------------------------------------------
_passed = 0
_failed = 0


def check(name, cond, extra=''):
    global _passed, _failed
    tag = 'PASS' if cond else 'FAIL'
    if cond:
        _passed += 1
    else:
        _failed += 1
    print(f"[{tag}] {name}" + (f"  -> {extra}" if extra else ""))
    return cond


def summary():
    print("\n" + "=" * 60)
    print(f"RESULT: {_passed} passed, {_failed} failed")
    return 0 if _failed == 0 else 1


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
def seed_geo():
    """Division -> District -> Upazila -> Union chain via ORM (locations are read-only via API)."""
    division = BangladeshLocation.objects.create(
        geo_id=9001, name_en='TestDiv', name_bn='টেস্ট', level='division')
    district = BangladeshLocation.objects.create(
        geo_id=9101, name_en='TestDist', name_bn='জেলা', level='district',
        parent=division, latitude=23.8103, longitude=90.4125)
    upazila = BangladeshLocation.objects.create(
        geo_id=9201, name_en='TestUpazila', name_bn='উপজেলা', level='upazila', parent=district)
    union = BangladeshLocation.objects.create(
        geo_id=9301, name_en='TestUnion', name_bn='ইউনিয়ন', level='union', parent=upazila)
    return division, district, upazila, union


def main():
    print("Creating throwaway PostgreSQL test database...")
    runner = DiscoverRunner(verbosity=0, interactive=False)
    old_config = runner.setup_databases()
    client = APIClient()

    try:
        # ---- geo ----
        _div, _dist, upazila, union = seed_geo()
        check("geo chain seeded", BangladeshLocation.objects.count() >= 4)

        # ---- admin (superuser) ----
        admin = User.objects.create_superuser(
            username='tadmin', email='tadmin@test.com', password='adminpass123', role='admin')
        check("admin superuser created", admin.is_staff)

        # ---- register via API ----
        r = client.post('/api/auth/register/', {
            'username': 'tfarmer', 'email': 'tfarmer@test.com', 'password': 'pass12345',
            'role': 'farmer', 'name': 'Farmer One', 'phone_number': '01710000001',
            'location': union.id,
        }, format='json')
        check("register farmer", r.status_code == 201, f"status={r.status_code}")
        farmer_token = r.data.get('token')

        r = client.post('/api/auth/register/', {
            'username': 'tcust', 'email': 'tcust@test.com', 'password': 'pass12345',
            'role': 'customer', 'name': 'Customer One', 'phone_number': '01710000002',
            'location': union.id,
        }, format='json')
        check("register customer", r.status_code == 201, f"status={r.status_code}")
        cust_token = r.data.get('token')

        r = client.post('/api/auth/register/', {
            'username': 'tdlvr', 'email': 'tdlvr@test.com', 'password': 'pass12345',
            'role': 'deliveryman', 'name': 'Delivery One', 'phone_number': '01710000003',
            'location': union.id,
        }, format='json')
        check("register deliveryman", r.status_code == 201, f"status={r.status_code}")
        dly_token = r.data.get('token')

        # registration without location should fail
        r = client.post('/api/auth/register/', {
            'username': 'noloc', 'email': 'noloc@test.com', 'password': 'pass12345',
            'role': 'farmer', 'name': 'No Loc', 'phone_number': '01710000004',
        }, format='json')
        check("register requires location", r.status_code == 400, f"status={r.status_code}")

        # ---- login via email ----
        r = client.post('/api/auth/login/', {'email_or_phone': 'tadmin@test.com', 'password': 'adminpass123'}, format='json')
        check("admin login by email", r.status_code == 200 and 'token' in r.data, f"status={r.status_code}")
        admin_token = r.data.get('token')

        # ---- login by phone (rotates token) ----
        r = client.post('/api/auth/login/', {'email_or_phone': '01710000002', 'password': 'pass12345'}, format='json')
        check("customer login by phone", r.status_code == 200 and 'token' in r.data)
        cust_token = r.data.get('token')

        # ---- admin: product type + area ----
        client.credentials(HTTP_AUTHORIZATION='Token ' + admin_token)
        r = client.post('/api/product-types/', {'name_en': 'Rice', 'name_bn': 'চাল'}, format='json')
        check("admin creates product type", r.status_code == 201, f"status={r.status_code}")
        pt_id = r.data.get('id')

        r = client.post('/api/areas/', {
            'name': 'Test Area', 'threshold_kg': '100.00', 'upazilas': [upazila.id],
        }, format='json')
        check("admin creates area", r.status_code == 201, f"status={r.status_code}")
        area_id = r.data.get('id')

        # non-admin cannot create product type
        client.credentials(HTTP_AUTHORIZATION='Token ' + farmer_token)
        r = client.post('/api/product-types/', {'name_en': 'X', 'name_bn': 'Y'}, format='json')
        check("farmer cannot create product type", r.status_code == 403, f"status={r.status_code}")

        # ---- farmer: create post ----
        r = client.post('/api/posts/', {
            'title': 'Fresh Rice', 'product_type': pt_id,
            'total_weight_kg': '500.00', 'price_per_kg': '50.00',
            'location': union.id, 'collection_point_address': 'Village Bazar',
        }, format='json')
        check("farmer creates post", r.status_code == 201, f"status={r.status_code}")
        post_id = r.data.get('id')
        post_location = r.data.get('location')
        check("post location flattened", isinstance(post_location, dict) and post_location.get('union') == 'TestUnion')
        area_on_post = r.data.get('area')
        check("post linked to area", area_on_post and area_on_post.get('id') == area_id)

        # post without location must fail
        r = client.post('/api/posts/', {
            'title': 'Bad', 'product_type': pt_id, 'total_weight_kg': '10', 'price_per_kg': '5',
        }, format='json')
        check("post requires location", r.status_code == 400, f"status={r.status_code}")

        # ---- customer: order (unauth should be rejected) ----
        client.credentials()
        r = client.post('/api/orders/', {'post': post_id, 'quantity_kg': '10', 'delivery_address': 'Dhaka'}, format='json')
        check("order requires auth", r.status_code in (401, 403), f"status={r.status_code}")

        client.credentials(HTTP_AUTHORIZATION='Token ' + cust_token)
        # insufficient stock
        r = client.post('/api/orders/', {'post': post_id, 'quantity_kg': '9999', 'delivery_address': 'Dhaka'}, format='json')
        check("order insufficient stock rejected", r.status_code == 400, f"status={r.status_code}")

        # single order
        r = client.post('/api/orders/', {'post': post_id, 'quantity_kg': '10', 'delivery_address': 'Dhaka'}, format='json')
        check("single order created", r.status_code == 201, f"status={r.status_code}")
        order1_id = r.data.get('id')
        check("single order is pending", r.data.get('status') == 'pending')

        # ---- DEMO PAY (bypasses real bKash) ----
        payload = {
            'items': [
                {'post': post_id, 'quantity_kg': '60.00'},
                {'post': post_id, 'quantity_kg': '50.00'},
            ],
            'delivery_address': '456 Test Ave, Dhaka',
        }
        r = client.post('/api/payments/demo/', payload, format='json')
        check("demo pay creates orders", r.status_code == 201, f"status={r.status_code}")

        # stock decremented by 60+50 = 110
        post_obj = client.get(f'/api/posts/{post_id}/').data
        check("stock decremented by 110", Decimal(post_obj['total_weight_kg']) == Decimal('380.00'),
              f"remaining={post_obj['total_weight_kg']}")

        # every demo-paid order marked success + paid (demo created 2 orders: 60 + 50)
        paid_orders = Order.objects.filter(customer__username='tcust', bkash_payment_status='success')
        check("demo orders paid", paid_orders.count() == 2, f"count={paid_orders.count()}")
        check("demo payments recorded", Payment.objects.filter(status='success').count() == 2)

        # batch created when threshold reached
        batch_count = Batch.objects.filter(area_id=area_id).count()
        check("batch auto-created from pool", batch_count >= 1, f"batches={batch_count}")
        batch = Batch.objects.filter(area_id=area_id).order_by('-id').first()

        # ---- deliveryman: service areas, accept, deliver ----
        client.credentials(HTTP_AUTHORIZATION='Token ' + dly_token)
        r = client.post('/api/deliveryman/service-areas/', {'service_areas': [area_id]}, format='json')
        check("deliveryman sets service areas", r.status_code == 200 and r.data.get('service_areas') == [area_id])

        r = client.get('/api/batches/available/')
        available_ids = [b['id'] for b in r.data]
        check("pending batch visible to deliveryman", batch.id in available_ids)

        r = client.post(f'/api/batches/{batch.id}/accept/')
        check("deliveryman accepts batch", r.status_code == 200, f"status={r.status_code}")

        r = client.post(f'/api/batches/{batch.id}/deliver/')
        check("deliveryman delivers batch", r.status_code == 200, f"status={r.status_code}")
        batch.refresh_from_db()
        check("batch status delivered", batch.status == 'delivered')

        # all member orders (the single + the 2 demo-paid ones) now completed
        member_total = Order.objects.filter(batch_items__batch=batch).count()
        member_completed = Order.objects.filter(batch_items__batch=batch, status='completed').count()
        check("batch orders completed", member_total == 3 and member_completed == 3,
              f"completed={member_completed}/{member_total}")

        # ---- customer: review the product ----
        client.credentials(HTTP_AUTHORIZATION='Token ' + cust_token)
        r = client.post('/api/reviews/', {'post': post_id, 'rating': 5, 'comment': 'Great rice!'}, format='json')
        check("customer reviews completed product", r.status_code == 201, f"status={r.status_code}")

        # duplicate review blocked
        r = client.post('/api/reviews/', {'post': post_id, 'rating': 4, 'comment': 'again'}, format='json')
        check("duplicate review blocked", r.status_code == 400, f"status={r.status_code}")

        # ---- farmer wallet ----
        client.credentials(HTTP_AUTHORIZATION='Token ' + farmer_token)
        r = client.get('/api/farmer/wallet/')
        check("farmer wallet endpoint", r.status_code == 200, f"status={r.status_code}")
        check("farmer wallet has completed earnings",
              Decimal(r.data['total_earnings']) > 0, f"earnings={r.data['total_earnings']}")

        # ---- admin analytics ----
        client.credentials(HTTP_AUTHORIZATION='Token ' + admin_token)
        r = client.get('/api/admin/analytics/')
        check("admin analytics endpoint", r.status_code == 200, f"status={r.status_code}")
        check("analytics GMV reflects demo pay", Decimal(r.data['metrics']['completed_gmv']) > 0)

        # ---- locations cascade ----
        client.credentials()
        r = client.get('/api/locations/?level=union&parent_id=' + str(upazila.id))
        check("locations union lookup", r.status_code == 200 and len(r.data) == 1)

        # ---- profile + logout ----
        client.credentials(HTTP_AUTHORIZATION='Token ' + cust_token)
        r = client.get('/api/auth/profile/')
        check("customer profile", r.status_code == 200 and r.data.get('username') == 'tcust')
        r = client.post('/api/auth/logout/')
        check("logout", r.status_code == 200)

        return summary()
    finally:
        runner.teardown_databases(old_config)
        print("PostgreSQL test database dropped.")


if __name__ == '__main__':
    sys.exit(main())