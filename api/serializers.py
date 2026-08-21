from decimal import Decimal
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db import transaction
from .models import Post, Order, OrderItem, Review, ReviewImage, OTP, ProductType, PostImage, Payment, ManualBkashPayment, FarmerBankAccount, BangladeshLocation, Area, PendingPool, Batch, BatchItem, Bid, Notification
from .services import process_new_order, haversine_km, district_centroid
from rest_framework.validators import UniqueValidator

User = get_user_model()


class LocationInfoSerializer(serializers.Serializer):
    """Read-only flattened location object: { id, division, district, upazila, union }."""
    id = serializers.IntegerField(read_only=True)
    level = serializers.CharField(read_only=True)
    name_en = serializers.CharField(read_only=True)
    name_bn = serializers.CharField(read_only=True)
    division = serializers.SerializerMethodField()
    district = serializers.SerializerMethodField()
    upazila = serializers.SerializerMethodField()
    union = serializers.SerializerMethodField()

    def _name(self, obj, level):
        node = obj.parent_chain().get(level)
        return node.name_en if node else None

    def get_division(self, obj):
        return self._name(obj, 'division')

    def get_district(self, obj):
        return self._name(obj, 'district')

    def get_upazila(self, obj):
        return self._name(obj, 'upazila')

    def get_union(self, obj):
        return self._name(obj, 'union')


class UserSerializer(serializers.ModelSerializer):
    avg_rating = serializers.FloatField(source='average_rating', read_only=True, allow_null=True)
    total_sales = serializers.ReadOnlyField()
    ratings_count = serializers.IntegerField(read_only=True)
    service_areas = serializers.JSONField(read_only=True, allow_null=True)
    location = LocationInfoSerializer(read_only=True, allow_null=True)

    email = serializers.EmailField(
        validators=[UniqueValidator(queryset=User.objects.all(), message="Please use a new email/phone number (নতুন ইমেইল/ফোন নম্বর ব্যবহার করুন).")]
    )
    phone_number = serializers.CharField(
        validators=[UniqueValidator(queryset=User.objects.all(), message="Please use a new email/phone number (নতুন ইমেইল/ফোন নম্বর ব্যবহার করুন).")]
    )

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'role', 'name',
            'phone_number', 'address',
            'location', 'is_verified',
            'avg_rating', 'ratings_count', 'total_sales',
            'service_areas', 'bkash_number',
        )
        read_only_fields = ('is_verified', 'avg_rating', 'ratings_count', 'total_sales', 'service_areas', 'location')

class EmailOrPhoneAuthSerializer(serializers.Serializer):
    email_or_phone = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        identifier = attrs.get('email_or_phone')
        password = attrs.get('password')

        if identifier and password:
            from django.contrib.auth import authenticate
            user = authenticate(request=self.context.get('request'),
                                username=identifier, password=password)

            if not user:
                raise serializers.ValidationError('Unable to log in with provided credentials.')
        else:
            raise serializers.ValidationError('Must include "email_or_phone" and "password".')

        attrs['user'] = user
        return attrs

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    location = serializers.PrimaryKeyRelatedField(
        queryset=BangladeshLocation.objects.all(), required=True)
    bkash_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    email = serializers.EmailField(
        required=True,
        validators=[UniqueValidator(queryset=User.objects.all(), message="Please use a new email/phone number (নতুন ইমেইল/ফোন নম্বর ব্যবহার করুন).")]
    )
    phone_number = serializers.CharField(
        required=True,
        validators=[UniqueValidator(queryset=User.objects.all(), message="Please use a new email/phone number (নতুন ইমেইল/ফোন নম্বর ব্যবহার করুন).")]
    )

    class Meta:
        model = User
        fields = (
            'username', 'email', 'password', 'role', 'name',
            'phone_number', 'address', 'location', 'bkash_number'
        )

    def validate_role(self, value):
        if value not in ['farmer', 'customer', 'deliveryman']:
            raise serializers.ValidationError("Role must be 'farmer', 'customer', or 'deliveryman'.")
        return value

    def validate_location(self, value):
        if value.level not in ('union', 'upazila', 'ward'):
            raise serializers.ValidationError("location must be a Union, Upazila, or City Corporation Area (ward).")
        return value

    def validate(self, attrs):
        if attrs.get('role') == 'farmer' and not attrs.get('bkash_number'):
            raise serializers.ValidationError({"bkash_number": "Farmers must provide a bKash number."})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User.objects.create_user(
            password=password,
            **validated_data
        )
        return user


class ProductTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductType
        fields = '__all__'


class PostImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostImage
        fields = ('id', 'image', 'created_at')

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        if instance.image:
            request = self.context.get('request')
            if request is not None:
                rep['image'] = request.build_absolute_uri(instance.image.url)
            else:
                rep['image'] = f"http://192.168.1.100:8000{instance.image.url}"
        return rep


class PostSerializer(serializers.ModelSerializer):
    farmer_name = serializers.ReadOnlyField(source='farmer.name')
    farmer_username = serializers.ReadOnlyField(source='farmer.username')
    farmer_phone = serializers.SerializerMethodField()
    farmer_avg_rating = serializers.FloatField(source='farmer.average_rating', read_only=True, allow_null=True)
    farmer_ratings_count = serializers.IntegerField(source='farmer.ratings_count', read_only=True)
    total_price = serializers.SerializerMethodField()
    effective_weight_kg = serializers.ReadOnlyField()
    product_type_name_bn = serializers.ReadOnlyField(source='product_type.name_bn', allow_null=True)
    images = PostImageSerializer(many=True, read_only=True)
    location = serializers.PrimaryKeyRelatedField(queryset=BangladeshLocation.objects.all(), required=True)
    location_info = LocationInfoSerializer(source='location', read_only=True, allow_null=True)
    area = serializers.SerializerMethodField()
    distance_km = serializers.SerializerMethodField()
    has_pending_bid = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = '__all__'
        read_only_fields = ('farmer', 'is_visible')

    def get_has_pending_bid(self, obj):
        """Whether the requesting customer already placed a bid on this post."""
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated or request.user.role != 'customer':
            return False
        return obj.bids.filter(customer=request.user).exists()

    def get_total_price(self, obj):
        return obj.total_price

    def get_farmer_phone(self, obj):
        request = self.context.get('request')
        if request is not None and not request.user.is_authenticated:
            return None
        return obj.farmer.phone_number

    def get_distance_km(self, obj):
        """Approx distance (km) from the requesting customer's union district centroid.

        Client passes `?union=<customer_union_id>`. Uses the official district
        reference coordinates (district centroid) for both endpoints.
        """
        request = self.context.get('request')
        if request is None:
            return None
        union_id = request.query_params.get('union')
        if not union_id:
            return None
        cust = BangladeshLocation.objects.filter(id=union_id).first()
        if cust is None or obj.location is None:
            return None
        cust_lat, cust_lng = district_centroid(cust)
        post_lat, post_lng = district_centroid(obj.location)
        if cust_lat is None or post_lat is None:
            return None
        return haversine_km(cust_lat, cust_lng, post_lat, post_lng)

    def get_area(self, obj):
        if obj.location is None:
            return None
        upazila = obj.location if obj.location.level == 'upazila' else obj.location.parent
        if upazila is None:
            return None
        area = Area.objects.filter(upazilas=upazila, is_active=True).first()
        if area is None:
            return None
        return {'id': area.id, 'name': area.name, 'threshold_kg': area.threshold_kg}

    def validate_location(self, value):
        if value.level not in ('union', 'upazila'):
            raise serializers.ValidationError("location must be a Union or Upazila.")
        return value

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation['location'] = representation.pop('location_info', None)
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            representation.pop('collection_point_address', None)
        if instance.image:
            request = self.context.get('request')
            if request is not None:
                representation['image'] = request.build_absolute_uri(instance.image.url)
            else:
                representation['image'] = f"http://192.168.1.100:8000{instance.image.url}"
        return representation

    def validate_total_weight_kg(self, value):
        if value <= 0:
            raise serializers.ValidationError("Quantity/Weight must be greater than zero.")
        return value

    def validate_price_per_kg(self, value):
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than zero.")
        return value

    def validate(self, attrs):
        product_type = attrs.get('product_type')
        price_per_kg = attrs.get('price_per_kg')
        quantity_type = attrs.get('quantity_type', getattr(self.instance, 'quantity_type', 'kg'))

        # Per-piece posts must declare an estimated weight per piece.
        if quantity_type == 'piece':
            est = attrs.get('est_weight_kg', getattr(self.instance, 'est_weight_kg', None))
            if not est or est <= 0:
                raise serializers.ValidationError(
                    {"est_weight_kg": "Per-piece posts require an estimated weight per piece (est_weight_kg)."})

        if product_type and product_type.max_price_limit is not None and price_per_kg:
            if price_per_kg > product_type.max_price_limit:
                raise serializers.ValidationError(
                    f"Price per unit ({price_per_kg}) exceeds the maximum limit ({product_type.max_price_limit}) for {product_type.name_bn}."
                )
        return attrs

    def create(self, validated_data):
        return Post.objects.create(**validated_data)

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance



