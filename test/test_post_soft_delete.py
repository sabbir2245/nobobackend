"""Tests for Post soft-delete / expiry visibility.

Deleting a post must NOT remove the row (so orders, payments, batches and
reviews stay intact) — it only flips `is_visible=False`. Expired posts are also
hidden from public listings by the `expire_posts` command.
"""
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient

from api.models import Post, Order, Review
from .helpers import make_geo, make_user, make_token, make_product, make_post


class PostSoftDeleteTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        _d, _dt, _up, self.union = make_geo(prefix_ids=5000)
        self.product = make_product()
        self.farmer = make_user('farmer', 'softfarmer', self.union)
        self.customer = make_user('customer', 'softcust', self.union)
        self.f_token = make_token(self.farmer)
        self.post = make_post(self.farmer, self.union, self.product, qty='100', price='50')
        self.url = f'/api/posts/{self.post.id}/'

    def test_destroy_soft_deletes_post(self):
        r = self.client.delete(self.url, HTTP_AUTHORIZATION=f'Token {self.f_token}')
        self.assertEqual(r.status_code, 204)
        self.post.refresh_from_db()
        self.assertFalse(self.post.is_visible)
        self.assertTrue(Post.objects.filter(id=self.post.id).exists())

    def test_hidden_post_not_in_public_list(self):
        self.post.is_visible = False
        self.post.save(update_fields=['is_visible'])
        r = self.client.get('/api/posts/')
        self.assertEqual(r.status_code, 200)
        ids = [p['id'] for p in r.data]
        self.assertNotIn(self.post.id, ids)

    def test_hidden_post_not_in_search(self):
        self.post.is_visible = False
        self.post.save(update_fields=['is_visible'])
        r = self.client.get('/api/posts/search_by_keyword/', {'q': 'Test'})
        ids = [p['id'] for p in r.data]
        self.assertNotIn(self.post.id, ids)

    def test_owner_sees_own_hidden_post(self):
        self.post.is_visible = False
        self.post.save(update_fields=['is_visible'])
        r = self.client.get('/api/posts/', HTTP_AUTHORIZATION=f'Token {self.f_token}')
        ids = [p['id'] for p in r.data]
        self.assertIn(self.post.id, ids)


class PostExpiryTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        _d, _dt, _up, self.union = make_geo(prefix_ids=6000)
        self.product = make_product()
        self.farmer = make_user('farmer', 'expfarmer', self.union)
        self.post = make_post(self.farmer, self.union, self.product,
                              qty='100', price='50', availability=48)
        # Force the post to look already expired.
        Post.objects.filter(pk=self.post.pk).update(
            created_at=timezone.now() - timedelta(hours=72))

    def _run_expire_command(self):
        from django.core.management import call_command
        call_command('expire_posts', verbosity=0)

    def test_expired_post_hidden_by_command(self):
        self._run_expire_command()
        self.post.refresh_from_db()
        self.assertFalse(self.post.is_visible)

    def test_nonexpired_post_stays_visible(self):
        Post.objects.filter(pk=self.post.pk).update(created_at=timezone.now())
        self._run_expire_command()
        self.post.refresh_from_db()
        self.assertTrue(self.post.is_visible)

    def test_zero_availability_never_expires(self):
        Post.objects.filter(pk=self.post.pk).update(
            time_availability=0, created_at=timezone.now() - timedelta(days=30))
        self._run_expire_command()
        self.post.refresh_from_db()
        self.assertTrue(self.post.is_visible)

    def test_expired_post_not_in_public_list(self):
        self._run_expire_command()
        r = self.client.get('/api/posts/')
        ids = [p['id'] for p in r.data]
        self.assertNotIn(self.post.id, ids)