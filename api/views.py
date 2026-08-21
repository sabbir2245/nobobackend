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

from .models import Post, Order, OrderItem, Review, ReviewImage, OTP, ProductType, PostImage, BangladeshLocation, Area, Batch, BatchItem, PendingPool, Payment, Bid, Notification
from .serializers import (
    UserSerializer, RegisterSerializer, PostSerializer,
    OrderSerializer, ReviewSerializer, EmailOrPhoneAuthSerializer,
    ProductTypeSerializer, BulkOrderSerializer,
    BangladeshLocationSerializer, AreaSerializer, BatchSerializer,
    BidSerializer, NotificationSerializer, SettlementDueSerializer,
)
from .permissions import IsFarmer, IsCustomer, IsAdminUser, IsDeliveryman, IsOwnerOrReadOnly
from .services import notify_batch_users

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
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            import traceback, json
            tb = traceback.format_exc()
            print(f"[REGISTER] Validation failed: {e}\n{tb}")
            # Re-raise so DRF returns the standard 400 with field errors
            raise
        try:
            user = serializer.save()
            token, created = Token.objects.get_or_create(user=user)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[REGISTER] Save failed: {e}\n{tb}")
            return Response(
                {"error": "Account creation failed. Please try again.", "debug": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
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

    def get_queryset(self):
        """Public listings exclude hidden posts; farmers always see their own."""
        user = getattr(self.request, 'user', None)
        if self.action in ('list', 'retrieve'):
            if user is not None and user.is_authenticated and user.role == 'farmer':
                return Post.objects.filter(
                    is_visible=True
                ) | Post.objects.filter(farmer=user).order_by('-created_at')
            return Post.objects.filter(is_visible=True).order_by('-created_at')
        return Post.objects.all().order_by('-created_at')

    def perform_destroy(self, instance):
        """Soft-delete: hide the post instead of removing it, so historical
        orders, payments, batches and reviews stay intact."""
        instance.is_visible = False
        instance.save(update_fields=['is_visible'])

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
            Q(title__icontains=query_str) | Q(description__icontains=query_str),
            is_visible=True,
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
            return Order.objects.filter(items__farmer=user).distinct().order_by('-created_at')
        elif user.role == 'deliveryman':
            return Order.objects.filter(
                batch_items__batch__deliveryman=user
            ).order_by('-created_at').distinct()
        else:
            return Order.objects.filter(customer=user).order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save()

    def destroy(self, request, pk=None):
        order = self.get_object()
        user = request.user

        if user.role != 'admin' and not user.is_staff and order.customer != user:
            return Response(
                {"error": "You do not have permission to delete this order."},
                status=status.HTTP_403_FORBIDDEN,
            )

        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)

            # Approved and not yet batched: restore stock per item
            if order.status == 'approved' and not BatchItem.objects.filter(order=order).exists():
                for item in order.items.select_related('post').all():
                    post = Post.objects.select_for_update().get(pk=item.post_id)
                    post.total_weight_kg += item.quantity_kg
                    post.save(update_fields=['total_weight_kg'])

            # Drop the order from any batches it belongs to.
            for batch_item in BatchItem.objects.filter(order=order):
                batch = batch_item.batch
                batch_item.delete()
                if not batch.items.exists():
                    batch.delete()

            order.delete()

        return Response(
            {"message": "Order deleted."},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=['post'])
    def bulk_create(self, request, pk=None):
        serializer = BulkOrderSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        response_serializer = OrderSerializer(order, context={'request': request})
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

        is_farmer_of_order = order.items.filter(farmer=user).exists()
        if user.role != 'admin' and not user.is_staff and order.customer != user and not is_farmer_of_order:
            return Response({"error": "You do not have permission to cancel this order."}, status=403)

        if order.status not in ['pending']:
            return Response({"error": "Only pending orders can be cancelled."}, status=400)

        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)
            order.status = 'cancelled'
            order.save()
            # Restore stock per item
            for item in order.items.select_related('post').all():
                post = Post.objects.select_for_update().get(pk=item.post_id)
                post.total_weight_kg += item.quantity_kg
                post.save(update_fields=['total_weight_kg'])
        return Response(OrderSerializer(order).data, context={'request': request})


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