class BulkOrderItemSerializer(serializers.Serializer):
    post = serializers.PrimaryKeyRelatedField(queryset=Post.objects.all())
    quantity_kg = serializers.DecimalField(max_digits=10, decimal_places=2)


class BulkOrderSerializer(serializers.Serializer):
    items = BulkOrderItemSerializer(many=True)
    delivery_address = serializers.CharField()

    def validate(self, attrs):
        items = attrs['items']
        if not items:
            raise serializers.ValidationError("At least one item is required.")

        for item in items:
            post = item['post']
            qty = item['quantity_kg']
            if qty <= 0:
                raise serializers.ValidationError({"items": f"Quantity must be > 0 for {post.title}."})
            if qty > post.total_weight_kg:
                raise serializers.ValidationError({"items": f"Insufficient stock for {post.title}. Only {post.total_weight_kg}kg available."})
        return attrs

    def create(self, validated_data):
        items_data = validated_data['items']
        delivery_address = validated_data['delivery_address']
        customer = self.context['request'].user

        with transaction.atomic():
            # Lock all posts upfront
            post_ids = [item['post'].pk for item in items_data]
            posts = {p.pk: p for p in Post.objects.select_for_update().filter(pk__in=post_ids)}

            # Re-validate stock with locked rows
            for item in items_data:
                post = posts[item['post'].pk]
                qty = item['quantity_kg']
                if post.total_weight_kg < qty:
                    raise serializers.ValidationError(
                        {"items": f"Insufficient stock for {post.title}. Only {post.total_weight_kg}kg available."}
                    )

            # Create one Order with all items
            order_items = []
            total_paid = Decimal('0')
            for item in items_data:
                post = posts[item['post'].pk]
                qty = item['quantity_kg']
                subtotal = round(qty * post.price_per_kg, 2)
                total_paid += subtotal

                post.total_weight_kg -= qty
                post.save(update_fields=['total_weight_kg'])

                order_items.append({
                    'post': post,
                    'farmer': post.farmer,
                    'quantity_kg': qty,
                    'quantity_type': post.quantity_type,
                    'est_weight_kg': post.est_weight_kg,
                    'price_per_kg': post.price_per_kg,
                    'subtotal': subtotal,
                })

            platform_fee = round(total_paid * Decimal('0.10'), 2)
            farmer_payout = total_paid - platform_fee

            order = Order.objects.create(
                customer=customer,
                total_paid=total_paid,
                platform_fee=platform_fee,
                farmer_payout=farmer_payout,
                delivery_address=delivery_address,
                advance_amount=round(total_paid / 2, 2),
                final_amount=round(total_paid / 2, 2),
                status='pending',
            )
            for item_data in order_items:
                OrderItem.objects.create(order=order, **item_data)

            # Process each item for pooling (per-farmer, per-location, per-product-type)
            for oi in order.items.select_related('post').all():
                _process_order_item(oi)

            return order


def _process_order_item(order_item):
    """Feed a single OrderItem into the pooling/batching engine."""
    from .services import area_for_post, PendingPool
    post = order_item.post
    area = area_for_post(post)
    if area is None:
        return
    from decimal import Decimal as D
    pool, created = PendingPool.objects.select_for_update().get_or_create(
        area=area,
        union=post.location,
        product_type=post.product_type,
        defaults={'pending_quantity_kg': order_item.effective_weight_kg},
    )
    if not created:
        pool.pending_quantity_kg += order_item.effective_weight_kg
        pool.save(update_fields=['pending_quantity_kg'])


