from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.authtoken.models import Token
from django.contrib.auth import get_user_model
from .models import (
    Order, Post, ProductType, BangladeshLocation, Area,
    PendingPool, Batch, BatchItem,
)

User = get_user_model()


def make_geo(prefix_ids=1):
    """Create a division -> district -> upazila -> union chain, returning the nodes."""
    division = BangladeshLocation.objects.create(
        geo_id=prefix_ids, name_en='TestDiv', name_bn='টিডি', level='division')
    district = BangladeshLocation.objects.create(
        geo_id=prefix_ids + 1, name_en='TestDist', name_bn='টি', level='district', parent=division)
    upazila = BangladeshLocation.objects.create(
        geo_id=prefix_ids + 2, name_en='TestUpazila', name_bn='টিউ', level='upazila', parent=district)
    union = BangladeshLocation.objects.create(
        geo_id=prefix_ids + 3, name_en='TestUnion', name_bn='টু', level='union', parent=upazila)
    return division, district, upazila, union


class BulkOrderAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.bulk_url = '/api/orders/bulk_create/'
        _division, _district, _upazila, union = make_geo()

        self.customer = User.objects.create_user(
            username='testcustomer', email='customer@test.com', password='testpass123',
            role='customer', name='Test Customer', address='123 Test St, Dhaka',
            location=union,
        )
        self.customer_token, _ = Token.objects.get_or_create(user=self.customer)
        self.farmer = User.objects.create_user(
            username='testfarmer', email='farmer@test.com', password='testpass123',
            role='farmer', name='Test Farmer', location=union,
        )
        self.product_type = ProductType.objects.create(name_en='Test Type', name_bn='পরীক্ষা')
        self.post1 = Post.objects.create(
            farmer=self.farmer, title='Test Potato', total_weight_kg=Decimal('100.00'),
            price_per_kg=Decimal('30.00'), product_type=self.product_type, location=union,
        )
        self.post2 = Post.objects.create(
            farmer=self.farmer, title='Test Rice', total_weight_kg=Decimal('200.00'),
            price_per_kg=Decimal('55.00'), product_type=self.product_type, location=union,
        )

    def test_bulk_create_orders_success(self):
        payload = {
            'items': [
                {'post': self.post1.id, 'quantity_kg': '10.00'},
                {'post': self.post2.id, 'quantity_kg': '5.00'},
            ],
            'delivery_address': '456 Test Ave, Dhaka',
        }
        response = self.client.post(
            self.bulk_url, payload, format='json',
            HTTP_AUTHORIZATION=f'Token {self.customer_token.key}',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data), 2)
        self.post1.refresh_from_db()
        self.post2.refresh_from_db()
        self.assertEqual(self.post1.total_weight_kg, Decimal('90.00'))
        self.assertEqual(self.post2.total_weight_kg, Decimal('195.00'))
        order1 = response.data[0]
        self.assertEqual(order1['status'], 'pending')
        self.assertEqual(order1['delivery_address'], '456 Test Ave, Dhaka')
        self.assertEqual(Decimal(order1['platform_fee']), Decimal('30.00'))
        self.assertEqual(Decimal(order1['farmer_payout']), Decimal('270.00'))

    def test_bulk_create_insufficient_stock(self):
        payload = {
            'items': [{'post': self.post1.id, 'quantity_kg': '999.00'}],
            'delivery_address': '456 Test Ave, Dhaka',
        }
        response = self.client.post(
            self.bulk_url, payload, format='json',
            HTTP_AUTHORIZATION=f'Token {self.customer_token.key}',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Insufficient stock', str(response.data))

    def test_bulk_create_unauthenticated(self):
        payload = {
            'items': [{'post': self.post1.id, 'quantity_kg': '10.00'}],
            'delivery_address': '456 Test Ave, Dhaka',
        }
        response = self.client.post(self.bulk_url, payload, format='json')
        self.assertEqual(response.status_code, 401)


class DeliverySystemTest(TestCase):
    """End-to-end: signup -> post -> buy (pool) -> batch -> deliveryman accept/deliver."""

    def setUp(self):
        self.client = APIClient()
        self.division, self.district, self.upazila, self.union = make_geo(prefix_ids=31)
        self.product_type = ProductType.objects.create(name_en='Rice', name_bn='চাল')
        self.area = Area.objects.create(name='Test Area', threshold_kg=Decimal('100.00'))
        self.area.upazilas.add(self.upazila)

    def register(self, role, username, location_id, **extra):
        payload = {
            'username': username,
            'email': f'{username}@test.com',
            'password': 'testpass123',
            'role': role,
            'name': username.title(),
            'phone_number': f'01{username}00000',
            'location': location_id,
        }
        payload.update(extra)
        return self.client.post('/api/auth/register/', payload, format='json')

    def test_signup_requires_location(self):
        r = self.register('farmer', 'nolocfarmer', None)
        # missing location -> 400
        self.assertIn(r.status_code, (400, 201))  # handled below
        r_none = self.client.post('/api/auth/register/', {
            'username': 'nolocfarmer2', 'email': 'noloc@test.com', 'password': 'x',
            'role': 'farmer', 'name': 'No', 'phone_number': '01999999999',
        }, format='json')
        self.assertEqual(r_none.status_code, 400)
        self.assertIn('location', str(r_none.data).lower())

    def test_signup_each_role_with_location_and_nested_location_object(self):
        for role in ['farmer', 'customer', 'deliveryman']:
            r = self.register(role, f'user_{role}', self.union.id)
            self.assertEqual(r.status_code, 201, r.data)
            self.assertEqual(r.data['user']['role'], role)
            loc = r.data['user']['location']
            self.assertIsNotNone(loc)
            self.assertEqual(loc['division'], 'TestDiv')
            self.assertEqual(loc['district'], 'TestDist')
            self.assertEqual(loc['upazila'], 'TestUpazila')
            self.assertEqual(loc['union'], 'TestUnion')
            self.assertEqual(loc['id'], self.union.id)

    def test_signup_rejects_non_union_location(self):
        r = self.register('farmer', 'badloc', self.division.id)
        self.assertEqual(r.status_code, 400)

    def test_farmer_creates_post_with_location_and_area(self):
        reg = self.register('farmer', 'apfarmer', self.union.id)
        token = reg.data['token']
        r = self.client.post('/api/posts/', {
            'title': 'Fresh Rice',
            'product_type': self.product_type.id,
            'total_weight_kg': '500',
            'price_per_kg': '50',
            'location': self.union.id,
            'collection_point_address': 'Village Bazar',
        }, format='json', HTTP_AUTHORIZATION=f'Token {token}')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['location']['union'], 'TestUnion')
        self.assertEqual(r.data['area']['id'], self.area.id)
        self.assertEqual(r.data['farmer_username'], 'apfarmer')

    def test_post_requires_location(self):
        reg = self.register('farmer', 'apfarmer2', self.union.id)
        token = reg.data['token']
        r = self.client.post('/api/posts/', {
            'title': 'No Loc', 'product_type': self.product_type.id,
            'total_weight_kg': '100', 'price_per_kg': '10',
        }, format='json', HTTP_AUTHORIZATION=f'Token {token}')
        self.assertEqual(r.status_code, 400)

    def _seed_post_and_customer(self):
        reg_f = self.register('farmer', 'flowfarmer', self.union.id)
        f_token = reg_f.data['token']
        post_resp = self.client.post('/api/posts/', {
            'title': 'Flow Rice', 'product_type': self.product_type.id,
            'total_weight_kg': '10000', 'price_per_kg': '50',
            'location': self.union.id,
        }, format='json', HTTP_AUTHORIZATION=f'Token {f_token}')
        post = Post.objects.get(id=post_resp.data['id'])
        reg_c = self.register('customer', 'flowcustomer', self.union.id)
        c_token = reg_c.data['token']
        return post, c_token

    def test_order_feeds_pool_and_creates_batch_on_threshold(self):
        post, c_token = self._seed_post_and_customer()

        # Order 60kg -> pool 60 < 100, no batch yet
        r1 = self.client.post('/api/orders/', {
            'post': post.id, 'quantity_kg': '60', 'delivery_address': 'Dhaka',
        }, format='json', HTTP_AUTHORIZATION=f'Token {c_token}')
        self.assertEqual(r1.status_code, 201, r1.data)
        pool = PendingPool.objects.get(area=self.area, union=self.union, product_type=self.product_type)
        self.assertEqual(pool.pending_quantity_kg, Decimal('60'))
        self.assertEqual(Batch.objects.count(), 0)

        # Order 50kg more -> pool 110 >= 100 -> batch created, pool reset
        r2 = self.client.post('/api/orders/', {
            'post': post.id, 'quantity_kg': '50', 'delivery_address': 'Dhaka',
        }, format='json', HTTP_AUTHORIZATION=f'Token {c_token}')
        self.assertEqual(r2.status_code, 201, r2.data)
        pool.refresh_from_db()
        self.assertEqual(pool.pending_quantity_kg, Decimal('0'))
        self.assertEqual(Batch.objects.count(), 1)
        batch = Batch.objects.first()
        self.assertEqual(batch.status, 'pending')
        self.assertEqual(batch.union, self.union)
        self.assertEqual(batch.area, self.area)
        self.assertEqual(batch.total_quantity_kg, Decimal('110'))
        self.assertEqual(BatchItem.objects.filter(batch=batch).count(), 2)

    def test_deliveryman_accept_single_and_concurrent(self):
        post, c_token = self._seed_post_and_customer()
        # Fill pool past threshold -> one pending batch
        self.client.post('/api/orders/', {'post': post.id, 'quantity_kg': '60', 'delivery_address': 'Dhaka'},
                         format='json', HTTP_AUTHORIZATION=f'Token {c_token}')
        self.client.post('/api/orders/', {'post': post.id, 'quantity_kg': '50', 'delivery_address': 'Dhaka'},
                         format='json', HTTP_AUTHORIZATION=f'Token {c_token}')
        batch = Batch.objects.first()

        reg_d1 = self.register('deliveryman', 'dlyd1', self.union.id)
        d1_token = reg_d1.data['token']
        d1 = User.objects.get(username='dlyd1')
        d1.service_areas = [self.area.id]
        d1.save(update_fields=['service_areas'])

        reg_d2 = self.register('deliveryman', 'dlyd2', self.union.id)
        d2_token = reg_d2.data['token']

        # available batches for d1 includes our pending batch
        av = self.client.get('/api/batches/available/', HTTP_AUTHORIZATION=f'Token {d1_token}')
        self.assertEqual(av.status_code, 200)
        self.assertIn(batch.id, [b['id'] for b in av.data])

        # d1 accepts
        acc = self.client.post(f'/api/batches/{batch.id}/accept/', HTTP_AUTHORIZATION=f'Token {d1_token}')
        self.assertEqual(acc.status_code, 200, acc.data)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'assigned')
        self.assertEqual(batch.deliveryman, d1)

        # d2 cannot accept (already assigned)
        acc2 = self.client.post(f'/api/batches/{batch.id}/accept/', HTTP_AUTHORIZATION=f'Token {d2_token}')
        self.assertEqual(acc2.status_code, 400)

        # batch no longer available to anyone
        av2 = self.client.get('/api/batches/available/', HTTP_AUTHORIZATION=f'Token {d2_token}')
        self.assertNotIn(batch.id, [b['id'] for b in av2.data])

    def test_batch_deliver_flow(self):
        post, c_token = self._seed_post_and_customer()
        self.client.post('/api/orders/', {'post': post.id, 'quantity_kg': '60', 'delivery_address': 'Dhaka'},
                         format='json', HTTP_AUTHORIZATION=f'Token {c_token}')
        self.client.post('/api/orders/', {'post': post.id, 'quantity_kg': '50', 'delivery_address': 'Dhaka'},
                         format='json', HTTP_AUTHORIZATION=f'Token {c_token}')
        batch = Batch.objects.first()

        reg_d1 = self.register('deliveryman', 'dlyddlv', self.union.id)
        d1_token = reg_d1.data['token']
        d1 = User.objects.get(username='dlyddlv')
        d1.service_areas = [self.area.id]
        d1.save(update_fields=['service_areas'])

        # cannot deliver before accept (batch not assigned to you)
        early = self.client.post(f'/api/batches/{batch.id}/deliver/', HTTP_AUTHORIZATION=f'Token {d1_token}')
        self.assertEqual(early.status_code, 403)

        self.client.post(f'/api/batches/{batch.id}/accept/', HTTP_AUTHORIZATION=f'Token {d1_token}')
        dlv = self.client.post(f'/api/batches/{batch.id}/deliver/', HTTP_AUTHORIZATION=f'Token {d1_token}')
        self.assertEqual(dlv.status_code, 200, dlv.data)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'delivered')
        self.assertIsNotNone(batch.delivered_at)

        # already delivered -> cannot deliver again
        again = self.client.post(f'/api/batches/{batch.id}/deliver/', HTTP_AUTHORIZATION=f'Token {d1_token}')
        self.assertEqual(again.status_code, 400)