class BidViewSet(viewsets.ModelViewSet):
    """Bidding & negotiation system.

    - Customer places exactly one bid per post (POST /api/bids/).
    - Farmer submits a single counter-offer (POST /api/bids/{id}/counter/).
    - Customer confirms or rejects (POST /api/bids/{id}/accept/ | reject/).
    """
    serializer_class = BidSerializer

    def get_permissions(self):
        if self.action in ['create']:
            return [permissions.IsAuthenticated(), IsCustomer()]
        if self.action in ['counter']:
            return [permissions.IsAuthenticated(), IsFarmer()]
        if self.action in ['accept', 'reject']:
            return [permissions.IsAuthenticated(), IsCustomer()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'farmer':
            return Bid.objects.filter(post__farmer=user)
        if user.role == 'customer':
            return Bid.objects.filter(customer=user)
        if user.is_staff or user.role == 'admin':
            return Bid.objects.all()
        return Bid.objects.none()

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsFarmer])
    def counter(self, request, pk=None):
        """Farmer's single counter-bid / final price, prompted by the question box."""
        bid = self.get_object()
        if bid.post.farmer != request.user:
            return Response({"error": "You are not the farmer of this post."}, status=status.HTTP_403_FORBIDDEN)
        if bid.status != 'pending':
            return Response({"error": f"Cannot counter a bid in '{bid.status}' status."}, status=status.HTTP_400_BAD_REQUEST)
        counter_amount = request.data.get('counter_amount')
        if counter_amount is None:
            return Response({"error": "Provide 'counter_amount' (your final price)."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            amount = Decimal(str(counter_amount))
            if amount <= 0:
                raise ValueError
        except (TypeError, ValueError, InvalidOperation):
            return Response({"error": "Invalid counter amount."}, status=status.HTTP_400_BAD_REQUEST)
        bid.counter_amount = amount
        bid.message = request.data.get('message', '') or ''
        bid.status = 'counter_offered'
        bid.save()
        return Response(BidSerializer(bid).data)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsCustomer])
    def accept(self, request, pk=None):
        bid = self.get_object()
        if bid.customer != request.user:
            return Response({"error": "This bid does not belong to you."}, status=status.HTTP_403_FORBIDDEN)
        if bid.status != 'counter_offered':
            return Response({"error": "Only a counter-offered bid can be accepted."}, status=status.HTTP_400_BAD_REQUEST)
        bid.status = 'accepted'
        bid.save()
        return Response(BidSerializer(bid).data)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsCustomer])
    def reject(self, request, pk=None):
        bid = self.get_object()
        if bid.customer != request.user:
            return Response({"error": "This bid does not belong to you."}, status=status.HTTP_403_FORBIDDEN)
        if bid.status != 'counter_offered':
            return Response({"error": "Only a counter-offered bid can be rejected."}, status=status.HTTP_400_BAD_REQUEST)
        bid.status = 'rejected'
        bid.save()
        return Response(BidSerializer(bid).data)


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

        pending_payouts = OrderItem.objects.filter(
            farmer=farmer,
            order__status__in=['pending', 'approved'],
            order__advance_paid=True,
            order__final_paid=False,
        ).aggregate(sum=Sum('subtotal'))['sum'] or 0.00

        total_earnings = OrderItem.objects.filter(
            farmer=farmer,
            order__status='completed'
        ).aggregate(sum=Sum('subtotal'))['sum'] or 0.00

        total_commission = Order.objects.filter(
            items__farmer=farmer,
            status='completed'
        ).aggregate(sum=Sum('platform_fee'))['sum'] or 0.00

        recent_order_ids = OrderItem.objects.filter(
            farmer=farmer
        ).values_list('order_id', flat=True).distinct()[:10]
        recent_orders = Order.objects.filter(id__in=recent_order_ids).order_by('-created_at')
        recent_orders_serialized = OrderSerializer(recent_orders, many=True, context={'request': request}).data

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
        if self.action in ['available', 'accept', 'deliver', 'mine', 'pick_up', 'in_transit', 'verify_payment']:
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
        queryset = queryset.select_related('area', 'union', 'product_type', 'union__parent__parent')
        batches = list(queryset)
        # Sort closest-first (km from the deliveryman's union district centroid).
        from .services import district_centroid, haversine_km
        dm_lat, dm_lng = district_centroid(request.user.location)
        if dm_lat is not None:
            def _dist(b):
                b_lat, b_lng = district_centroid(b.union)
                if b_lat is None:
                    return float('inf')
                return haversine_km(dm_lat, dm_lng, b_lat, b_lng)
            batches.sort(key=_dist)
        serializer = BatchSerializer(batches, many=True, context={'request': request})
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
                notify_batch_users(
                    batch, 'batch_assigned',
                    f"Batch #{batch.id} has been assigned to a deliveryman",
                    f"Your order in batch #{batch.id} is now being picked up for delivery.")
            return Response(BatchSerializer(batch).data)
        except Batch.DoesNotExist:
            return Response({"error": "Batch not found."}, status=404)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsDeliveryman])
    def pick_up(self, request, pk=None):
        """Step 1: deliveryman picks up the batch at the union — 'Picked the batch at union'."""
        with transaction.atomic():
            try:
                batch = Batch.objects.select_for_update().get(pk=pk)
            except Batch.DoesNotExist:
                return Response({"error": "Batch not found."}, status=404)
            if batch.deliveryman != request.user:
                return Response({"error": "This batch is not assigned to you."}, status=403)
            if batch.status != 'assigned':
                return Response({"error": f"Cannot pick up batch in '{batch.status}' status."}, status=400)
            batch.status = 'picked_up'
            batch.save(update_fields=['status'])
            notify_batch_users(
                batch, 'batch_picked_up',
                f"Batch #{batch.id} has been picked up",
                "Your delivery has been picked up from the collection point.")
        return Response(BatchSerializer(batch).data)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsDeliveryman])
    def in_transit(self, request, pk=None):
        """Step 2: batch is 'On Board / In Transit / Shipped' while being delivered."""
        with transaction.atomic():
            try:
                batch = Batch.objects.select_for_update().get(pk=pk)
            except Batch.DoesNotExist:
                return Response({"error": "Batch not found."}, status=404)
            if batch.deliveryman != request.user:
                return Response({"error": "This batch is not assigned to you."}, status=403)
            if batch.status != 'picked_up':
                return Response({"error": f"Cannot mark in-transit from '{batch.status}' status."}, status=400)
            batch.status = 'in_transit'
            batch.save(update_fields=['status'])
            notify_batch_users(
                batch, 'batch_in_transit',
                f"Batch #{batch.id} is in transit",
                "Your delivery is on the way. Expect it soon.")
        return Response(BatchSerializer(batch).data)

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsDeliveryman])
    def verify_payment(self, request, pk=None):
        """Step 3: at handover, deliveryman confirms 'Payment completed by customer'."""
        with transaction.atomic():
            try:
                batch = Batch.objects.select_for_update().get(pk=pk)
            except Batch.DoesNotExist:
                return Response({"error": "Batch not found."}, status=404)
            if batch.deliveryman != request.user:
                return Response({"error": "This batch is not assigned to you."}, status=403)
            if batch.status not in ('picked_up', 'in_transit'):
                return Response({"error": f"Cannot verify payment in '{batch.status}' status."}, status=400)
            batch.payment_verified = True
            batch.save(update_fields=['payment_verified'])
            notify_batch_users(
                batch, 'payment_verified',
                f"Payment verified for batch #{batch.id}",
                "The deliveryman has confirmed your final payment at handover.")
        return Response(BatchSerializer(batch).data)

    @action(detail=True, methods=['post'])
    def deliver(self, request, pk=None):
        """Step 4 (final): 'Delivered to customer — Mark Complete'. Sets status to 'Delivered'."""
        with transaction.atomic():
            try:
                batch = Batch.objects.select_for_update().get(pk=pk)
            except Batch.DoesNotExist:
                return Response({"error": "Batch not found."}, status=404)
            if batch.deliveryman != request.user:
                return Response({"error": "This batch is not assigned to you."}, status=403)
            if batch.status not in ('picked_up', 'in_transit'):
                return Response({"error": f"Cannot deliver batch in '{batch.status}' status."}, status=400)
            batch.status = 'delivered'
            batch.delivered_at = timezone.now()
            batch.save()
            notify_batch_users(
                batch, 'batch_delivered',
                f"Batch #{batch.id} delivered",
                "Your order has been delivered. Please confirm and review the products.")
            # Complete every member order so farmers get paid and customers can review.
            now = timezone.now()
            for item in batch.items.select_related('order'):
                order = item.order
                if order.status == 'pending':
                    order.status = 'completed'
                    order.delivered_at = now
                    order.save(update_fields=['status', 'delivered_at'])
        return Response(BatchSerializer(batch).data)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """Real-time delivery notifications for the logged-in user.

    - `GET /api/notifications/` — my notifications, newest first.
    - `GET /api/notifications/unread_count/` — count of unread notifications.
    - `POST /api/notifications/<id>/read/` — mark one notification read.
    - `POST /api/notifications/read_all/` — mark all my notifications read.
    """
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        count = self.get_queryset().filter(is_read=False).count()
        return Response({"unread_count": count})

    @action(detail=True, methods=['post'])
    def read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save(update_fields=['is_read'])
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=['post'])
    def read_all(self, request):
        self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({"status": "ok"})


