"""Shared factories for the new-feature test suite (bidding, delivery, escrow)."""
from decimal import Decimal
from rest_framework.authtoken.models import Token
from django.contrib.auth import get_user_model
from api.models import ProductType, BangladeshLocation, Area, Post

User = get_user_model()


def make_geo(prefix_ids=500, lat=23.685, lng=90.3563):
    """division -> district -> upazila -> union chain. District carries coords."""
    division = BangladeshLocation.objects.create(
        geo_id=prefix_ids, name_en='Div', name_bn='D', level='division')
    district = BangladeshLocation.objects.create(
        geo_id=prefix_ids + 1, name_en='Dist', name_bn='Dt', level='district',
        parent=division, latitude=lat, longitude=lng)
    upazila = BangladeshLocation.objects.create(
        geo_id=prefix_ids + 2, name_en='Upazila', name_bn='U', level='upazila', parent=district)
    union = BangladeshLocation.objects.create(
        geo_id=prefix_ids + 3, name_en='Union', name_bn='Un', level='union', parent=upazila)
    return division, district, upazila, union


def make_user(role, username, location, email=None, phone=None):
    return User.objects.create_user(
        username=username,
        email=email or f'{username}@test.com',
        password='testpass123',
        role=role,
        name=username.title(),
        phone_number=phone or '01' + str(abs(hash(username)) % 10**9).zfill(9),
        location=location,
    )


def make_token(user):
    token, _ = Token.objects.get_or_create(user=user)
    return token.key


def make_area(upazila, threshold='100'):
    area = Area.objects.create(name='Area', threshold_kg=Decimal(threshold))
    area.upazilas.add(upazila)
    return area


def make_product():
    return ProductType.objects.create(name_en='Rice', name_bn='চাল')


def make_post(farmer, union, product, qty='1000', price='50', availability=48):
    return Post.objects.create(
        farmer=farmer, title='Test Post', product_type=product,
        total_weight_kg=Decimal(qty), price_per_kg=Decimal(price),
        location=union, time_availability=availability,
    )