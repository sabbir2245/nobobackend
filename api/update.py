from rest_framework import serializers, generics, permissions
from rest_framework.exceptions import PermissionDenied
from django.db.models import Sum
from .models import User, Post, BangladeshLocation

# ==========================================
# 1. SERIALIZERS
# ==========================================

class UserUpdateSerializer(serializers.ModelSerializer):
    location = serializers.PrimaryKeyRelatedField(
        queryset=BangladeshLocation.objects.all(), required=False)

    class Meta:
        model = User
        fields = ['name', 'phone_number', 'address', 'email', 'location']

    def validate_email(self, value):
        user = self.context['request'].user
        if User.objects.filter(email=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError("Please use a new email/phone number (নতুন ইমেইল/ফোন নম্বর ব্যবহার করুন).")
        return value

    def validate_location(self, value):
        if value.level not in ('union', 'upazila'):
            raise serializers.ValidationError("location must be a Union or Upazila.")
        return value


class PostUpdateSerializer(serializers.ModelSerializer):
    location = serializers.PrimaryKeyRelatedField(
        queryset=BangladeshLocation.objects.all(), required=False)

    class Meta:
        model = Post
        fields = ['title', 'description', 'image', 'image_url', 'total_weight_kg',
                  'price_per_kg', 'location', 'collection_point_address']

    def validate_location(self, value):
        if value.level not in ('union', 'upazila'):
            raise serializers.ValidationError("location must be a Union or Upazila.")
        return value


# ==========================================
# 2. VIEWS
# ==========================================

class UserUpdateView(generics.RetrieveUpdateAPIView):
    """
    PUT/PATCH/GET endpoint for the logged-in user's own profile.
    """
    serializer_class = UserUpdateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class PostUpdateView(generics.RetrieveUpdateDestroyAPIView):
    """
    PUT/PATCH/GET/DELETE endpoint for a specific post.
    """
    queryset = Post.objects.all()
    serializer_class = PostUpdateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_update(self, serializer):
        # Security check: ensures only the post's farmer can modify it
        post = self.get_object()
        if post.farmer != self.request.user:
            raise PermissionDenied("You do not have permission to edit this post.")
        serializer.save()