class SettlementDueView(APIView):
    """Admin farmer-due settlement CHECKBOX backend (website admin portal).

    - `GET  /api/payments/settlement/dues/` — list unpaid (and optionally all)
      farmer-due settlement rows, one per successful order-linked payment.
    - `POST /api/payments/settlement/dues/` — mark one payment's farmer payout as
      settled/paid. Body: `{ "payment_id": 123, "paid": true|false }`.
    """
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]

    def get(self, request):
        payments = Payment.objects.filter(
            status='success', order__isnull=False
        ).select_related(
            'order'
        ).prefetch_related(
            'order__items__farmer', 'order__items__post'
        ).order_by('-paid_at', '-id')

        # Default: only show rows whose farmer payout has NOT been marked paid.
        only_unpaid = request.query_params.get('unpaid', 'true').lower() != 'false'
        if only_unpaid:
            payments = payments.filter(settlement_paid=False)

        serializer = SettlementDueSerializer(payments, many=True)
        return Response(serializer.data)

    def post(self, request):
        payment_id = request.data.get('payment_id')
        paid = request.data.get('paid', True)
        if payment_id is None:
            return Response({"error": "Provide 'payment_id'."}, status=400)
        try:
            payment = Payment.objects.get(pk=payment_id, status='success', order__isnull=False)
        except Payment.DoesNotExist:
            return Response({"error": "Payment not found or not a successful order-linked payment."}, status=404)

        payment.settlement_paid = bool(paid)
        if payment.settlement_paid:
            payment.settlement_paid_at = timezone.now()
        else:
            payment.settlement_paid_at = None
        payment.save(update_fields=['settlement_paid', 'settlement_paid_at'])
        return Response(SettlementDueSerializer(payment).data)


class DemoPayView(APIView):
    """
    POST /api/payments/demo/
    Body: { items: [{ post, quantity_kg }], delivery_address }
    Creates bulk orders AND records a successful demo payment,
    skipping the real bKash gateway. Intended for local testing / demos only.
    """
    permission_classes = [permissions.IsAuthenticated, IsCustomer]

    def post(self, request):
        import random as _random
        from time import time as _time
        from decimal import Decimal
        serializer = BulkOrderSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        order = serializer.save()

        with transaction.atomic():
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

        response_serializer = OrderSerializer(order, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