class OrderItemSerializer(serializers.ModelSerializer):
    post_title = serializers.ReadOnlyField(source='post.title')
    post_location = LocationInfoSerializer(source='post.location', read_only=True, allow_null=True)
    post_collection_point_address = serializers.ReadOnlyField(source='post.collection_point_address')
    farmer_name = serializers.ReadOnlyField(source='farmer.name')
    farmer_phone = serializers.ReadOnlyField(source='farmer.phone_number')

    class Meta:
        model = OrderItem
        fields = ('id', 'post', 'post_title', 'farmer', 'farmer_name', 'farmer_phone',
                  'quantity_kg', 'quantity_type', 'est_weight_kg', 'price_per_kg', 'subtotal',
                  'post_location', 'post_collection_point_address')


class OrderSerializer(serializers.ModelSerializer):
    customer_username = serializers.ReadOnlyField(source='customer.username')
    customer_name = serializers.ReadOnlyField(source='customer.name')
    customer_phone = serializers.ReadOnlyField(source='customer.phone_number')
    items = OrderItemSerializer(many=True, read_only=True)
    # Legacy convenience fields (derived from first item for backward compat)
    post_title = serializers.SerializerMethodField()
    post_farmer_name = serializers.SerializerMethodField()
    post_farmer_id = serializers.SerializerMethodField()
    post_farmer_phone = serializers.SerializerMethodField()
    post_location = serializers.SerializerMethodField()
    post_collection_point_address = serializers.SerializerMethodField()
    post = serializers.SerializerMethodField()
    quantity_kg = serializers.SerializerMethodField()
    quantity_type = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = '__all__'
        read_only_fields = ('customer', 'total_paid', 'platform_fee', 'farmer_payout', 'status', 'delivered_at',
                           'bkash_payment_id', 'bkash_trx_id', 'bkash_payment_status', 'paid_amount', 'paid_at')

    def _first_item(self, obj):
        items = getattr(obj, '_prefetched_items', None)
        if items is None:
            items = list(obj.items.select_related('post', 'farmer', 'post__location').all())
            obj._prefetched_items = items
        return items[0] if items else None

    def get_post(self, obj):
        fi = self._first_item(obj)
        return fi.post_id if fi else None

    def get_post_title(self, obj):
        fi = self._first_item(obj)
        return fi.post.title if fi else None

    def get_post_farmer_name(self, obj):
        fi = self._first_item(obj)
        return fi.farmer.name if fi and fi.farmer else None

    def get_post_farmer_id(self, obj):
        fi = self._first_item(obj)
        return fi.farmer_id if fi else None

    def get_post_farmer_phone(self, obj):
        fi = self._first_item(obj)
        return fi.farmer.phone_number if fi and fi.farmer else None

    def get_post_location(self, obj):
        fi = self._first_item(obj)
        if fi and fi.post and fi.post.location:
            return LocationInfoSerializer(fi.post.location).data
        return None

    def get_post_collection_point_address(self, obj):
        fi = self._first_item(obj)
        return fi.post.collection_point_address if fi and fi.post else None

    def get_quantity_kg(self, obj):
        fi = self._first_item(obj)
        return str(fi.quantity_kg) if fi else '0'

    def get_quantity_type(self, obj):
        fi = self._first_item(obj)
        return fi.quantity_type if fi else 'kg'


class ReviewImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReviewImage
        fields = ('id', 'image', 'image_url')

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        if instance.image:
            request = self.context.get('request')
            if request is not None:
                rep['image'] = request.build_absolute_uri(instance.image.url)
            else:
                rep['image'] = f"http://192.168.1.100:8000{instance.image.url}"
            print(f"[DEBUG ReviewImageSerializer] image → {rep['image']}")
        return rep


class ReviewSerializer(serializers.ModelSerializer):
    customer_username = serializers.ReadOnlyField(source='customer.username')
    customer_name = serializers.SerializerMethodField()
    post_title = serializers.SerializerMethodField()
    farmer_username = serializers.SerializerMethodField()
    farmer_id = serializers.SerializerMethodField()
    images = ReviewImageSerializer(many=True, read_only=True)

    def get_customer_name(self, obj):
        request = self.context.get('request')
        if request is not None and not request.user.is_authenticated:
            return None
        return obj.customer.name

    def get_post_title(self, obj):
        if obj.post:
            return obj.post.title
        return obj.post_title

    def get_farmer_username(self, obj):
        if obj.farmer:
            return obj.farmer.username
        return None

    def get_farmer_id(self, obj):
        if obj.farmer:
            return obj.farmer.id
        return None

    class Meta:
        model = Review
        fields = '__all__'
        read_only_fields = ('customer',)

    def create(self, validated_data):
        post = validated_data.get('post')
        validated_data['farmer'] = post.farmer if post else None
        validated_data.setdefault('post_title', post.title if post else '')
        return super().create(validated_data)

    def validate(self, attrs):
        customer = self.context['request'].user
        post = attrs.get('post')
        rating = attrs.get('rating')

        if rating < 1 or rating > 5:
            raise serializers.ValidationError({"rating": "Rating must be between 1 and 5."})

        has_completed_order = OrderItem.objects.filter(
            order__customer=customer,
            post=post,
            order__status='completed'
        ).exists()

        if not has_completed_order:
            raise serializers.ValidationError(
                {"non_field_errors": "You can only review a product after completing a purchase for it."}
            )

        return attrs


