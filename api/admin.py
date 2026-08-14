from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db.models import Sum, Count
from django.shortcuts import render
from django.urls import path

from .models import User, Post, PostImage, Order, Review, ReviewImage, ProductType, OTP, Payment, FarmerBankAccount, BangladeshLocation, Area, PendingPool, Batch, BatchItem


class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'is_verified', 'is_active')
    list_filter = ('role', 'is_verified', 'is_active')
    search_fields = ('username', 'email', 'phone_number')
    fieldsets = UserAdmin.fieldsets + (
        ('Custom Fields', {'fields': ('role', 'name', 'phone_number', 'address',
                                       'location', 'is_verified',
                                       'average_rating', 'ratings_count', 'service_areas')}),
    )


@admin.register(ProductType)
class ProductTypeAdmin(admin.ModelAdmin):
    list_display = ('name_bn', 'name_en', 'max_price_limit', 'post_count')
    list_editable = ('max_price_limit',)
    search_fields = ('name_bn', 'name_en')

    def post_count(self, obj):
        return obj.posts.count()
    post_count.short_description = 'Posts'


class PostImageInline(admin.TabularInline):
    model = PostImage
    extra = 0
    max_num = 3


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('title', 'farmer', 'product_type', 'total_weight_kg', 'price_per_kg', 'created_at')
    list_filter = ('product_type', 'created_at')
    search_fields = ('title', 'farmer__username')
    inlines = [PostImageInline]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'post_title', 'quantity_kg', 'status', 'total_paid', 'bkash_payment_status', 'created_at')
    list_filter = ('status', 'bkash_payment_status', 'created_at')
    search_fields = ('customer__username', 'post__title')

    def post_title(self, obj):
        return obj.post.title
    post_title.short_description = 'Product'


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ('name', 'threshold_kg', 'upazila_count', 'is_active', 'updated_at')
    list_editable = ('threshold_kg', 'is_active')
    filter_horizontal = ('upazilas',)
    search_fields = ('name',)

    def upazila_count(self, obj):
        return obj.upazilas.count()
    upazila_count.short_description = 'Upazilas'


class BatchItemInline(admin.TabularInline):
    model = BatchItem
    extra = 0


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'union', 'product_type', 'area', 'status', 'total_quantity_kg',
                    'total_value', 'deliveryman', 'created_at')
    list_filter = ('status', 'product_type', 'created_at')
    search_fields = ('union__name_en',)
    inlines = [BatchItemInline]


@admin.register(PendingPool)
class PendingPoolAdmin(admin.ModelAdmin):
    list_display = ('area', 'union', 'product_type', 'pending_quantity_kg', 'updated_at')


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'post', 'rating', 'created_at')
    list_filter = ('rating',)


admin.site.register(ReviewImage)
admin.site.register(OTP)

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('transaction_id', 'user', 'order', 'amount', 'status', 'gateway', 'bkash_trx_id', 'paid_at', 'settlement_appended', 'created_at')
    list_filter = ('status', 'gateway', 'settlement_appended', 'created_at')
    search_fields = ('transaction_id', 'user__username', 'order__id')
    readonly_fields = ('transaction_id', 'user', 'order', 'amount', 'gateway_response', 'created_at', 'updated_at')
    actions = ['download_settlement_xlsx']
    change_list_template = "admin/api/payment/change_list.html"

    @admin.action(description="Download Settlement XLSX")
    def download_settlement_xlsx(self, request, queryset):
        from django.shortcuts import redirect
        return redirect('admin:settlement_xlsx')

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path(
                'settlement-xlsx/',
                self.admin_site.admin_view(self._settlement_xlsx_view),
                name='settlement_xlsx',
            ),
        ]
        return custom_urls + urls

    def _settlement_xlsx_view(self, request):
        from django.http import FileResponse
        from .payments import _rebuild_settlement_xlsx
        path = _rebuild_settlement_xlsx()
        resp = FileResponse(
            open(path, 'rb'),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = 'attachment; filename="admin_settlement.xlsx"'
        return resp


@admin.register(FarmerBankAccount)
class FarmerBankAccountAdmin(admin.ModelAdmin):
    list_display = ('farmer', 'bank_name', 'account_number', 'routing_number', 'account_type')
    list_filter = ('bank_name', 'account_type')
    search_fields = ('farmer__username', 'farmer__name', 'account_number')


@admin.register(BangladeshLocation)
class BangladeshLocationAdmin(admin.ModelAdmin):
    list_display = ('name_en', 'name_bn', 'level', 'parent')
    list_filter = ('level',)
    search_fields = ('name_en', 'name_bn')


admin.site.register(User, CustomUserAdmin)


# ── Stats view ─────────────────────────────────────────────────────

def admin_stats_view(request):
    total_gmv = Order.objects.exclude(status='cancelled').aggregate(s=Sum('total_paid'))['s'] or 0
    completed_gmv = Order.objects.filter(status='completed').aggregate(s=Sum('total_paid'))['s'] or 0
    platform_profit = Order.objects.filter(status='completed').aggregate(s=Sum('platform_fee'))['s'] or 0
    pending_profit = Order.objects.exclude(status__in=['completed', 'cancelled']).aggregate(s=Sum('platform_fee'))['s'] or 0

    farmer_count = User.objects.filter(role='farmer').count()
    customer_count = User.objects.filter(role='customer').count()

    type_stats = ProductType.objects.annotate(
        post_count=Count('posts'),
    ).values('name_bn', 'name_en', 'max_price_limit', 'post_count')

    context = {
        'title': 'Platform Statistics',
        'total_gmv': total_gmv,
        'completed_gmv': completed_gmv,
        'platform_profit': platform_profit,
        'pending_profit': pending_profit,
        'farmer_count': farmer_count,
        'customer_count': customer_count,
        'total_users': farmer_count + customer_count,
        'type_stats': type_stats,
        'order_counts': {
            'pending': Order.objects.filter(status='pending').count(),
            'completed': Order.objects.filter(status='completed').count(),
            'cancelled': Order.objects.filter(status='cancelled').count(),
        },
        'recent_orders': Order.objects.select_related('customer', 'post').order_by('-created_at')[:8],
        'recent_reviews': Review.objects.select_related('customer', 'post').order_by('-created_at')[:8],
    }
    return render(request, 'admin/stats.html', context)


# Add stats URL to the admin site
original_get_urls = admin.site.get_urls


def patched_get_urls():
    urls = [path('stats/', admin_stats_view, name='stats')]
    urls.extend(original_get_urls())
    return urls


admin.site.get_urls = patched_get_urls