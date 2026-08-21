from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from api.models import Order, Batch, BatchItem, PendingPool
from .helpers import (
    make_geo, make_user, make_token, make_area, make_product, make_post,
)


class DeliveryWorkflowTest(TestCase):
    """Full delivery lifecycle: accept -> pick_up -> in_transit -> verify -> deliver."""

    def setUp(self):
        self.client = APIClient()
        _d1, _dt1, _up1, self.union1 = make_geo(prefix_ids=700)
        self.product = make_product()
        self.area = make_area(_up1, threshold='100')
        self.farmer = make_user('farmer', 'dlfarmer', self.union1)
        self.customer = make_user('customer', 'dlcustomer', self.union1)
        self.post = make_post(self.farmer, self.union1, self.product)
        self.c_token = make_token(self.customer)
        self.deliveryman = make_user('deliveryman', 'dldman', self.union1)
        self.deliveryman.service_areas = [self.area.id]
        self.deliveryman.save(update_fields=['service_areas'])
        self.d_token = make_token(self.deliveryman)

    def _seed_batch(self):
        """Create two orders past the area threshold to form one pending batch."""
        for qty in ('60', '50'):
            self.client.post('/api/orders/', {'post': self.post.id, 'quantity_kg': qty,
                                              'delivery_address': 'Dhaka'},
                             format='json', HTTP_AUTHORIZATION=f'Token {self.c_token}')
        return Batch.objects.first()

    def test_full_delivery_workflow(self):
        batch = self._seed_batch()
        self.assertEqual(batch.status, 'pending')

        # Accept
        r = self.client.post(f'/api/batches/{batch.id}/accept/',
                             HTTP_AUTHORIZATION=f'Token {self.d_token}')
        self.assertEqual(r.status_code, 200, r.data)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'assigned')

        # Cannot deliver before pick-up (old single-step path is rejected)
        r = self.client.post(f'/api/batches/{batch.id}/deliver/',
                             HTTP_AUTHORIZATION=f'Token {self.d_token}')
        self.assertEqual(r.status_code, 400)

        # Pick up at union
        r = self.client.post(f'/api/batches/{batch.id}/pick_up/',
                             HTTP_AUTHORIZATION=f'Token {self.d_token}')
        self.assertEqual(r.status_code, 200, r.data)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'picked_up')

        # In transit / shipped
        r = self.client.post(f'/api/batches/{batch.id}/in_transit/',
                             HTTP_AUTHORIZATION=f'Token {self.d_token}')
        self.assertEqual(r.status_code, 200, r.data)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'in_transit')

        # Verify payment completed by customer
        r = self.client.post(f'/api/batches/{batch.id}/verify_payment/',
                             HTTP_AUTHORIZATION=f'Token {self.d_token}')
        self.assertEqual(r.status_code, 200, r.data)
        batch.refresh_from_db()
        self.assertTrue(batch.payment_verified)

        # Final handover
        r = self.client.post(f'/api/batches/{batch.id}/deliver/',
                             HTTP_AUTHORIZATION=f'Token {self.d_token}')
        self.assertEqual(r.status_code, 200, r.data)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'delivered')
        self.assertIsNotNone(batch.delivered_at)

        # All member orders completed
        self.assertEqual(
            Order.objects.filter(post=self.post, status='completed').count(), 2)

    def test_workflow_requires_sequential_stages(self):
        batch = self._seed_batch()
        self.client.post(f'/api/batches/{batch.id}/accept/',
                         HTTP_AUTHORIZATION=f'Token {self.d_token}')
        # in_transit before pick_up is not allowed
        r = self.client.post(f'/api/batches/{batch.id}/in_transit/',
                             HTTP_AUTHORIZATION=f'Token {self.d_token}')
        self.assertEqual(r.status_code, 400)

    def test_verify_payment_only_after_pickup(self):
        batch = self._seed_batch()
        self.client.post(f'/api/batches/{batch.id}/accept/',
                         HTTP_AUTHORIZATION=f'Token {self.d_token}')
        r = self.client.post(f'/api/batches/{batch.id}/verify_payment/',
                             HTTP_AUTHORIZATION=f'Token {self.d_token}')
        self.assertEqual(r.status_code, 400)

    def test_deliveryman_cannot_act_on_unassigned_batch(self):
        batch = self._seed_batch()
        r = self.client.post(f'/api/batches/{batch.id}/pick_up/',
                             HTTP_AUTHORIZATION=f'Token {self.d_token}')
        self.assertEqual(r.status_code, 403)


class BatchDistanceSortingTest(TestCase):
    """Available batches must be sorted closest-first by distance in km."""

    def setUp(self):
        self.client = APIClient()
        # Deliveryman in Dhaka
        _, dhaka_district, dhaka_upazila, self.dhaka_union = make_geo(prefix_ids=800, lat=23.685, lng=90.3563)
        # Far union in a distant district (large coordinate offset)
        _, _, far_upazila, self.far_union = make_geo(prefix_ids=900, lat=22.34, lng=91.82)
        self.product = make_product()
        self.deliveryman = make_user('deliveryman', 'sortdman', self.dhaka_union)
        self.d_token = make_token(self.deliveryman)

        self.area_near = make_area(dhaka_upazila, threshold='1')
        self.area_far = make_area(far_upazila, threshold='1')
        # Deliveryman serves both areas
        self.deliveryman.service_areas = [self.area_near.id, self.area_far.id]
        self.deliveryman.save(update_fields=['service_areas'])

        self._make_batch(self.area_far, self.far_union)
        self._make_batch(self.area_near, self.dhaka_union)

    def _make_batch(self, area, union):
        farmer = make_user('farmer', f'f_{area.id}', union)
        customer = make_user('customer', f'c_{area.id}', union)
        post = make_post(farmer, union, self.product, qty='50', price='50')
        order = Order.objects.create(
            customer=customer, post=post, quantity_kg=Decimal('10'),
            total_paid=Decimal('500'), platform_fee=Decimal('50'),
            farmer_payout=Decimal('450'), delivery_address='x',
            advance_amount=Decimal('250'), final_amount=Decimal('250'),
            status='pending')
        batch = Batch.objects.create(
            area=area, union=union, product_type=self.product,
            total_quantity_kg=Decimal('10'), total_value=Decimal('500'),
            status='pending')
        BatchItem.objects.create(batch=batch, order=order, quantity_kg=Decimal('10'), farmer=farmer)
        return batch

    def test_available_batches_sorted_closest_first(self):
        r = self.client.get('/api/batches/available/', HTTP_AUTHORIZATION=f'Token {self.d_token}')
        self.assertEqual(r.status_code, 200)
        data = r.data
        self.assertEqual(len(data), 2)
        # Closest (Dhaka, same district as deliveryman) must come first.
        self.assertEqual(data[0]['union']['id'], self.dhaka_union.id)
        self.assertEqual(data[1]['union']['id'], self.far_union.id)
        # Distance of the first must be smaller than the second.
        self.assertLess(data[0]['distance_km'], data[1]['distance_km'])
        self.assertIsNotNone(data[0]['distance_km'])