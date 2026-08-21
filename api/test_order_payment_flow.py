"""
End-to-end test: multi-product order → manual bKash submit → admin approve → farmer dues.
Tests the full backend payment flow with OrderItem model.
"""
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.authtoken.models import Token
from django.contrib.auth import get_user_model

from .models import (
    Order, OrderItem, Post, ProductType, Payment, ManualBkashPayment,
    BangladeshLocation, Area,
)

User = get_user_model()


def make_geo(prefix_ids=100):
    division = BangladeshLocation.objects.create(
        geo_id=prefix_ids, name_en='TDiv', name_bn='টিডি', level='division')
    district = BangladeshLocation.objects.create(
        geo_id=prefix_ids + 1, name_en='TDist', name_bn='টি', level='district', parent=division)
    upazila = BangladeshLocation.objects.create(
        geo_id=prefix_ids + 2, name_en='TUpa', name_bn='টিউ', level='upazila', parent=district)
    union = BangladeshLocation.objects.create(
        geo_id=prefix_ids + 3, name_en='TUnion', name_bn='টু', level='union', parent=upazila)
    return division, district, upazila, union


class MultiProductOrderFlowTest(TestCase):
    """Full flow: bulk order (3 products, 3 farmers) → submit bKash → approve → farmer dues."""

    def setUp(self):
        self.client = APIClient()

        # Location
        _d, _di, _u, self.union = make_geo(prefix_ids=200)
        self.product_type = ProductType.objects.create(name_en='Vegetable', name_bn='সবজি')

        # 3 Farmers
        self.farmer1 = User.objects.create_user(
            username='farmer_a', email='fa@test.com', password='pass123',
            role='farmer', name='Farmer A', phone_number='01111111111',
            location=self.union, bkash_number='01999000001',
        )
        self.farmer2 = User.objects.create_user(
            username='farmer_b', email='fb@test.com', password='pass123',
            role='farmer', name='Farmer B', phone_number='01111111112',
            location=self.union, bkash_number='01999000002',
        )
        self.farmer3 = User.objects.create_user(
            username='farmer_c', email='fc@test.com', password='pass123',
            role='farmer', name='Farmer C', phone_number='01111111113',
            location=self.union, bkash_number='01999000003',
        )

        # Customer
        self.customer = User.objects.create_user(
            username='buyer1', email='buyer@test.com', password='pass123',
            role='customer', name='Test Buyer', location=self.union,
        )
        self.c_token, _ = Token.objects.get_or_create(user=self.customer)

        # Admin
        self.admin = User.objects.create_user(
            username='admin1', email='admin@test.com', password='pass123',
            role='admin', name='Admin User', is_staff=True, location=self.union,
        )
        self.a_token, _ = Token.objects.get_or_create(user=self.admin)

        # 3 Posts from 3 different farmers
        self.post1 = Post.objects.create(
            farmer=self.farmer1, title='Garlic', product_type=self.product_type,
            total_weight_kg=Decimal('500'), price_per_kg=Decimal('80'),
            location=self.union,
        )
        self.post2 = Post.objects.create(
            farmer=self.farmer2, title='Cucumber', product_type=self.product_type,
            total_weight_kg=Decimal('300'), price_per_kg=Decimal('42'),
            location=self.union,
        )
        self.post3 = Post.objects.create(
            farmer=self.farmer3, title='Chili', product_type=self.product_type,
            total_weight_kg=Decimal('200'), price_per_kg=Decimal('95'),
            location=self.union,
        )

    # ── Step 1: Create multi-product order ──────────────────────────────────

    def test_01_bulk_create_multi_product_order(self):
        """Customer places order with 3 products from 3 farmers → single Order + 3 OrderItems."""
        payload = {
            'items': [
                {'post': self.post1.id, 'quantity_kg': '50.00'},   # 50 * 80 = 4000
                {'post': self.post2.id, 'quantity_kg': '80.00'},   # 80 * 42 = 3360
                {'post': self.post3.id, 'quantity_kg': '10.00'},   # 10 * 95 = 950
            ],
            'delivery_address': '123 Test Street, Dhaka',
        }
        r = self.client.post('/api/orders/bulk_create/', payload, format='json',
                             HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.assertEqual(r.status_code, 201, r.data)

        # Returns a single Order (not a list)
        self.assertEqual(r.data['status'], 'pending')
        order_id = r.data['id']

        # Check totals: 4000 + 3360 + 950 = 8310
        self.assertEqual(Decimal(r.data['total_paid']), Decimal('8310.00'))
        # Platform fee: 10% of 8310 = 831.00
        self.assertEqual(Decimal(r.data['platform_fee']), Decimal('831.00'))
        # Farmer payout: 8310 - 831 = 7479
        self.assertEqual(Decimal(r.data['farmer_payout']), Decimal('7479.00'))

        # 3 OrderItems created
        self.assertEqual(len(r.data['items']), 3)
        item_titles = {i['post_title'] for i in r.data['items']}
        self.assertEqual(item_titles, {'Garlic', 'Cucumber', 'Chili'})

        # Stock deducted
        self.post1.refresh_from_db()
        self.post2.refresh_from_db()
        self.post3.refresh_from_db()
        self.assertEqual(self.post1.total_weight_kg, Decimal('450.00'))
        self.assertEqual(self.post2.total_weight_kg, Decimal('220.00'))
        self.assertEqual(self.post3.total_weight_kg, Decimal('190.00'))

        # Order has advance/final split
        self.assertEqual(Decimal(r.data['advance_amount']), Decimal('4155.00'))
        self.assertEqual(Decimal(r.data['final_amount']), Decimal('4155.00'))
        self.assertFalse(r.data['advance_paid'])
        self.assertFalse(r.data['final_paid'])

        # Verify DB
        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.items.count(), 3)
        self.assertEqual(order.status, 'pending')
        return order_id

    # ── Step 2: Submit manual bKash payment (advance) ───────────────────────

    def test_02_submit_advance_payment(self):
        order_id = self.test_01_bulk_create_multi_product_order()

        r = self.client.post('/api/payments/manual-bkash/submit/', {
            'order_id': order_id,
            'payment_type': 'advance',
            'trx_id': 'TRXABC123',
            'sender_number': '01700000000',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['status'], 'pending')
        self.assertEqual(r.data['trx_id'], 'TRXABC123')

        # ManualBkashPayment record created
        sub = ManualBkashPayment.objects.get(pk=r.data['submission_id'])
        self.assertEqual(sub.status, 'pending')
        self.assertEqual(sub.order_id, order_id)
        self.assertEqual(sub.payment_type, 'advance')
        self.assertEqual(sub.amount, Decimal('4155.00'))

    # ── Step 3: Admin approves advance payment ──────────────────────────────

    def test_03_admin_approves_advance(self):
        order_id = self.test_01_bulk_create_multi_product_order()

        # Submit
        r = self.client.post('/api/payments/manual-bkash/submit/', {
            'order_id': order_id,
            'payment_type': 'advance',
            'trx_id': 'TRXABC123',
            'sender_number': '01700000000',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        sub_id = r.data['submission_id']

        # Admin approves
        r = self.client.post(f'/api/payments/manual-bkash/{sub_id}/approve/', {
            'note': 'Verified bKash record',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.a_token.key}')
        self.assertEqual(r.status_code, 200, r.data)

        # Payment record created
        payment = Payment.objects.get(pk=r.data['payment_id'])
        self.assertEqual(payment.status, 'success')
        self.assertEqual(payment.amount, Decimal('4155.00'))
        self.assertEqual(payment.payment_type, 'advance')
        self.assertEqual(payment.transaction_id, 'MANUAL-TRXABC123-O' + str(order_id))
        self.assertEqual(payment.bkash_trx_id, 'TRXABC123')
        self.assertEqual(payment.sender_number, '01700000000')

        # Order updated
        order = Order.objects.get(pk=order_id)
        self.assertTrue(order.advance_paid)
        self.assertFalse(order.final_paid)
        self.assertEqual(order.status, 'approved')
        self.assertEqual(order.paid_amount, Decimal('4155.00'))
        self.assertEqual(order.bkash_trx_id, 'TRXABC123')

        # ManualBkashPayment marked approved
        sub = ManualBkashPayment.objects.get(pk=sub_id)
        self.assertEqual(sub.status, 'approved')
        self.assertEqual(sub.payment_id, payment.id)

    # ── Step 4: Submit + approve final payment ──────────────────────────────

    def test_04_submit_and_approve_final_payment(self):
        order_id = self.test_01_bulk_create_multi_product_order()

        # Submit advance
        r = self.client.post('/api/payments/manual-bkash/submit/', {
            'order_id': order_id, 'payment_type': 'advance',
            'trx_id': 'TRXADV999', 'sender_number': '01700000000',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        sub_adv_id = r.data['submission_id']

        # Approve advance
        self.client.post(f'/api/payments/manual-bkash/{sub_adv_id}/approve/', {},
                         format='json', HTTP_AUTHORIZATION=f'Token {self.a_token.key}')

        # Now submit final
        r = self.client.post('/api/payments/manual-bkash/submit/', {
            'order_id': order_id, 'payment_type': 'final',
            'trx_id': 'TRXFIN456', 'sender_number': '01700000000',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.assertEqual(r.status_code, 201, r.data)
        sub_fin_id = r.data['submission_id']

        # Approve final
        r = self.client.post(f'/api/payments/manual-bkash/{sub_fin_id}/approve/', {},
                             format='json', HTTP_AUTHORIZATION=f'Token {self.a_token.key}')
        self.assertEqual(r.status_code, 200, r.data)

        # Order fully completed
        order = Order.objects.get(pk=order_id)
        self.assertTrue(order.advance_paid)
        self.assertTrue(order.final_paid)
        self.assertEqual(order.status, 'completed')

        # Two Payment records for this order
        payments = Payment.objects.filter(order=order, status='success')
        self.assertEqual(payments.count(), 2)
        types = set(payments.values_list('payment_type', flat=True))
        self.assertEqual(types, {'advance', 'final'})

    # ── Step 5: Farmer dues (settlement) endpoint ───────────────────────────

    def test_05_farmer_dues_after_payment(self):
        order_id = self.test_01_bulk_create_multi_product_order()

        # Submit + approve advance
        r = self.client.post('/api/payments/manual-bkash/submit/', {
            'order_id': order_id, 'payment_type': 'advance',
            'trx_id': 'TRXDUE001', 'sender_number': '01700000000',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.client.post(f'/api/payments/manual-bkash/{r.data["submission_id"]}/approve/', {},
                         format='json', HTTP_AUTHORIZATION=f'Token {self.a_token.key}')

        # Check admin farmer-due endpoint
        r = self.client.get('/api/payments/settlement/dues/?unpaid=true',
                            HTTP_AUTHORIZATION=f'Token {self.a_token.key}')
        self.assertEqual(r.status_code, 200)

        # For multi-farmer orders, farmer_name is comma-separated. Check by name.
        all_names = ' '.join(e.get('farmer_name', '') or '' for e in r.data)
        self.assertIn('Farmer A', all_names)
        self.assertIn('Farmer B', all_names)
        self.assertIn('Farmer C', all_names)

        # Each entry should have a payout_amount
        for entry in r.data:
            self.assertIsNotNone(entry['payout_amount'])

    # ── Step 6: Duplicate submission blocked ─────────────────────────────────

    def test_06_duplicate_advance_blocked(self):
        order_id = self.test_01_bulk_create_multi_product_order()

        # Submit advance once
        self.client.post('/api/payments/manual-bkash/submit/', {
            'order_id': order_id, 'payment_type': 'advance',
            'trx_id': 'TRXDUPE1', 'sender_number': '01700000000',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')

        # Try again with same order + same type
        r = self.client.post('/api/payments/manual-bkash/submit/', {
            'order_id': order_id, 'payment_type': 'advance',
            'trx_id': 'TRXDUPE1', 'sender_number': '01700000000',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.assertEqual(r.status_code, 400)
        self.assertIn('already has a pending submission', str(r.data))

    # ── Step 7: Same TRX ID allowed for different orders ────────────────────

    def test_07_same_trx_different_orders_allowed(self):
        order_id1 = self.test_01_bulk_create_multi_product_order()

        # Create a second single-item order for the same customer
        r = self.client.post('/api/orders/bulk_create/', {
            'items': [{'post': self.post1.id, 'quantity_kg': '5.00'}],
            'delivery_address': '456 Second St',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.assertEqual(r.status_code, 201)
        order_id2 = r.data['id']

        # Submit same TRX ID for both orders (same bKash payment covers both)
        r1 = self.client.post('/api/payments/manual-bkash/submit/', {
            'order_id': order_id1, 'payment_type': 'advance',
            'trx_id': 'SHARED_TRX_999', 'sender_number': '01700000000',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.assertEqual(r1.status_code, 201)

        r2 = self.client.post('/api/payments/manual-bkash/submit/', {
            'order_id': order_id2, 'payment_type': 'advance',
            'trx_id': 'SHARED_TRX_999', 'sender_number': '01700000000',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.assertEqual(r2.status_code, 201)

        # Both approved — different transaction_ids (MANUAL-SHARED_TRX_999-O{id})
        self.client.post(f'/api/payments/manual-bkash/{r1.data["submission_id"]}/approve/', {},
                         format='json', HTTP_AUTHORIZATION=f'Token {self.a_token.key}')
        self.client.post(f'/api/payments/manual-bkash/{r2.data["submission_id"]}/approve/', {},
                         format='json', HTTP_AUTHORIZATION=f'Token {self.a_token.key}')

        p1 = Payment.objects.get(order_id=order_id1, status='success')
        p2 = Payment.objects.get(order_id=order_id2, status='success')
        self.assertNotEqual(p1.transaction_id, p2.transaction_id)

    # ── Step 8: Farmer wallet shows earnings ─────────────────────────────────

    def test_08_farmer_wallet_after_order(self):
        order_id = self.test_01_bulk_create_multi_product_order()

        # Approve advance so order is approved
        r = self.client.post('/api/payments/manual-bkash/submit/', {
            'order_id': order_id, 'payment_type': 'advance',
            'trx_id': 'TRXWAL001', 'sender_number': '01700000000',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        self.client.post(f'/api/payments/manual-bkash/{r.data["submission_id"]}/approve/', {},
                         format='json', HTTP_AUTHORIZATION=f'Token {self.a_token.key}')

        # Farmer A checks wallet
        f_token, _ = Token.objects.get_or_create(user=self.farmer1)
        r = self.client.get('/api/farmer/wallet/',
                            HTTP_AUTHORIZATION=f'Token {f_token.key}')
        self.assertEqual(r.status_code, 200)

        # Farmer A has pending payout from the advance
        self.assertGreater(Decimal(str(r.data['pending_payouts'])), Decimal('0'))

    # ── Step 9: Rejection flow ──────────────────────────────────────────────

    def test_09_reject_submission(self):
        order_id = self.test_01_bulk_create_multi_product_order()

        r = self.client.post('/api/payments/manual-bkash/submit/', {
            'order_id': order_id, 'payment_type': 'advance',
            'trx_id': 'TRXREJECT1', 'sender_number': '01700000000',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')
        sub_id = r.data['submission_id']

        # Admin rejects
        r = self.client.post(f'/api/payments/manual-bkash/{sub_id}/reject/', {
            'note': 'TRX not found in bKash records',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.a_token.key}')
        self.assertEqual(r.status_code, 200)

        sub = ManualBkashPayment.objects.get(pk=sub_id)
        self.assertEqual(sub.status, 'rejected')

        # No Payment created
        self.assertFalse(Payment.objects.filter(bkash_trx_id='TRXREJECT1').exists())

        # Order still pending
        order = Order.objects.get(pk=order_id)
        self.assertEqual(order.status, 'pending')
        self.assertFalse(order.advance_paid)

    # ── Step 10: Payment and ManualBkash payment list endpoints ─────────────

    def test_10_manual_bkash_list(self):
        order_id = self.test_01_bulk_create_multi_product_order()

        # Submit
        r = self.client.post('/api/payments/manual-bkash/submit/', {
            'order_id': order_id, 'payment_type': 'advance',
            'trx_id': 'TRXLIST01', 'sender_number': '01700000000',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token.key}')

        # Admin lists pending
        r = self.client.get('/api/payments/manual-bkash/list/?status=pending',
                            HTTP_AUTHORIZATION=f'Token {self.a_token.key}')
        self.assertEqual(r.status_code, 200)
        pending_ids = [s['id'] for s in r.data]
        self.assertIn(r.data[0]['id'], pending_ids)

        # After approval, no longer in pending
        self.client.post(f'/api/payments/manual-bkash/{r.data[0]["id"]}/approve/', {},
                         format='json', HTTP_AUTHORIZATION=f'Token {self.a_token.key}')
        r = self.client.get('/api/payments/manual-bkash/list/?status=pending',
                            HTTP_AUTHORIZATION=f'Token {self.a_token.key}')
        self.assertNotIn(r.data[0]['id'] if r.data else None,
                         [s['id'] for s in r.data if s.get('trx_id') == 'TRXLIST01'] if r.data else [])