class BidSerializer(serializers.ModelSerializer):
    customer_username = serializers.ReadOnlyField(source='customer.username')
    customer_name = serializers.ReadOnlyField(source='customer.name')
    post_title = serializers.ReadOnlyField(source='post.title')
    farmer_username = serializers.SerializerMethodField()

    class Meta:
        model = Bid
        fields = (
            'id', 'post', 'post_title', 'customer', 'customer_username',
            'customer_name', 'farmer_username', 'amount', 'counter_amount',
            'status', 'message', 'created_at', 'updated_at',
        )
        read_only_fields = ('customer', 'status', 'counter_amount')

    def get_farmer_username(self, obj):
        return obj.post.farmer.username

    def validate(self, attrs):
        request = self.context.get('request')
        post = attrs.get('post')
        if request is not None:
            if request.user.role != 'customer':
                raise serializers.ValidationError({"non_field_errors": "Only customers can place a bid."})
            existing = Bid.objects.filter(customer=request.user, post=post).first()
            if existing:
                raise serializers.ValidationError(
                    {"non_field_errors": "You have already placed a bid on this post. "
                                         "Await the farmer's counter-offer or rejection."})
        return attrs

    def create(self, validated_data):
        validated_data['customer'] = self.context['request'].user
        return super().create(validated_data)


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ('user', 'transaction_id', 'status', 'gateway_response')


class ManualBkashPaymentSerializer(serializers.ModelSerializer):
    user_username = serializers.ReadOnlyField(source='user.username')
    order_id_display = serializers.ReadOnlyField(source='order.id', allow_null=True)

    class Meta:
        model = ManualBkashPayment
        fields = ('id', 'user', 'user_username', 'order', 'order_id_display',
                  'sender_number', 'amount', 'trx_id', 'payment_type',
                  'status', 'admin_note', 'payment', 'approved_by', 'approved_at',
                  'created_at', 'updated_at')
        read_only_fields = ('user', 'status', 'admin_note', 'payment',
                            'approved_by', 'approved_at')


class FarmerBankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = FarmerBankAccount
        fields = '__all__'
        read_only_fields = ('farmer',)


class BangladeshLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = BangladeshLocation
        fields = ('id', 'geo_id', 'name_en', 'name_bn', 'level', 'parent',
                  'latitude', 'longitude', 'city_corp', 'ward_no')


class AreaSerializer(serializers.ModelSerializer):
    upazilas = serializers.PrimaryKeyRelatedField(
        queryset=BangladeshLocation.objects.filter(level='upazila'),
        many=True, required=False)

    class Meta:
        model = Area
        fields = ('id', 'name', 'upazilas', 'threshold_kg', 'is_active',
                  'created_at', 'updated_at')
        read_only_fields = ('created_at', 'updated_at')


class BatchItemSerializer(serializers.ModelSerializer):
    farmer_name = serializers.ReadOnlyField(source='farmer.name')
    farmer_phone = serializers.ReadOnlyField(source='farmer.phone_number')
    post_title = serializers.SerializerMethodField()
    order_status = serializers.ReadOnlyField(source='order.status')
    collection_point_address = serializers.SerializerMethodField()

    class Meta:
        model = BatchItem
        fields = ('id', 'order', 'post_title', 'quantity_kg', 'farmer',
                  'farmer_name', 'farmer_phone', 'order_status',
                  'collection_point_address')

    def get_post_title(self, obj):
        items = list(obj.order.items.select_related('post').all()[:3])
        titles = ', '.join(i.post.title for i in items)
        if obj.order.items.count() > 3:
            titles += '...'
        return titles or '(unknown)'

    def get_collection_point_address(self, obj):
        items = list(obj.order.items.select_related('post').all()[:1])
        return items[0].post.collection_point_address if items and items[0].post else None


