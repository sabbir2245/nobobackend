from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from api.models import Bid
from .helpers import make_geo, make_user, make_token, make_product, make_post


class BiddingSystemTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        _division, _district, _upazila, self.union = make_geo(prefix_ids=600)
        self.product = make_product()
        self.farmer = make_user('farmer', 'bidfarmer', self.union)
        self.customer = make_user('customer', 'bidcustomer', self.union)
        self.post = make_post(self.farmer, self.union, self.product, availability=72)
        self.c_token = make_token(self.customer)
        self.f_token = make_token(self.farmer)

    def test_post_exposes_time_availability(self):
        r = self.client.get(f'/api/posts/{self.post.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['time_availability'], 72)

    def test_customer_can_place_one_bid(self):
        r = self.client.post('/api/bids/', {'post': self.post.id, 'amount': '40.00'},
                             format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['status'], 'pending')
        self.assertEqual(Decimal(r.data['amount']), Decimal('40.00'))
        self.assertEqual(r.data['customer_username'], 'bidcustomer')
        self.assertEqual(r.data['post_title'], 'Test Post')

    def test_duplicate_bid_blocked(self):
        Bid.objects.create(customer=self.customer, post=self.post, amount=Decimal('40'))
        r = self.client.post('/api/bids/', {'post': self.post.id, 'amount': '35.00'},
                             format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 400)
        self.assertIn('already placed a bid', str(r.data))

    def test_non_customer_cannot_bid(self):
        r = self.client.post('/api/bids/', {'post': self.post.id, 'amount': '40.00'},
                             format='json', HTTP_AUTHORIZATION=f'Token {self.f_token}')
        self.assertEqual(r.status_code, 403)

    def test_farmer_counter_bid_flow(self):
        bid = Bid.objects.create(customer=self.customer, post=self.post, amount=Decimal('40'))
        r = self.client.post(f'/api/bids/{bid.id}/counter/', {'counter_amount': '45.00'},
                             format='json', HTTP_AUTHORIZATION=f'Token {self.f_token}')
        self.assertEqual(r.status_code, 200, r.data)
        bid.refresh_from_db()
        self.assertEqual(bid.status, 'counter_offered')
        self.assertEqual(bid.counter_amount, Decimal('45.00'))

    def test_only_post_farmer_can_counter(self):
        other_farmer = make_user('farmer', 'otherfarmer', self.union)
        other_token = make_token(other_farmer)
        bid = Bid.objects.create(customer=self.customer, post=self.post, amount=Decimal('40'))
        r = self.client.post(f'/api/bids/{bid.id}/counter/', {'counter_amount': '45'},
                             format='json', HTTP_AUTHORIZATION=f'Token {other_token}')
        # Queryset scoping hides other farmers' bids -> 404 (no info leak).
        self.assertEqual(r.status_code, 404)

    def test_counter_invalid_amount(self):
        bid = Bid.objects.create(customer=self.customer, post=self.post, amount=Decimal('40'))
        r = self.client.post(f'/api/bids/{bid.id}/counter/', {'counter_amount': '-5'},
                             format='json', HTTP_AUTHORIZATION=f'Token {self.f_token}')
        self.assertEqual(r.status_code, 400)

    def test_customer_accept_counter(self):
        bid = Bid.objects.create(customer=self.customer, post=self.post, amount=Decimal('40'))
        self.client.post(f'/api/bids/{bid.id}/counter/', {'counter_amount': '45'},
                         format='json', HTTP_AUTHORIZATION=f'Token {self.f_token}')
        r = self.client.post(f'/api/bids/{bid.id}/accept/', format='json',
                             HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 200, r.data)
        bid.refresh_from_db()
        self.assertEqual(bid.status, 'accepted')

    def test_customer_reject_counter(self):
        bid = Bid.objects.create(customer=self.customer, post=self.post, amount=Decimal('40'))
        self.client.post(f'/api/bids/{bid.id}/counter/', {'counter_amount': '60'},
                         format='json', HTTP_AUTHORIZATION=f'Token {self.f_token}')
        r = self.client.post(f'/api/bids/{bid.id}/reject/', format='json',
                             HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 200, r.data)
        bid.refresh_from_db()
        self.assertEqual(bid.status, 'rejected')

    def test_cannot_accept_without_counter(self):
        bid = Bid.objects.create(customer=self.customer, post=self.post, amount=Decimal('40'))
        r = self.client.post(f'/api/bids/{bid.id}/accept/', format='json',
                             HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.status_code, 400)

    def test_farmer_sees_bids_on_their_posts(self):
        Bid.objects.create(customer=self.customer, post=self.post, amount=Decimal('40'))
        r = self.client.get('/api/bids/', HTTP_AUTHORIZATION=f'Token {self.f_token}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 1)

    def test_post_has_pending_bid_flag(self):
        Bid.objects.create(customer=self.customer, post=self.post, amount=Decimal('40'))
        r = self.client.get(f'/api/posts/{self.post.id}/', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        self.assertEqual(r.data['has_pending_bid'], True)