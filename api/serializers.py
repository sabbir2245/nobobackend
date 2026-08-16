from decimal import Decimal
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db import transaction
from .models import Post, Order, Review, ReviewImage, OTP, ProductType, PostImage, Payment, FarmerBankAccount, BangladeshLocation, Area, PendingPool, Batch, BatchItem
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
        validators=[UniqueValidator(queryset=User.objects.all(), message="A user with this email already exists.")]
    )
    phone_number = serializers.CharField(
        validators=[UniqueValidator(queryset=User.objects.all(), message="A user with this phone number already exists.")]
    )

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'role', 'name',
            'phone_number', 'address',
            'location', 'is_verified',
            'avg_rating', 'ratings_count', 'total_sales',
            'service_areas',
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

    email = serializers.EmailField(
        required=True,
        validators=[UniqueValidator(queryset=User.objects.all(), message="A user with this email already exists.")]
    )
    phone_number = serializers.CharField(
        required=True,
        validators=[UniqueValidator(queryset=User.objects.all(), message="A user with this phone number already exists.")]
    )

    class Meta:
        model = User
        fields = (
            'username', 'email', 'password', 'role', 'name',
            'phone_number', 'address', 'location'
        )

    def validate_role(self, value):
        if value not in ['farmer', 'customer', 'deliveryman']:
            raise serializers.ValidationError("Role must be 'farmer', 'customer', or 'deliveryman'.")
        return value

    def validate_location(self, value):
        if value.level not in ('union', 'upazila'):
            raise serializers.ValidationError("location must be a Union or Upazila.")
        return value

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
    product_type_name_bn = serializers.ReadOnlyField(source='product_type.name_bn', allow_null=True)
    images = PostImageSerializer(many=True, read_only=True)
    location = serializers.PrimaryKeyRelatedField(queryset=BangladeshLocation.objects.all(), required=True)
    location_info = LocationInfoSerializer(source='location', read_only=True, allow_null=True)
    area = serializers.SerializerMethodField()
    distance_km = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = '__all__'
        read_only_fields = ('farmer',)

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
            raise serializers.ValidationError("Weight must be greater than zero.")
        return value

    def validate_price_per_kg(self, value):
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than zero.")
        return value

    def validate(self, attrs):
        product_type = attrs.get('product_type')
        price_per_kg = attrs.get('price_per_kg')
        if product_type and product_type.max_price_limit is not None and price_per_kg:
            if price_per_kg > product_type.max_price_limit:
                raise serializers.ValidationError(
                    f"Price per kg ({price_per_kg}) exceeds the maximum limit ({product_type.max_price_limit}) for {product_type.name_bn}."
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
        items = validated_data['items']
        delivery_address = validated_data['delivery_address']
        customer = self.context['request'].user

        with transaction.atomic():
            orders = []
            for item in items:
                post = Post.objects.select_for_update().get(pk=item['post'].pk)
                qty = item['quantity_kg']

                if post.total_weight_kg < qty:
                    raise serializers.ValidationError(
                        {"items": f"Insufficient stock for {post.title}. Only {post.total_weight_kg}kg available."}
                    )

                total_paid = round(qty * post.price_per_kg, 2)

                post.total_weight_kg -= qty
                post.save()

                platform_fee = round(total_paid * Decimal('0.10'), 2)
                farmer_payout = total_paid - platform_fee

                order = Order.objects.create(
                    customer=customer,
                    post=post,
                    quantity_kg=qty,
                    total_paid=total_paid,
                    platform_fee=platform_fee,
                    farmer_payout=farmer_payout,
                    delivery_address=delivery_address,
                    status='pending'
                )
                orders.append(order)
                process_new_order(order)
            return orders


class OrderSerializer(serializers.ModelSerializer):
    customer_username = serializers.ReadOnlyField(source='customer.username')
    customer_name = serializers.ReadOnlyField(source='customer.name')
    customer_phone = serializers.ReadOnlyField(source='customer.phone_number')
    post_title = serializers.ReadOnlyField(source='post.title')
    post_farmer_name = serializers.ReadOnlyField(source='post.farmer.name')
    post_farmer_id = serializers.ReadOnlyField(source='post.farmer.id')
    post_farmer_phone = serializers.ReadOnlyField(source='post.farmer.phone_number')
    post_location = LocationInfoSerializer(source='post.location', read_only=True, allow_null=True)
    post_collection_point_address = serializers.ReadOnlyField(source='post.collection_point_address')

    class Meta:
        model = Order
        fields = '__all__'
        read_only_fields = ('customer', 'total_paid', 'platform_fee', 'farmer_payout', 'status', 'delivered_at',
                           'bkash_payment_id', 'bkash_trx_id', 'bkash_payment_status', 'paid_amount', 'paid_at')

    def validate(self, attrs):
        post = attrs.get('post')
        quantity_kg = attrs.get('quantity_kg')

        if quantity_kg <= 0:
            raise serializers.ValidationError({"quantity_kg": "Quantity must be greater than zero."})

        if post.total_weight_kg < quantity_kg:
            raise serializers.ValidationError(
                {"quantity_kg": f"Insufficient stock. Only {post.total_weight_kg}kg available."}
            )

        return attrs

    def create(self, validated_data):
        customer = self.context['request'].user
        post = validated_data['post']
        quantity_kg = validated_data['quantity_kg']

        with transaction.atomic():
            post = Post.objects.select_for_update().get(pk=post.pk)

            if post.total_weight_kg < quantity_kg:
                raise serializers.ValidationError(
                    {"quantity_kg": f"Insufficient stock. Only {post.total_weight_kg}kg available."}
                )

            total_paid = round(quantity_kg * post.price_per_kg, 2)

            post.total_weight_kg -= quantity_kg
            post.save()

            platform_fee = round(total_paid * Decimal('0.10'), 2)
            farmer_payout = total_paid - platform_fee

            order = Order.objects.create(
                customer=customer,
                post=post,
                quantity_kg=quantity_kg,
                total_paid=total_paid,
                platform_fee=platform_fee,
                farmer_payout=farmer_payout,
                delivery_address=validated_data['delivery_address'],
                status='pending'
            )
            process_new_order(order)
            return order


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

        has_completed_order = Order.objects.filter(
            customer=customer,
            post=post,
            status='completed'
        ).exists()

        if not has_completed_order:
            raise serializers.ValidationError(
                {"non_field_errors": "You can only review a product after completing a purchase for it."}
            )

        return attrs


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ('user', 'transaction_id', 'status', 'gateway_response')


class FarmerBankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = FarmerBankAccount
        fields = '__all__'
        read_only_fields = ('farmer',)


class BangladeshLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = BangladeshLocation
        fields = ('id', 'geo_id', 'name_en', 'name_bn', 'level', 'parent',
                  'latitude', 'longitude')


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
    post_title = serializers.ReadOnlyField(source='order.post.title')
    order_status = serializers.ReadOnlyField(source='order.status')
    collection_point_address = serializers.ReadOnlyField(source='order.post.collection_point_address', allow_null=True)

    class Meta:
        model = BatchItem
        fields = ('id', 'order', 'post_title', 'quantity_kg', 'farmer',
                  'farmer_name', 'farmer_phone', 'order_status',
                  'collection_point_address')


class BatchSerializer(serializers.ModelSerializer):
    area = AreaSerializer(read_only=True)
    union = LocationInfoSerializer(read_only=True)
    product_type_name_bn = serializers.ReadOnlyField(source='product_type.name_bn', allow_null=True)
    product_type_name_en = serializers.ReadOnlyField(source='product_type.name_en', allow_null=True)
    deliveryman_name = serializers.ReadOnlyField(source='deliveryman.name', allow_null=True)
    deliveryman_phone = serializers.ReadOnlyField(source='deliveryman.phone_number', allow_null=True)
    items = BatchItemSerializer(many=True, read_only=True)

    class Meta:
        model = Batch
        fields = '__all__'
        read_only_fields = ('status', 'deliveryman', 'total_quantity_kg',
                            'total_value', 'assigned_at', 'delivered_at')


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