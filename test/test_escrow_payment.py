from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from api.models import Order, Payment
from .helpers import make_geo, make_user, make_token, make_product, make_post


class EscrowPaymentTest(TestCase):
    """50% advance + 50% final bKash settlement flow via manual TrxID."""

    def setUp(self):
        self.client = APIClient()
        _d, _dt, _up, self.union = make_geo(prefix_ids=1000)
        self.product = make_product()
        self.farmer = make_user('farmer', 'escrowfarmer', self.union)
        self.customer = make_user('customer', 'escrowcustomer', self.union)
        self.post = make_post(self.farmer, self.union, self.product, qty='100', price='100')
        self.c_token = make_token(self.customer)
        self.order = Order.objects.create(
            customer=self.customer, post=self.post, quantity_kg=Decimal('10'),
            total_paid=Decimal('1000'), platform_fee=Decimal('100'),
            farmer_payout=Decimal('900'), delivery_address='Dhaka',
            advance_amount=Decimal('500'), final_amount=Decimal('500'),
            status='pending')
        self.url = '/api/payments/escrow/trx/'

    def test_advance_payment_success(self):
        r = self.client.post(self.url, {
            'order_id': self.order.id, 'payment_type': 'advance', 'trx_id': 'ADV123',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 201, r.data)
        self.order.refresh_from_db()
        self.assertTrue(self.order.advance_paid)
        self.assertFalse(self.order.final_paid)
        payment = Payment.objects.get(order=self.order, payment_type='advance')
        self.assertEqual(payment.status, 'success')
        self.assertEqual(payment.bkash_trx_id, 'ADV123')
        self.assertEqual(payment.amount, Decimal('500'))

    def test_final_payment_blocked_before_advance(self):
        r = self.client.post(self.url, {
            'order_id': self.order.id, 'payment_type': 'final', 'trx_id': 'FIN1',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 400)
        self.assertIn('Advance payment must be completed', str(r.data))

    def test_full_advance_then_final_flow(self):
        r1 = self.client.post(self.url, {
            'order_id': self.order.id, 'payment_type': 'advance', 'trx_id': 'ADV1',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r1.status_code, 201)

        r2 = self.client.post(self.url, {
            'order_id': self.order.id, 'payment_type': 'final', 'trx_id': 'FIN1',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r2.status_code, 201, r2.data)
        self.order.refresh_from_db()
        self.assertTrue(self.order.advance_paid)
        self.assertTrue(self.order.final_paid)
        self.assertEqual(self.order.bkash_payment_status, 'success')
        self.assertEqual(
            Payment.objects.filter(order=self.order, status='success').count(), 2)

    def test_duplicate_advance_blocked(self):
        self.client.post(self.url, {
            'order_id': self.order.id, 'payment_type': 'advance', 'trx_id': 'ADV1',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        r = self.client.post(self.url, {
            'order_id': self.order.id, 'payment_type': 'advance', 'trx_id': 'ADV2',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 400)
        self.assertIn('already completed', str(r.data))

    def test_requires_trx_id(self):
        r = self.client.post(self.url, {
            'order_id': self.order.id, 'payment_type': 'advance',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 400)
        self.assertIn('trx_id is required', str(r.data))

    def test_invalid_payment_type(self):
        r = self.client.post(self.url, {
            'order_id': self.order.id, 'payment_type': 'half', 'trx_id': 'X',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 400)

    def test_order_not_found(self):
        r = self.client.post(self.url, {
            'order_id': 999999, 'payment_type': 'advance', 'trx_id': 'ADV1',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 404)

    def test_unauthenticated(self):
        r = self.client.post(self.url, {
            'order_id': self.order.id, 'payment_type': 'advance', 'trx_id': 'ADV1',
        }, format='json')
        self.assertEqual(r.status_code, 401)

    def test_cannot_pay_for_others_order(self):
        other = make_user('customer', 'othercust', self.union)
        other_token = make_token(other)
        r = self.client.post(self.url, {
            'order_id': self.order.id, 'payment_type': 'advance', 'trx_id': 'ADV1',
        }, format='json', HTTP_AUTHORIZATION=f'Token {other_token}')
        self.assertEqual(r.status_code, 403)