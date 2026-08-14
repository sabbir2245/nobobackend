from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.authtoken.models import Token
from django.contrib.auth import get_user_model
from .models import Payment

User = get_user_model()

MOCK_BKASH_CREATE_SUCCESS = {
    'statusCode': '0000',
    'paymentID': 'TR0011REF123456789',
    'bkashURL': 'https://sandbox.bka.sh/tokenized/checkout/123',
    'merchantInvoiceNumber': 'NOB-TEST-001',
}

MOCK_BKASH_EXECUTE_SUCCESS = {
    'statusCode': '0000',
    'transactionStatus': 'Completed',
    'trxID': 'TRX123456789',
    'amount': '500.00',
    'paymentID': 'TR0011REF123456789',
    'merchantInvoiceNumber': 'NOB-TEST-001',
}

MOCK_BKASH_QUERY_COMPLETED = {
    'statusCode': '0000',
    'transactionStatus': 'Completed',
    'trxID': 'TRX123456789',
    'amount': '500.00',
}

MOCK_BKASH_QUERY_FAILED = {
    'statusCode': '0000',
    'transactionStatus': 'Failed',
}

MOCK_BKASH_REFUND_SUCCESS = {
    'statusCode': '0000',
    'refundTrxID': 'RF123456789',
}


class BKashPaymentInitiateTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = '/api/payments/bkash/initiate/'

        self.customer = User.objects.create_user(
            username='bkashcust',
            email='bkash@test.com',
            password='testpass123',
            role='customer',
            name='bKash Customer',
            phone_number='01700000000',
        )
        self.token, _ = Token.objects.get_or_create(user=self.customer)

    @patch('api.payments.bkash_create_payment')
    def test_initiate_success(self, mock_create):
        mock_create.return_value = MOCK_BKASH_CREATE_SUCCESS

        response = self.client.post(
            self.url, {'amount': '500.00'}, format='json',
            HTTP_AUTHORIZATION=f'Token {self.token.key}',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('bkash_url', response.data)
        self.assertEqual(response.data['bkash_url'], MOCK_BKASH_CREATE_SUCCESS['bkashURL'])
        self.assertEqual(response.data['amount'], '500.00')
        self.assertIn('transaction_id', response.data)
        self.assertIn('payment_id', response.data)
        self.assertEqual(response.data['payment_id_bkash'], MOCK_BKASH_CREATE_SUCCESS['paymentID'])

        payment = Payment.objects.get(pk=response.data['payment_id'])
        self.assertEqual(payment.status, 'initiated')
        self.assertEqual(payment.amount, Decimal('500.00'))
        self.assertEqual(payment.gateway, 'bkash')
        self.assertEqual(payment.bkash_payment_id, MOCK_BKASH_CREATE_SUCCESS['paymentID'])

    def test_initiate_missing_amount(self):
        response = self.client.post(
            self.url, {}, format='json',
            HTTP_AUTHORIZATION=f'Token {self.token.key}',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Amount is required', str(response.data))

    def test_initiate_invalid_amount(self):
        response = self.client.post(
            self.url, {'amount': '-100'}, format='json',
            HTTP_AUTHORIZATION=f'Token {self.token.key}',
        )
        self.assertEqual(response.status_code, 400)

    def test_initiate_zero_amount(self):
        response = self.client.post(
            self.url, {'amount': '0'}, format='json',
            HTTP_AUTHORIZATION=f'Token {self.token.key}',
        )
        self.assertEqual(response.status_code, 400)

    def test_initiate_unauthenticated(self):
        response = self.client.post(
            self.url, {'amount': '500.00'}, format='json',
        )
        self.assertEqual(response.status_code, 401)

    @patch('api.payments.bkash_create_payment')
    def test_initiate_gateway_failure(self, mock_create):
        mock_create.side_effect = Exception('bKash API error')

        response = self.client.post(
            self.url, {'amount': '500.00'}, format='json',
            HTTP_AUTHORIZATION=f'Token {self.token.key}',
        )
        self.assertEqual(response.status_code, 502)
        self.assertIn('Failed to initiate', str(response.data))


class BKashPaymentStatusTest(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.customer = User.objects.create_user(
            username='bkashstatus',
            email='bkashstatus@test.com',
            password='testpass123',
            role='customer',
        )
        self.token, _ = Token.objects.get_or_create(user=self.customer)

        self.payment = Payment.objects.create(
            user=self.customer,
            amount=Decimal('250.00'),
            transaction_id='BKASH-STATUS-001',
            status='success',
            gateway='bkash',
            bkash_payment_id='TR0011REFSTATUS',
            bkash_trx_id='TRXSTATUS001',
        )

    def test_get_status(self):
        response = self.client.get(
            '/api/payments/bkash/status/BKASH-STATUS-001/',
            HTTP_AUTHORIZATION=f'Token {self.token.key}',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'success')
        self.assertEqual(response.data['amount'], '250.00')
        self.assertEqual(response.data['gateway'], 'bkash')

    def test_get_status_not_found(self):
        response = self.client.get(
            '/api/payments/bkash/status/DOES_NOT_EXIST/',
            HTTP_AUTHORIZATION=f'Token {self.token.key}',
        )
        self.assertEqual(response.status_code, 404)

    def test_get_status_unauthorized(self):
        response = self.client.get('/api/payments/bkash/status/BKASH-STATUS-001/')
        self.assertEqual(response.status_code, 401)

    @patch('api.payments.bkash_query_payment')
    def test_reconcile_initiated_status(self, mock_query):
        Payment.objects.create(
            user=self.customer,
            amount=Decimal('100.00'),
            transaction_id='BKASH-INIT-001',
            status='initiated',
            gateway='bkash',
            bkash_payment_id='TR0011REFINIT',
        )
        mock_query.return_value = MOCK_BKASH_QUERY_COMPLETED

        response = self.client.get(
            '/api/payments/bkash/status/BKASH-INIT-001/',
            HTTP_AUTHORIZATION=f'Token {self.token.key}',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'success')


class BKashPaymentCallbackTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_callback_missing_payment_id(self):
        response = self.client.get('/api/payments/bkash/callback/')
        self.assertEqual(response.status_code, 400)

    def test_callback_cancelled(self):
        response = self.client.get('/api/payments/bkash/callback/?paymentID=TEST_CANCEL&status=cancel')
        self.assertEqual(response.status_code, 200)

    @patch('api.payments.bkash_execute_payment')
    def test_callback_success(self, mock_execute):
        mock_execute.return_value = MOCK_BKASH_EXECUTE_SUCCESS

        response = self.client.get(
            '/api/payments/bkash/callback/?paymentID=TR0011REF123456789&status=success'
        )
        self.assertEqual(response.status_code, 200)

    @patch('api.payments.bkash_execute_payment')
    def test_callback_execute_failure_fallback_query(self, mock_execute):
        mock_execute.return_value = {'statusCode': '9999', 'transactionStatus': 'Failed'}

        with patch('api.payments.bkash_query_payment') as mock_query:
            mock_query.return_value = MOCK_BKASH_QUERY_COMPLETED

            response = self.client.get(
                '/api/payments/bkash/callback/?paymentID=TR0011REF_FALLBACK&status=success'
            )
            self.assertEqual(response.status_code, 200)


class BKashPaymentSuccessFailTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_success_endpoint(self):
        response = self.client.post('/api/payments/bkash/success/', {
            'transaction_id': 'BKASH-DIRECT-SUCCESS',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'success')

    def test_fail_endpoint(self):
        response = self.client.post('/api/payments/bkash/fail/', {
            'transaction_id': 'BKASH-DIRECT-FAIL',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'failed')