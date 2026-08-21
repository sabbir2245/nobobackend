"""Tests for the UddoktaPay escrow flow (auto-verified 50/50 advance & final).

The outbound requests to UddoktaPay are mocked so no real gateway call is made.
"""
import json
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase
from django.test.utils import override_settings
from rest_framework.test import APIClient

from api.models import Order, Payment
from .helpers import make_geo, make_user, make_token, make_product, make_post


def _charge_response(invoice_id, payment_url="https://pay.test/checkout"):
    return {
        "status": True,
        "payment_url": payment_url,
        "invoice_id": invoice_id,
        "message": "Payment pending",
    }


def _webhook_payload(order_id, payment_type, amount, invoice_id, trx_id="BLATRX123",
                     sender="01700000000"):
    return {
        "full_name": "Cust",
        "email": "cust@test.com",
        "amount": f"{Decimal(amount):.2f}",
        "fee": "0.00",
        "charged_amount": f"{Decimal(amount):.2f}",
        "invoice_id": invoice_id,
        "metadata": {"order_id": str(order_id), "payment_type": payment_type},
        "payment_method": "bKash",
        "sender_number": sender,
        "transaction_id": trx_id,
        "status": "COMPLETED",
    }


class UddoktaPayCheckoutTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        _d, _dt, _up, self.union = make_geo(prefix_ids=2000)
        self.product = make_product()
        self.farmer = make_user('farmer', 'udoktafarmer', self.union)
        self.customer = make_user('customer', 'udoktacust', self.union)
        self.post = make_post(self.farmer, self.union, self.product, qty='100', price='100')
        self.c_token = make_token(self.customer)
        self.order = Order.objects.create(
            customer=self.customer, post=self.post, quantity_kg=Decimal('10'),
            total_paid=Decimal('1000'), platform_fee=Decimal('100'),
            farmer_payout=Decimal('900'), delivery_address='Dhaka',
            advance_amount=Decimal('500'), final_amount=Decimal('500'),
            status='pending')
        self.url = '/api/payments/uddoktapay/checkout/'

    @patch('api.uddoktapay_views.uddoktapay_create_charge',
           return_value=_charge_response('INV-ADV-1'))
    def test_advance_checkout_initiates_payment(self, mock_charge):
        r = self.client.post(self.url, {
            'order_id': self.order.id, 'payment_type': 'advance',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['payment_url'], 'https://pay.test/checkout')
        self.assertEqual(r.data['invoice_id'], 'INV-ADV-1')
        payment = Payment.objects.get(order=self.order, payment_type='advance')
        self.assertEqual(payment.status, 'initiated')
        self.assertEqual(payment.gateway, 'uddoktapay')
        self.assertEqual(payment.uddokta_invoice_id, 'INV-ADV-1')
        # Order not marked paid until webhook confirms.
        self.order.refresh_from_db()
        self.assertFalse(self.order.advance_paid)

    @patch('api.uddoktapay_views.uddoktapay_create_charge',
           return_value=_charge_response('INV-FIN-1'))
    def test_final_checkout_blocked_before_advance(self, mock_charge):
        r = self.client.post(self.url, {
            'order_id': self.order.id, 'payment_type': 'final',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 400)
        self.assertIn('Advance payment must be completed', str(r.data))

    def test_requires_order_and_payment_type(self):
        r = self.client.post(self.url, {
            'payment_type': 'advance',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 400)
        r = self.client.post(self.url, {
            'order_id': self.order.id,
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 400)

    def test_invalid_payment_type(self):
        r = self.client.post(self.url, {
            'order_id': self.order.id, 'payment_type': 'half',
        }, format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 400)

    def test_unauthenticated(self):
        r = self.client.post(self.url, {
            'order_id': self.order.id, 'payment_type': 'advance',
        }, format='json')
        self.assertEqual(r.status_code, 401)

    def test_cannot_pay_others_order(self):
        other = make_user('customer', 'othercust2', self.union)
        other_token = make_token(other)
        r = self.client.post(self.url, {
            'order_id': self.order.id, 'payment_type': 'advance',
        }, format='json', HTTP_AUTHORIZATION=f'Token {other_token}')
        self.assertEqual(r.status_code, 403)


@override_settings(UDDOKTAPAY_API_KEY='test-uddokta-key')
class UddoktaPayWebhookTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        _d, _dt, _up, self.union = make_geo(prefix_ids=3000)
        self.product = make_product()
        self.farmer = make_user('farmer', 'udoktafarmer2', self.union)
        self.customer = make_user('customer', 'udoktacust2', self.union)
        self.post = make_post(self.farmer, self.union, self.product, qty='100', price='100')
        self.c_token = make_token(self.customer)
        self.order = Order.objects.create(
            customer=self.customer, post=self.post, quantity_kg=Decimal('10'),
            total_paid=Decimal('1000'), platform_fee=Decimal('100'),
            farmer_payout=Decimal('900'), delivery_address='Dhaka',
            advance_amount=Decimal('500'), final_amount=Decimal('500'),
            status='pending')
        self.url = '/api/payments/uddoktapay/webhook/'
        self.headers = {
            'HTTP_RT_UDDOKTAPAY_API_KEY': settings.UDDOKTAPAY_API_KEY,
            'CONTENT_TYPE': 'application/json',
        }

    def _make_initiated(self, payment_type, invoice_id):
        return Payment.objects.create(
            user=self.customer, order=self.order, amount=Decimal('500'),
            payment_type=payment_type, transaction_id=f'UDOKTA-{invoice_id}',
            status='initiated', gateway='uddoktapay',
            uddokta_invoice_id=invoice_id)

    def test_advance_webhook_marks_paid(self):
        self._make_initiated('advance', 'INV-ADV-W')
        payload = _webhook_payload(self.order.id, 'advance', '500', 'INV-ADV-W')
        r = self.client.post(self.url, data=json.dumps(payload),
                             content_type='application/json', **self.headers)
        self.assertEqual(r.status_code, 200)
        self.order.refresh_from_db()
        self.assertTrue(self.order.advance_paid)
        self.assertFalse(self.order.final_paid)
        payment = Payment.objects.get(order=self.order, payment_type='advance')
        self.assertEqual(payment.status, 'success')
        self.assertEqual(payment.bkash_trx_id, 'BLATRX123')
        self.assertEqual(payment.sender_number, '01700000000')

    def test_advance_then_final_webhook_full_flow(self):
        self._make_initiated('advance', 'INV-ADV-W2')
        self.client.post(self.url, data=json.dumps(
            _webhook_payload(self.order.id, 'advance', '500', 'INV-ADV-W2')),
            content_type='application/json', **self.headers)
        self.order.refresh_from_db()
        self.assertTrue(self.order.advance_paid)

        self._make_initiated('final', 'INV-FIN-W2')
        r = self.client.post(self.url, data=json.dumps(
            _webhook_payload(self.order.id, 'final', '500', 'INV-FIN-W2', trx_id='FINTRX')),
            content_type='application/json', **self.headers)
        self.assertEqual(r.status_code, 200)
        self.order.refresh_from_db()
        self.assertTrue(self.order.final_paid)
        self.assertEqual(
            Payment.objects.filter(order=self.order, status='success').count(), 2)

    def test_wrong_api_key_rejected(self):
        self._make_initiated('advance', 'INV-BAD')
        payload = _webhook_payload(self.order.id, 'advance', '500', 'INV-BAD')
        r = self.client.post(self.url, data=json.dumps(payload),
                             content_type='application/json',
                             HTTP_RT_UDDOKTAPAY_API_KEY='wrong-key')
        self.assertEqual(r.status_code, 401)

    def test_amount_mismatch_rejected(self):
        self._make_initiated('advance', 'INV-AMT')
        payload = _webhook_payload(self.order.id, 'advance', '999', 'INV-AMT')
        r = self.client.post(self.url, data=json.dumps(payload),
                             content_type='application/json', **self.headers)
        self.assertEqual(r.status_code, 400)
        self.order.refresh_from_db()
        self.assertFalse(self.order.advance_paid)

    def test_non_completed_status_not_finalized(self):
        self._make_initiated('advance', 'INV-PEND')
        payload = _webhook_payload(self.order.id, 'advance', '500', 'INV-PEND')
        payload['status'] = 'PENDING'
        r = self.client.post(self.url, data=json.dumps(payload),
                             content_type='application/json', **self.headers)
        self.assertEqual(r.status_code, 400)
        self.order.refresh_from_db()
        self.assertFalse(self.order.advance_paid)

    def test_no_matching_initiated_payment(self):
        payload = _webhook_payload(self.order.id, 'advance', '500', 'INV-NOMATCH')
        r = self.client.post(self.url, data=json.dumps(payload),
                             content_type='application/json', **self.headers)
        self.assertEqual(r.status_code, 404)
        self.order.refresh_from_db()
        self.assertFalse(self.order.advance_paid)

    def test_invalid_payload(self):
        r = self.client.post(self.url, data='not-json',
                             content_type='application/json', **self.headers)
        self.assertEqual(r.status_code, 400)


class UddoktaPayVerifyViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        _d, _dt, _up, self.union = make_geo(prefix_ids=4000)
        self.product = make_product()
        self.farmer = make_user('farmer', 'udoktafarmer3', self.union)
        self.customer = make_user('customer', 'udoktacust3', self.union)
        self.post = make_post(self.farmer, self.union, self.product, qty='100', price='100')
        self.c_token = make_token(self.customer)
        self.order = Order.objects.create(
            customer=self.customer, post=self.post, quantity_kg=Decimal('10'),
            total_paid=Decimal('1000'), platform_fee=Decimal('100'),
            farmer_payout=Decimal('900'), delivery_address='Dhaka',
            advance_amount=Decimal('500'), final_amount=Decimal('500'),
            status='pending')
        self.invoice = 'INV-VERIFY'
        Payment.objects.create(
            user=self.customer, order=self.order, amount=Decimal('500'),
            payment_type='advance', transaction_id=f'UDOKTA-{self.invoice}',
            status='initiated', gateway='uddoktapay', uddokta_invoice_id=self.invoice)

    @patch('api.uddoktapay_views.uddoktapay_verify',
           return_value={"status": "COMPLETED", "transaction_id": "VTRX1",
                         "sender_number": "01711111111"})
    def test_verify_finalizes_initiated_payment(self, mock_verify):
        r = self.client.get(
            f'/api/payments/uddoktapay/verify/{self.invoice}/',
            HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 200)
        self.order.refresh_from_db()
        self.assertTrue(self.order.advance_paid)
        payment = Payment.objects.get(order=self.order, payment_type='advance')
        self.assertEqual(payment.status, 'success')

    @patch('api.uddoktapay_views.uddoktapay_verify',
           return_value={"status": "PENDING"})
    def test_verify_pending_does_not_finalize(self, mock_verify):
        r = self.client.get(
            f'/api/payments/uddoktapay/verify/{self.invoice}/',
            HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 200)
        self.order.refresh_from_db()
        self.assertFalse(self.order.advance_paid)

    def test_verify_requires_auth(self):
        r = self.client.get(f'/api/payments/uddoktapay/verify/{self.invoice}/')
        self.assertEqual(r.status_code, 401)