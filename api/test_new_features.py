from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.authtoken.models import Token
from django.contrib.auth import get_user_model
from .services import add_order_to_pool
from .models import (
    Order, Post, ProductType, BangladeshLocation, Area,
    PendingPool, Batch, Payment, Notification,
)

User = get_user_model()


def make_geo(prefix_ids=1):
    division = BangladeshLocation.objects.create(
        geo_id=prefix_ids, name_en='TestDiv', name_bn='টিডি', level='division')
    district = BangladeshLocation.objects.create(
        geo_id=prefix_ids + 1, name_en='TestDist', name_bn='টি', level='district', parent=division)
    upazila = BangladeshLocation.objects.create(
        geo_id=prefix_ids + 2, name_en='TestUpazila', name_bn='টিউ', level='upazila', parent=district)
    union = BangladeshLocation.objects.create(
        geo_id=prefix_ids + 3, name_en='TestUnion', name_bn='টু', level='union', parent=upazila)
    return division, district, upazila, union


# ── Item 1: Per-KG vs per-piece (quantity_type) ─────────────────────────────

class PerPieceUnitTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        _d, _di, _u, self.union = make_geo(prefix_ids=61)
        self.product_type = ProductType.objects.create(name_en='Chicken', name_bn='মুরগি')
        self.farmer = User.objects.create_user(
            username='piecefarmer', email='pf@test.com', password='testpass123',
            role='farmer', name='Piece Farmer', location=self.union,
        )
        self.f_token, _ = Token.objects.get_or_create(user=self.farmer)
        self.customer = User.objects.create_user(
            username='piececustomer', email='pc@test.com', password='testpass123',
            role='customer', name='Piece Customer', location=self.union,
        )
        self.c_token, _ = Token.objects.get_or_create(user=self.customer)

    def test_farmer_creates_piece_post_requires_est_weight(self):
        r = self.client.post('/api/posts/', {
            'title': 'Fresh Chicken', 'product_type': self.product_type.id,
            'quantity_type': 'piece', 'total_weight_kg': '50', 'price_per_kg': '200',
            'location': self.union.id,
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.f_token.key}')
        self.assertEqual(r.status_code, 400)
        self.assertIn('est_weight_kg', r.data)

    def test_farmer_creates_piece_post_success(self):
        r = self.client.post('/api/posts/', {
            'title': 'Fresh Chicken', 'product_type': self.product_type.id,
            'quantity_type': 'piece', 'total_weight_kg': '50', 'price_per_kg': '200',
            'est_weight_kg': '1.5', 'location': self.union.id,
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.f_token.key}')
        self.assertEqual(r.status_code, 201, r.data)
        post = Post.objects.get(id=r.data['id'])
        self.assertEqual(post.quantity_type, 'piece')
        # effective stock in kg = 50 pieces * 1.5kg = 75kg
        self.assertEqual(post.effective_weight_kg, Decimal('75.00'))

    def test_piece_order_snapshots_unit_and_pools_by_effective_kg(self):
        post = Post.objects.create(
            farmer=self.farmer, title='Chicken', product_type=self.product_type,
            quantity_type='piece', total_weight_kg=Decimal('100'),
            price_per_kg=Decimal('200'), est_weight_kg=Decimal('1.5'), location=self.union,
        )
        area = Area.objects.create(name='Test Area', threshold_kg=Decimal('100.00'))
        area.upazilas.add(self.union.parent)

        r = self.client.post('/api/orders/', {
            'post': post.id, 'quantity_kg': '60', 'delivery_address': 'Dhaka',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.assertEqual(r.status_code, 201, r.data)
        order = Order.objects.get(id=r.data['id'])
        self.assertEqual(order.quantity_type, 'piece')
        self.assertEqual(order.est_weight_kg, Decimal('1.5'))
        # total_paid = 60 pieces * 200 = 12000
        self.assertEqual(order.total_paid, Decimal('12000.00'))
        # effective weight for pooling = 60 * 1.5 = 90kg
        self.assertEqual(order.effective_weight_kg, Decimal('90.00'))
        # only approved orders enter the pool
        order.status = 'approved'; order.save(update_fields=['status'])
        add_order_to_pool(order)
        pool = PendingPool.objects.get(area=area, union=self.union, product_type=self.product_type)
        self.assertEqual(pool.pending_quantity_kg, Decimal('90.00'))

        # +10 more pieces -> pool 105kg >= 100 threshold -> batch with 105kg
        r2 = self.client.post('/api/orders/', {
            'post': post.id, 'quantity_kg': '10', 'delivery_address': 'Dhaka',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.assertEqual(r2.status_code, 201, r2.data)
        order2 = Order.objects.get(id=r2.data['id'])
        order2.status = 'approved'; order2.save(update_fields=['status'])
        add_order_to_pool(order2)
        pool.refresh_from_db()
        self.assertEqual(pool.pending_quantity_kg, Decimal('0'))
        batch = Batch.objects.first()
        self.assertEqual(batch.total_quantity_kg, Decimal('105.00'))


# ── Item 2: Admin farmer-due settlement checkbox ────────────────────────────

class SettlementDueTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        _d, _di, _u, self.union = make_geo(prefix_ids=71)
        self.admin = User.objects.create_user(
            username='adminsettle', email='admin@test.com', password='testpass123',
            role='admin', is_staff=True, name='Admin',
        )
        self.a_token, _ = Token.objects.get_or_create(user=self.admin)
        self.farmer = User.objects.create_user(
            username='farmsettle', email='fs@test.com', password='testpass123',
            role='farmer', name='Farm Settle', location=self.union,
        )
        self.customer = User.objects.create_user(
            username='custsettle', email='cs@test.com', password='testpass123',
            role='customer', name='Cust Settle', location=self.union,
        )
        self.post = Post.objects.create(
            farmer=self.farmer, title='Rice', total_weight_kg=Decimal('100'),
            price_per_kg=Decimal('50'), location=self.union,
        )
        self.order = Order.objects.create(
            customer=self.customer, post=self.post, quantity_kg=Decimal('10'),
            total_paid=Decimal('500.00'), platform_fee=Decimal('50.00'),
            farmer_payout=Decimal('450.00'), delivery_address='Dhaka',
        )
        self.payment = Payment.objects.create(
            user=self.customer, order=self.order, amount=Decimal('500.00'),
            transaction_id='SETTLE-001', status='success', gateway='bkash',
            settlement_appended=True,
        )

    def test_admin_lists_unpaid_dues(self):
        r = self.client.get('/api/payments/settlement/dues/',
                            HTTP_AUTHORIZATION=f'Token {self.a_token.key}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 1)
        self.assertEqual(r.data[0]['order_id'], self.order.id)
        self.assertEqual(Decimal(r.data[0]['payout_amount']), Decimal('450.00'))
        self.assertFalse(r.data[0]['settlement_paid'])

    def test_non_admin_forbidden(self):
        cust_token, _ = Token.objects.get_or_create(user=self.customer)
        r = self.client.get('/api/payments/settlement/dues/',
                            HTTP_AUTHORIZATION=f'Token {cust_token.key}')
        self.assertEqual(r.status_code, 403)

    def test_admin_marks_due_paid(self):
        r = self.client.post('/api/payments/settlement/dues/', {
            'payment_id': self.payment.id, 'paid': True,
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.a_token.key}')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['settlement_paid'])
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.settlement_paid)
        self.assertIsNotNone(self.payment.settlement_paid_at)

        # Now no unpaid dues remain
        r2 = self.client.get('/api/payments/settlement/dues/',
                             HTTP_AUTHORIZATION=f'Token {self.a_token.key}')
        self.assertEqual(len(r2.data), 0)

    def test_admin_unmark_paid(self):
        self.payment.settlement_paid = True
        self.payment.save()
        r = self.client.post('/api/payments/settlement/dues/', {
            'payment_id': self.payment.id, 'paid': False,
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.a_token.key}')
        self.assertEqual(r.status_code, 200)
        self.payment.refresh_from_db()
        self.assertFalse(self.payment.settlement_paid)


# ── Item 3: Real-time delivery notifications ────────────────────────────────

class NotificationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        _d, _di, _u, self.union = make_geo(prefix_ids=81)
        self.product_type = ProductType.objects.create(name_en='Rice', name_bn='চাল')
        self.area = Area.objects.create(name='Test Area', threshold_kg=Decimal('100.00'))
        self.area.upazilas.add(self.union.parent)

        self.farmer = User.objects.create_user(
            username='nfarmer', email='nf@test.com', password='testpass123',
            role='farmer', name='N Farmer', location=self.union,
        )
        self.customer = User.objects.create_user(
            username='ncustomer', email='nc@test.com', password='testpass123',
            role='customer', name='N Customer', location=self.union,
        )
        self.c_token, _ = Token.objects.get_or_create(user=self.customer)
        self.deliveryman = User.objects.create_user(
            username='ndelivery', email='nd@test.com', password='testpass123',
            role='deliveryman', name='N Delivery', location=self.union,
        )
        self.d_token, _ = Token.objects.get_or_create(user=self.deliveryman)

        self.post = Post.objects.create(
            farmer=self.farmer, title='Rice', product_type=self.product_type,
            total_weight_kg=Decimal('10000'), price_per_kg=Decimal('50'), location=self.union,
        )
        # Create orders to trigger a batch.
        self.client.post('/api/orders/', {'post': self.post.id, 'quantity_kg': '60', 'delivery_address': 'Dhaka'},
                         format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.client.post('/api/orders/', {'post': self.post.id, 'quantity_kg': '50', 'delivery_address': 'Dhaka'},
                         format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.batch = Batch.objects.first()
        self.deliveryman.service_areas = [self.area.id]
        self.deliveryman.save(update_fields=['service_areas'])

    def _deliver_batch(self):
        self.client.post(f'/api/batches/{self.batch.id}/accept/', HTTP_AUTHORIZATION=f'Token {self.d_token.key}')
        self.client.post(f'/api/batches/{self.batch.id}/pick_up/', HTTP_AUTHORIZATION=f'Token {self.d_token.key}')
        self.client.post(f'/api/batches/{self.batch.id}/in_transit/', HTTP_AUTHORIZATION=f'Token {self.d_token.key}')
        self.client.post(f'/api/batches/{self.batch.id}/verify_payment/', HTTP_AUTHORIZATION=f'Token {self.d_token.key}')
        self.client.post(f'/api/batches/{self.batch.id}/deliver/', HTTP_AUTHORIZATION=f'Token {self.d_token.key}')

    def test_batch_events_create_notifications(self):
        self.assertEqual(Notification.objects.count(), 0)
        self._deliver_batch()
        # Customers + farmers + deliveryman notified on each event.
        # 5 events x 3 users = 15 notifications.
        self.assertEqual(Notification.objects.count(), 15)

    def test_customer_can_list_and_mark_read(self):
        self._deliver_batch()
        r = self.client.get('/api/notifications/', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.assertEqual(r.status_code, 200)
        my_notifs = r.data
        self.assertGreaterEqual(len(my_notifs), 5)
        types = {n['notification_type'] for n in my_notifs}
        self.assertTrue({'batch_assigned', 'batch_picked_up', 'batch_in_transit',
                         'payment_verified', 'batch_delivered'}.issubset(types))

        uc = self.client.get('/api/notifications/unread_count/', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.assertEqual(uc.data['unread_count'], len(my_notifs))

        first_id = my_notifs[0]['id']
        rr = self.client.post(f'/api/notifications/{first_id}/read/', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.assertEqual(rr.status_code, 200)
        self.assertTrue(rr.data['is_read'])

        ra = self.client.post('/api/notifications/read_all/', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.assertEqual(ra.status_code, 200)
        uc2 = self.client.get('/api/notifications/unread_count/', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.assertEqual(uc2.data['unread_count'], 0)

    def test_notifications_are_scoped_to_user(self):
        other = User.objects.create_user(
            username='other', email='other@test.com', password='testpass123',
            role='customer', location=self.union,
        )
        other_token, _ = Token.objects.get_or_create(user=other)
        self._deliver_batch()
        r = self.client.get('/api/notifications/', HTTP_AUTHORIZATION=f'Token {other_token.key}')
        self.assertEqual(len(r.data), 0)


# ── Item 4: Bangla duplicate-registration message ───────────────────────────

class DuplicateRegistrationWordingTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        _d, _di, _u, self.union = make_geo(prefix_ids=91)

    def _payload(self, username, email, phone):
        return {
            'username': username, 'email': email, 'password': 'testpass123',
            'role': 'customer', 'name': 'John', 'phone_number': phone,
            'location': self.union.id,
        }

    def test_duplicate_email_returns_bangla_message(self):
        self.client.post('/api/auth/register/', self._payload('u1', 'dup@test.com', '01700000001'),
                         format='json')
        r = self.client.post('/api/auth/register/', self._payload('u2', 'dup@test.com', '01700000002'),
                             format='json')
        self.assertEqual(r.status_code, 400)
        msg = str(r.data.get('email', ''))
        self.assertIn('নতুন ইমেইল', msg)

    def test_duplicate_phone_returns_bangla_message(self):
        self.client.post('/api/auth/register/', self._payload('u3', 'dup1@test.com', '01700000003'),
                         format='json')
        r = self.client.post('/api/auth/register/', self._payload('u4', 'dup2@test.com', '01700000003'),
                             format='json')
        self.assertEqual(r.status_code, 400)
        msg = str(r.data.get('phone_number', ''))
        self.assertIn('নতুন', msg)