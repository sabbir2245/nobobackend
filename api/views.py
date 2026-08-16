import math
import random
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.db.models import Sum, Q
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from rest_framework import viewsets, permissions, status, generics
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token

from .models import Post, Order, Review, ReviewImage, OTP, ProductType, PostImage, BangladeshLocation, Area, Batch, BatchItem, PendingPool, Payment
from .serializers import (
    UserSerializer, RegisterSerializer, PostSerializer,
    OrderSerializer, ReviewSerializer, EmailOrPhoneAuthSerializer,
    ProductTypeSerializer, BulkOrderSerializer,
    BangladeshLocationSerializer, AreaSerializer, BatchSerializer,
)
from .permissions import IsFarmer, IsCustomer, IsAdminUser, IsDeliveryman, IsOwnerOrReadOnly

User = get_user_model()

def calculate_haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)



class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, created = Token.objects.get_or_create(user=user)
        return Response({
            "token": token.key,
            "user": UserSerializer(user).data
        }, status=status.HTTP_201_CREATED)


class CustomLoginView(ObtainAuthToken):
    permission_classes = [permissions.AllowAny]
    serializer_class = EmailOrPhoneAuthSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        # Rotate: revoke prior tokens so only the newest login stays valid.
        Token.objects.filter(user=user).delete()
        token = Token.objects.create(user=user)
        return Response({
            "token": token.key,
            "user": UserSerializer(user).data
        }, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        request.auth.delete()
        return Response({"message": "Logged out successfully."}, status=status.HTTP_200_OK)

class UserProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class UserManagementViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        user = self.get_object()
        user.is_verified = True
        user.save()
        return Response({"status": f"User {user.username} has been verified.", "user": UserSerializer(user).data})

    @action(detail=True, methods=['post'])
    def suspend(self, request, pk=None):
        user = self.get_object()
        user.is_active = False
        user.save()
        return Response({"status": f"User {user.username} has been suspended."})

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        user = self.get_object()
        user.is_active = True
        user.save()
        return Response({"status": f"User {user.username} has been activated."})

class ProductTypeViewSet(viewsets.ModelViewSet):
    queryset = ProductType.objects.all().order_by('name_en')
    serializer_class = ProductTypeSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy', 'set_max_price']:
            return [permissions.IsAuthenticated(), IsAdminUser()]
        return [permissions.AllowAny()]

    @action(detail=True, methods=['patch'], permission_classes=[permissions.IsAuthenticated, IsAdminUser])
    def set_max_price(self, request, pk=None):
        product_type = self.get_object()
        amount = request.data.get('max_price_limit')
        if amount is None:
            return Response({"error": "Provide 'max_price_limit'."}, status=400)
        try:
            product_type.max_price_limit = Decimal(str(amount))
            product_type.save()
            return Response(ProductTypeSerializer(product_type).data)
        except (TypeError, ValueError, InvalidOperation):
            return Response({"error": "Invalid amount."}, status=400)


class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.all().order_by('-created_at')
    serializer_class = PostSerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [permissions.IsAuthenticated(), IsFarmer()]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsOwnerOrReadOnly()]
        return [permissions.AllowAny()]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        post = serializer.save(farmer=request.user)
        images = request.FILES.getlist('uploaded_images')
        for img in images[:3]:
            PostImage.objects.create(post=post, image=img)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        serializer.save(farmer=self.request.user)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(Q(title__icontains=search) | Q(description__icontains=search))

        product_type = request.query_params.get('product_type')
        if product_type:
            queryset = queryset.filter(product_type_id=product_type)

        farmer_id = request.query_params.get('farmer_id')
        if farmer_id:
            queryset = queryset.filter(farmer_id=farmer_id)

        # Location-based filtering (replaces legacy lat/lng/radius)
        area_id = request.query_params.get('area')
        if area_id:
            area = Area.objects.filter(id=area_id, is_active=True).first()
            if area:
                queryset = queryset.filter(
                    location__parent__in=area.upazilas.all()
                ).distinct()

        # NOTE: `union` param is used by the serializer as the customer's origin
        # for distance_km (approx km from district centroid), NOT as a hard filter.

        upazila_id = request.query_params.get('upazila')
        if upazila_id:
            queryset = queryset.filter(location__parent_id=upazila_id)

        district_id = request.query_params.get('district')
        if district_id:
            district_ids = list(BangladeshLocation.objects.filter(
                geo_id=district_id, level='district').values_list('id', flat=True))
            upazila_ids = list(BangladeshLocation.objects.filter(
                parent_id__in=district_ids, level='upazila').values_list('id', flat=True))
            union_ids = list(BangladeshLocation.objects.filter(
                parent_id__in=upazila_ids, level='union').values_list('id', flat=True))
            queryset = queryset.filter(location_id__in=union_ids)

        serializer = self.get_serializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny])
    def search_by_keyword(self, request):
        query_str = request.query_params.get('q', '').strip()

        if not query_str:
            return Response(
                {"error": "Missing required parameter. Please provide 'q'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        queryset = self.get_queryset().filter(
            Q(title__icontains=query_str) | Q(description__icontains=query_str)
        )

        serializer = self.get_serializer(queryset, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer

    def get_permissions(self):
        if self.action in ['create', 'bulk_create']:
            return [permissions.IsAuthenticated(), IsCustomer()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin' or user.is_staff:
            return Order.objects.all().order_by('-created_at')
        elif user.role == 'farmer':
            return Order.objects.filter(post__farmer=user).order_by('-created_at')
        elif user.role == 'deliveryman':
            # Delivery is handled per-union Batch; a deliveryman sees the orders
            # inside the batches they are delivering.
            return Order.objects.filter(
                batch_items__batch__deliveryman=user
            ).order_by('-created_at').distinct()
        else:
            return Order.objects.filter(customer=user).order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=False, methods=['post'])
    def bulk_create(self, request, pk=None):
        serializer = BulkOrderSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        orders = serializer.save()
        response_serializer = OrderSerializer(orders, many=True, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def complete(self, request, pk=None):
        order = self.get_object()
        user = request.user

        if user.role != 'admin' and not user.is_staff and order.customer != user:
            return Response({"error": "You do not have permission to complete this order."}, status=403)

        if order.status not in ['pending']:
            return Response({"error": f"Cannot complete order in '{order.status}' status."}, status=400)

        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)
            if order.status == 'completed':
                return Response(OrderSerializer(order).data)
            order.status = 'completed'
            order.delivered_at = timezone.now()
            order.save()
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def cancel(self, request, pk=None):
        order = self.get_object()
        user = request.user

        if user.role != 'admin' and not user.is_staff and order.customer != user and order.post.farmer != user:
            return Response({"error": "You do not have permission to cancel this order."}, status=403)

        if order.status not in ['pending']:
            return Response({"error": "Only pending orders can be cancelled."}, status=400)

        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)
            order.status = 'cancelled'
            order.save()
            post = order.post
            post = Post.objects.select_for_update().get(pk=post.pk)
            post.total_weight_kg += order.quantity_kg
            post.save()
        return Response(OrderSerializer(order).data)


class ReviewViewSet(viewsets.ModelViewSet):
    queryset = Review.objects.all().order_by('-created_at')
    serializer_class = ReviewSerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [permissions.IsAuthenticated(), IsCustomer()]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsOwnerOrReadOnly()]
        return [permissions.AllowAny()]

    def create(self, request, *args, **kwargs):
        print(f"[DEBUG ReviewViewSet.create] User={request.user.id} POST={dict(request.POST)} FILES={len(request.FILES.getlist('uploaded_images'))}")

        post_id = request.data.get('post')
        if post_id:
            existing = Review.objects.filter(customer=request.user, post_id=post_id).first()
            if existing:
                print(f"[DEBUG ReviewViewSet.create] Duplicate review blocked — user={request.user.id} post={post_id}")
                return Response(
                    {"non_field_errors": "You have already reviewed this product."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review = serializer.save(customer=request.user)
        print(f"[DEBUG ReviewViewSet.create] Review #{review.id} saved")

        images = request.FILES.getlist('uploaded_images')
        for i, img in enumerate(images[:3]):
            ri = ReviewImage.objects.create(review=review, image=img)
            print(f"[DEBUG ReviewViewSet.create] ReviewImage #{ri.id} created for review #{review.id} ({img.name})")

        serializer = self.get_serializer(review, context={'request': request})
        headers = self.get_success_headers(serializer.data)
        print(f"[DEBUG ReviewViewSet.create] Response data keys: {list(serializer.data.keys())}")
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        farmer_id = request.query_params.get('farmer_id')
        if farmer_id:
            queryset = queryset.filter(farmer_id=farmer_id)
        post_id = request.query_params.get('post_id')
        if post_id:
            queryset = queryset.filter(post_id=post_id)
        customer_id = request.query_params.get('customer_id')
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class FarmerProfileView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        farmer = User.objects.filter(id=pk, role='farmer').first()
        if farmer is None:
            return Response({"detail": "Farmer not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = UserSerializer(farmer, context={'request': request})
        return Response(serializer.data)


class FarmerWalletView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsFarmer]

    def get(self, request):
        farmer = request.user

        pending_payouts = Order.objects.filter(
            post__farmer=farmer,
            status__in=['pending']
        ).aggregate(sum=Sum('farmer_payout'))['sum'] or 0.00

        total_earnings = Order.objects.filter(
            post__farmer=farmer,
            status='completed'
        ).aggregate(sum=Sum('farmer_payout'))['sum'] or 0.00

        total_commission = Order.objects.filter(
            post__farmer=farmer,
            status='completed'
        ).aggregate(sum=Sum('platform_fee'))['sum'] or 0.00

        recent_orders = Order.objects.filter(post__farmer=farmer).order_by('-created_at')[:10]
        recent_orders_serialized = OrderSerializer(recent_orders, many=True).data

        return Response({
            "pending_payouts": pending_payouts,
            "total_earnings": total_earnings,
            "total_commission_deductions": total_commission,
            "recent_transactions": recent_orders_serialized
        })


class AdminAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]

    def get(self, request):
        completed_gmv = Order.objects.filter(status='completed').aggregate(sum=Sum('total_paid'))['sum'] or 0.00
        total_gmv = Order.objects.exclude(status='cancelled').aggregate(sum=Sum('total_paid'))['sum'] or 0.00

        realized_profit = Order.objects.filter(status='completed').aggregate(sum=Sum('platform_fee'))['sum'] or 0.00
        pending_profit = Order.objects.filter(status__in=['pending']).aggregate(sum=Sum('platform_fee'))['sum'] or 0.00

        active_users = User.objects.filter(is_active=True).count()
        farmers_count = User.objects.filter(role='farmer').count()
        customers_count = User.objects.filter(role='customer').count()

        hotspots = []
        posts_locations = Post.objects.all().select_related('farmer', 'location__parent__parent').values(
            'id', 'title', 'farmer__username', 'location__name_en',
            'location__parent__parent__latitude', 'location__parent__parent__longitude')
        for loc in posts_locations:
            hotspots.append({
                "type": "post",
                "id": loc['id'],
                "label": loc['title'],
                "lat": loc['location__parent__parent__latitude'],
                "lng": loc['location__parent__parent__longitude'],
                "owner": loc['farmer__username'],
                "location": loc['location__name_en'],
            })

        return Response({
            "metrics": {
                "total_gmv": total_gmv,
                "completed_gmv": completed_gmv,
                "realized_profit": realized_profit,
                "pending_profit": pending_profit
            },
            "user_stats": {
                "active_users": active_users,
                "farmers": farmers_count,
                "customers": customers_count
            },
            "hotspots": hotspots
        })


# =============================================================================
# DELIVERYMAN SERVICE AREAS & LOCATION HIERARCHY
# =============================================================================

class BangladeshLocationView(APIView):
    """
    GET /api/locations/?level=district&parent_id=1
    Returns administrative locations filtered by level and parent.
    
    Levels: division, district, upazila, union, ward
    - To get all divisions: GET /api/locations/?level=division
    - To get districts of a division: GET /api/locations/?level=district&parent_id=<division_id>
    - To get upazilas of a district: GET /api/locations/?level=upazila&parent_id=<district_id>
    - etc.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        level = request.query_params.get('level')
        parent_id = request.query_params.get('parent_id')

        queryset = BangladeshLocation.objects.all()

        if level:
            queryset = queryset.filter(level=level)
        if parent_id:
            queryset = queryset.filter(parent_id=parent_id)

        queryset = queryset.order_by('name_en')
        serializer = BangladeshLocationSerializer(queryset, many=True)
        print(f"[LOCATIONS] Fetched {queryset.count()} locations (level={level}, parent={parent_id})")
        return Response(serializer.data)


class AssignServiceAreaView(APIView):
    """
    GET/POST /api/deliveryman/service-areas/
    
    GET: Returns the deliveryman's current service areas.
    POST: Body { service_areas: [1, 2, 3] } — updates service areas (list of location IDs).
    """
    permission_classes = [permissions.IsAuthenticated, IsDeliveryman]

    def get(self, request):
        print(f"[SERVICE AREAS] User {request.user.id} fetching service areas")
        return Response({
            'service_areas': request.user.service_areas or [],
        })

    def post(self, request):
        service_areas = request.data.get('service_areas', [])
        print(f"[SERVICE AREAS] User {request.user.id} setting service areas: {service_areas}")

        if not isinstance(service_areas, list):
            return Response({"error": "service_areas must be a list."}, status=400)

        user = request.user
        user.service_areas = service_areas
        user.save(update_fields=['service_areas'])

        return Response({
            'status': 'ok',
            'service_areas': user.service_areas,
        })


# =============================================================================
# AREAS & BATCHES (delivery system)
# =============================================================================

class AreaViewSet(viewsets.ModelViewSet):
    queryset = Area.objects.all().order_by('name')
    serializer_class = AreaSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAuthenticated(), IsAdminUser()]
        return [permissions.AllowAny()]


class BatchViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Batch.objects.all().select_related('area', 'union', 'product_type', 'deliveryman')
    serializer_class = BatchSerializer

    def get_permissions(self):
        if self.action in ['available', 'accept', 'deliver', 'mine']:
            return [permissions.IsAuthenticated(), IsDeliveryman()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff or user.role == 'admin':
            return Batch.objects.all().select_related('area', 'union', 'product_type', 'deliveryman')
        if user.role == 'farmer':
            return Batch.objects.filter(items__farmer=user).distinct().select_related(
                'area', 'union', 'product_type', 'deliveryman')
        if user.role == 'deliveryman':
            return Batch.objects.filter(deliveryman=user).select_related(
                'area', 'union', 'product_type', 'deliveryman')
        return Batch.objects.none()

    @action(detail=False, methods=['get'])
    def available(self, request):
        queryset = Batch.objects.filter(status='pending', deliveryman__isnull=True)
        service_areas = request.user.service_areas or []
        area_ids = [a for a in service_areas if isinstance(a, int)]
        if area_ids:
            queryset = queryset.filter(area_id__in=area_ids)
        serializer = BatchSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def mine(self, request):
        queryset = Batch.objects.filter(deliveryman=request.user).select_related(
            'area', 'union', 'product_type')
        serializer = BatchSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        try:
            with transaction.atomic():
                batch = Batch.objects.select_for_update().get(pk=pk)
                if batch.status != 'pending' or batch.deliveryman is not None:
                    return Response({"error": "This batch is no longer available."}, status=400)
                batch.status = 'assigned'
                batch.deliveryman = request.user
                batch.assigned_at = timezone.now()
                batch.save()
            return Response(BatchSerializer(batch).data)
        except Batch.DoesNotExist:
            return Response({"error": "Batch not found."}, status=404)

    @action(detail=True, methods=['post'])
    def deliver(self, request, pk=None):
        with transaction.atomic():
            try:
                batch = Batch.objects.select_for_update().get(pk=pk)
            except Batch.DoesNotExist:
                return Response({"error": "Batch not found."}, status=404)
            if batch.deliveryman != request.user:
                return Response({"error": "This batch is not assigned to you."}, status=403)
            if batch.status != 'assigned':
                return Response({"error": f"Cannot deliver batch in '{batch.status}' status."}, status=400)
            batch.status = 'delivered'
            batch.delivered_at = timezone.now()
            batch.save()
            # Complete every member order so farmers get paid and customers can review.
            now = timezone.now()
            for item in batch.items.select_related('order'):
                order = item.order
                if order.status == 'pending':
                    order.status = 'completed'
                    order.delivered_at = now
                    order.save(update_fields=['status', 'delivered_at'])
        return Response(BatchSerializer(batch).data)


class DemoPayView(APIView):
    """
    POST /api/payments/demo/
    Body: { items: [{ post, quantity_kg }], delivery_address }
    Creates the bulk orders AND records a successful demo payment for each,
    skipping the real bKash gateway. Intended for local testing / demos only.
    """
    permission_classes = [permissions.IsAuthenticated, IsCustomer]

    def post(self, request):
        import random as _random
        from time import time as _time
        serializer = BulkOrderSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        orders = serializer.save()

        with transaction.atomic():
            for order in orders:
                demo_trx = f"DEMO-{request.user.id}-{_time():.0f}{_random.randint(100, 999)}"
                payment = Payment.objects.create(
                    user=request.user,
                    order=order,
                    amount=order.total_paid,
                    transaction_id=demo_trx,
                    status='success',
                    gateway='bkash',
                    bkash_trx_id=demo_trx,
                    paid_at=timezone.now(),
                    settlement_appended=False,
                )
                from .payments import _append_settlement_xlsx
                if _append_settlement_xlsx(payment):
                    Payment.objects.filter(pk=payment.pk).update(settlement_appended=True)
                order.bkash_payment_id = demo_trx
                order.bkash_trx_id = demo_trx
                order.bkash_payment_status = 'success'
                order.paid_amount = order.total_paid
                order.paid_at = timezone.now()
                order.save(update_fields=[
                    'bkash_payment_id', 'bkash_trx_id', 'bkash_payment_status',
                    'paid_amount', 'paid_at',
                ])

        response_serializer = OrderSerializer(orders, many=True, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