class BatchSerializer(serializers.ModelSerializer):
    area = AreaSerializer(read_only=True)
    union = LocationInfoSerializer(read_only=True)
    product_type_name_bn = serializers.ReadOnlyField(source='product_type.name_bn', allow_null=True)
    product_type_name_en = serializers.ReadOnlyField(source='product_type.name_en', allow_null=True)
    deliveryman_name = serializers.ReadOnlyField(source='deliveryman.name', allow_null=True)
    deliveryman_phone = serializers.ReadOnlyField(source='deliveryman.phone_number', allow_null=True)
    items = BatchItemSerializer(many=True, read_only=True)
    distance_km = serializers.SerializerMethodField()

    class Meta:
        model = Batch
        fields = '__all__'
        read_only_fields = ('status', 'deliveryman', 'total_quantity_kg',
                            'total_value', 'assigned_at', 'delivered_at')

    def get_distance_km(self, obj):
        """Approx distance (km) from the requesting deliveryman's union district
        centroid to the batch's union district centroid (closest-first sorting)."""
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated or request.user.role != 'deliveryman':
            return None
        from .services import district_centroid, haversine_km
        dm = request.user
        dm_lat, dm_lng = district_centroid(dm.location)
        b_lat, b_lng = district_centroid(obj.union)
        if dm_lat is None or b_lat is None:
            return None
        return haversine_km(dm_lat, dm_lng, b_lat, b_lng)


class PendingPoolSerializer(serializers.ModelSerializer):
    union = LocationInfoSerializer(read_only=True)
    area_name = serializers.ReadOnlyField(source='area.name')
    product_type_name_bn = serializers.ReadOnlyField(source='product_type.name_bn', allow_null=True)

    class Meta:
        model = PendingPool
        fields = '__all__'


class UserServiceAreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'service_areas')


class NotificationSerializer(serializers.ModelSerializer):
    batch_id = serializers.ReadOnlyField(source='batch.id', allow_null=True)
    order_id = serializers.ReadOnlyField(source='order.id', allow_null=True)

    class Meta:
        model = Notification
        fields = ('id', 'notification_type', 'title', 'message',
                  'batch_id', 'order_id', 'is_read', 'created_at')
        read_only_fields = ('user', 'notification_type', 'title', 'message',
                            'batch', 'order', 'is_read', 'created_at')


class SettlementDueSerializer(serializers.ModelSerializer):
    """Admin view of a farmer-due settlement row (per successful order-linked payment)."""
    farmer_id = serializers.SerializerMethodField()
    farmer_name = serializers.SerializerMethodField()
    farmer_username = serializers.SerializerMethodField()
    order_id = serializers.ReadOnlyField(source='order.id', allow_null=True)
    order_title = serializers.SerializerMethodField()
    payout_amount = serializers.ReadOnlyField(source='order.farmer_payout', allow_null=True)

    class Meta:
        model = Payment
        fields = ('id', 'transaction_id', 'farmer_id', 'farmer_name', 'farmer_username',
                  'order_id', 'order_title', 'payout_amount', 'paid_at',
                  'settlement_appended', 'settlement_paid', 'settlement_paid_at')
        read_only_fields = fields

    def _get_farmers(self, obj):
        if not obj.order:
            return []
        return list(obj.order.items.select_related('farmer').values_list('farmer', flat=True).distinct())

    def get_farmer_id(self, obj):
        farmers = self._get_farmers(obj)
        return farmers[0] if len(farmers) == 1 else None

    def get_farmer_name(self, obj):
        if not obj.order:
            return None
        farmers = obj.order.items.select_related('farmer').all()
        names = [i.farmer.name for i in farmers if i.farmer]
        return ', '.join(names) if names else None

    def get_farmer_username(self, obj):
        if not obj.order:
            return None
        farmers = obj.order.items.select_related('farmer').all()
        usernames = [i.farmer.username for i in farmers if i.farmer]
        return ', '.join(usernames) if usernames else None

    def get_order_title(self, obj):
        if not obj.order:
            return None
        items = list(obj.order.items.select_related('post').all()[:3])
        titles = ', '.join(i.post.title for i in items)
        if obj.order.items.count() > 3:
            titles += '...'
        return titles or None