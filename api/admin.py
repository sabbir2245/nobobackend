from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.safestring import mark_safe
from django.db.models import Sum, Count
from django.db import transaction
from django.shortcuts import render
from django.urls import path

from .models import User, Post, PostImage, Order, Review, ReviewImage, ProductType, OTP, Payment, ManualBkashPayment, FarmerBankAccount, BangladeshLocation, Area, PendingPool, Batch, BatchItem, Bid, Notification, FarmerDue
from .services import add_order_to_pool


class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'is_verified', 'is_active')
    list_filter = ('role', 'is_verified', 'is_active')
    search_fields = ('username', 'email', 'phone_number')
    fieldsets = UserAdmin.fieldsets + (
        ('Custom Fields', {'fields': ('role', 'name', 'phone_number', 'address',
                                       'location', 'is_verified',
                                       'average_rating', 'ratings_count', 'service_areas',
                                       'bkash_number')}),
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
    list_display = ('thumbnail', 'title', 'farmer', 'product_type', 'total_weight_kg',
                    'price_per_kg', 'status', 'created_at')
    list_filter = ('product_type', 'created_at')
    search_fields = ('title', 'description', 'farmer__username', 'farmer__name',
                     'product_type__name_en', 'product_type__name_bn')
    list_per_page = 25
    readonly_fields = ('created_at', 'updated_at')
    inlines = [PostImageInline]
    actions = ['delete_selected_posts']

    @admin.display(description='Image', ordering='image')
    def thumbnail(self, obj):
        url = obj.image.url if obj.image else ''
        if not url:
            return '-'
        return mark_safe(f'<img src="{url}" style="height:48px;width:auto;border-radius:4px;">')

    @admin.display(description='Status')
    def status(self, obj):
        return 'Active' if obj.total_weight_kg and obj.total_weight_kg > 0 else 'Sold out'

    @admin.action(description='Delete selected posts')
    def delete_selected_posts(self, request, queryset):
        from django.contrib import messages
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f'Deleted {count} post(s).', messages.SUCCESS)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'item_summary', 'status', 'total_paid', 'bkash_payment_status', 'created_at')
    list_filter = ('status', 'bkash_payment_status', 'created_at')
    search_fields = ('customer__username', 'items__post__title')

    def item_summary(self, obj):
        items = list(obj.items.all()[:3])
        if not items:
            return '-'
        titles = ', '.join(f"{i.post.title} x{i.quantity_kg}" for i in items)
        if obj.items.count() > 3:
            titles += '...'
        return titles
    item_summary.short_description = 'Items'


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


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'post', 'amount', 'counter_amount', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('customer__username', 'post__title')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'notification_type', 'title', 'is_read', 'batch', 'order', 'created_at')
    list_filter = ('notification_type', 'is_read', 'created_at')
    search_fields = ('user__username', 'user__name', 'title', 'message')
    readonly_fields = ('created_at',)


admin.site.register(ReviewImage)
admin.site.register(OTP)

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('transaction_id', 'user', 'order', 'amount', 'status', 'gateway', 'bkash_trx_id', 'uddokta_invoice_id', 'paid_at', 'settlement_appended', 'settlement_paid', 'created_at')
    list_filter = ('status', 'gateway', 'settlement_appended', 'settlement_paid', 'created_at')
    search_fields = ('transaction_id', 'user__username', 'order__id', 'uddokta_invoice_id')
    # Checkbox to mark a payment's farmer payout as settled/paid, straight from the list view.
    list_editable = ('settlement_paid',)
    readonly_fields = ('transaction_id', 'user', 'order', 'amount', 'gateway_response', 'created_at', 'updated_at')
    actions = ['download_settlement_xlsx', 'mark_settled', 'mark_unsettled']
    change_list_template = "admin/api/payment/change_list.html"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('order').prefetch_related('order__items__farmer')

    def farmer(self, obj):
        if obj.order:
            farmers = set(i.farmer.name for i in obj.order.items.select_related('farmer').all() if i.farmer)
            return ', '.join(farmers) if farmers else '—'
        return '—'
    farmer.short_description = 'Farmer'

    def payout(self, obj):
        return f"{obj.order.farmer_payout:.2f}" if obj.order else '—'
    payout.short_description = 'Payout (90%)'

    @admin.action(description="Mark selected as SETTLED (farmer paid)")
    def mark_settled(self, request, queryset):
        from django.contrib import messages
        from django.utils import timezone
        updated = queryset.filter(status='success', order__isnull=False).update(
            settlement_paid=True, settlement_paid_at=timezone.now())
        self.message_user(request, f'Marked {updated} payment(s) as settled.', messages.SUCCESS)

    @admin.action(description="Mark selected as NOT settled")
    def mark_unsettled(self, request, queryset):
        from django.contrib import messages
        updated = queryset.update(settlement_paid=False, settlement_paid_at=None)
        self.message_user(request, f'Marked {updated} payment(s) as not settled.', messages.SUCCESS)

    def save_model(self, request, obj, form, change):
        from django.utils import timezone
        if obj.settlement_paid and not obj.settlement_paid_at:
            obj.settlement_paid_at = timezone.now()
        elif not obj.settlement_paid:
            obj.settlement_paid_at = None
        super().save_model(request, obj, form, change)

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


@admin.register(ManualBkashPayment)
class ManualBkashPaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'sender_number', 'amount', 'trx_id', 'payment_type',
                    'status', 'order', 'payment', 'approved_by', 'approved_at', 'created_at')
    list_filter = ('status', 'payment_type', 'created_at')
    search_fields = ('trx_id', 'sender_number', 'user__username', 'order__id')
    readonly_fields = ('user', 'order', 'payment', 'approved_by', 'approved_at',
                       'created_at', 'updated_at')
    actions = ['approve_selected', 'reject_selected']
    change_list_template = "admin/api/manualbkashpayment/change_list.html"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'order', 'payment', 'approved_by')

    @admin.action(description="Approve selected (create payment + link to order)")
    def approve_selected(self, request, queryset):
        from django.contrib import messages
        from django.utils import timezone
        from .payments import _append_settlement_xlsx

        approved_count = 0
        for sub in queryset.filter(status='pending'):
            try:
                with transaction.atomic():
                    # Create Payment record
                    payment = Payment.objects.create(
                        user=sub.user,
                        order=sub.order,
                        amount=sub.amount,
                        payment_type=sub.payment_type,
                        transaction_id=f"MANUAL-{sub.trx_id}-O{sub.order_id}",
                        status='success',
                        gateway='bkash',
                        bkash_trx_id=sub.trx_id,
                        sender_number=sub.sender_number,
                        paid_at=timezone.now(),
                        settlement_appended=False,
                    )

                    # Append settlement XLSX
                    if sub.order:
                        if _append_settlement_xlsx(payment):
                            payment.settlement_appended = True
                            payment.save(update_fields=['settlement_appended'])

                        # Update order payment flags
                        order = sub.order
                        if sub.payment_type == 'advance':
                            order.advance_paid = True
                            order.status = 'approved'
                        else:
                            order.final_paid = True
                            order.status = 'completed'
                        order.paid_amount = sub.amount
                        order.bkash_trx_id = sub.trx_id
                        order.bkash_payment_status = 'success'
                        order.paid_at = payment.paid_at
                        order.save(update_fields=[
                        'advance_paid', 'final_paid', 'status', 'paid_amount', 'bkash_trx_id',
                        'bkash_payment_status', 'paid_at',
                    ])
                    if order.status == 'approved':
                        add_order_to_pool(order)

                    # Mark submission as approved
                    sub.status = 'approved'
                    sub.payment = payment
                    sub.approved_by = request.user
                    sub.approved_at = timezone.now()
                    sub.save(update_fields=['status', 'payment', 'approved_by', 'approved_at'])
                    approved_count += 1
            except Exception as e:
                self.message_user(request, f'Error approving {sub.trx_id}: {e}', messages.ERROR)

        self.message_user(request, f'Approved {approved_count} manual bKash payment(s).', messages.SUCCESS)

    @admin.action(description="Reject selected submissions")
    def reject_selected(self, request, queryset):
        from django.contrib import messages
        from django.utils import timezone
        updated = queryset.filter(status='pending').update(
            status='rejected', approved_by=request.user, approved_at=timezone.now())
        self.message_user(request, f'Rejected {updated} manual bKash submission(s).', messages.SUCCESS)

    def save_model(self, request, obj, form, change):
        if change and obj.status == 'approved' and not obj.payment:
            # If admin manually sets status to approved via change form, run approval logic
            from django.utils import timezone as tz
            from .payments import _append_settlement_xlsx
            with transaction.atomic():
                payment = Payment.objects.create(
                    user=obj.user,
                    order=obj.order,
                    amount=obj.amount,
                    payment_type=obj.payment_type,
                    transaction_id=f"MANUAL-{obj.trx_id}-O{obj.order_id}",
                    status='success',
                    gateway='bkash',
                    bkash_trx_id=obj.trx_id,
                    sender_number=obj.sender_number,
                    paid_at=tz.now(),
                    settlement_appended=False,
                )
                if obj.order:
                    if _append_settlement_xlsx(payment):
                        payment.settlement_appended = True
                        payment.save(update_fields=['settlement_appended'])
                    order = obj.order
                    if obj.payment_type == 'advance':
                        order.advance_paid = True
                        order.status = 'approved'
                    else:
                        order.final_paid = True
                        order.status = 'completed'
                    order.paid_amount = obj.amount
                    order.bkash_trx_id = obj.trx_id
                    order.bkash_payment_status = 'success'
                    order.paid_at = payment.paid_at
                    order.save(update_fields=[
                        'advance_paid', 'final_paid', 'status', 'paid_amount', 'bkash_trx_id',
                        'bkash_payment_status', 'paid_at',
                    ])
                    if order.status == 'approved':
                        add_order_to_pool(order)
                obj.payment = payment
                obj.approved_by = request.user
                obj.approved_at = tz.now()
        super().save_model(request, obj, form, change)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:pk>/approve/',
                self.admin_site.admin_view(self._approve_single_view),
                name='manualbkash-approve',
            ),
        ]
        return custom_urls + urls

    def _approve_single_view(self, request, pk):
        from django.shortcuts import redirect, get_object_or_404
        from django.contrib import messages
        from django.utils import timezone as tz
        from .payments import _append_settlement_xlsx

        sub = get_object_or_404(ManualBkashPayment, pk=pk, status='pending')
        try:
            with transaction.atomic():
                payment = Payment.objects.create(
                    user=sub.user,
                    order=sub.order,
                    amount=sub.amount,
                    payment_type=sub.payment_type,
                    transaction_id=f"MANUAL-{sub.trx_id}-O{sub.order_id}",
                    status='success',
                    gateway='bkash',
                    bkash_trx_id=sub.trx_id,
                    sender_number=sub.sender_number,
                    paid_at=tz.now(),
                    settlement_appended=False,
                )
                if sub.order:
                    if _append_settlement_xlsx(payment):
                        payment.settlement_appended = True
                        payment.save(update_fields=['settlement_appended'])
                    order = sub.order
                    if sub.payment_type == 'advance':
                        order.advance_paid = True
                        order.status = 'approved'
                    else:
                        order.final_paid = True
                        order.status = 'completed'
                    order.paid_amount = sub.amount
                    order.bkash_trx_id = sub.trx_id
                    order.bkash_payment_status = 'success'
                    order.paid_at = payment.paid_at
                    order.save(update_fields=[
                        'advance_paid', 'final_paid', 'status', 'paid_amount', 'bkash_trx_id',
                        'bkash_payment_status', 'paid_at',
                    ])
                    if order.status == 'approved':
                        add_order_to_pool(order)
                sub.status = 'approved'
                sub.payment = payment
                sub.approved_by = request.user
                sub.approved_at = tz.now()
                sub.save(update_fields=['status', 'payment', 'approved_by', 'approved_at'])
            messages.success(request, f'Manual bKash payment {sub.trx_id} approved successfully.')
        except Exception as e:
            messages.error(request, f'Error approving: {e}')
        return redirect('admin:api_manualbkashpayment_changelist')


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
        'recent_orders': Order.objects.select_related('customer').prefetch_related('items__post').order_by('-created_at')[:8],
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


# ── Farmer Due View ─────────────────────────────────────────────────

def farmer_due_mark_view(request):
    from django.contrib import messages as msg
    from django.shortcuts import redirect
    from django.utils import timezone as tz

    if request.method == 'POST':
        farmer_id = request.POST.get('farmer_id')
        if farmer_id:
            updated = Payment.objects.filter(
                order__items__farmer_id=farmer_id,
                status='success',
                settlement_paid=False,
            ).update(settlement_paid=True, settlement_paid_at=tz.now())
            msg.success(request, f'Marked {updated} payment(s) as paid for farmer #{farmer_id}.')
    return redirect('admin:farmer-due')


def farmer_due_view(request):
    from django.db.models import Sum, Q
    from .models import OrderItem, Payment

    # Get all OrderItems for farmers with approved/completed orders
    # where payment exists and settlement not yet paid.
    unpaid_items = (
        OrderItem.objects.filter(
            order__status__in=['approved', 'completed'],
            order__payments__status='success',
            order__payments__settlement_paid=False,
        )
        .select_related('farmer', 'post', 'order')
        .order_by('farmer__name', 'farmer__username')
    )

    # Group by farmer
    farmer_map = {}
    for item in unpaid_items:
        fid = item.farmer_id
        if fid not in farmer_map:
            farmer_map[fid] = {
                'farmer': item.farmer,
                'items': [],
                'total_pending': 0,
            }
        farmer_map[fid]['items'].append(item)
        farmer_map[fid]['total_pending'] += float(item.subtotal)

    # Sort by total pending descending
    farmers = sorted(farmer_map.values(), key=lambda x: -x['total_pending'])
    total_pending = sum(f['total_pending'] for f in farmers)

    context = {
        'title': 'Farmer Dues',
        'farmers': farmers,
        'total_pending': total_pending,
    }
    return render(request, 'admin/farmer_due.html', context)


# Patch admin site URLs to include farmer-due
original_get_urls_2 = admin.site.get_urls


def patched_get_urls_with_farmer_due():
    urls = [
        path('farmer-due/', admin.site.admin_view(farmer_due_view), name='farmer-due'),
        path('farmer-due/mark/', admin.site.admin_view(farmer_due_mark_view), name='farmer-due-mark'),
    ]
    urls.extend(original_get_urls_2())
    return urls


admin.site.get_urls = patched_get_urls_with_farmer_due


# ── Farmer Due proxy in sidebar ──────────────────────────────────────

@admin.register(FarmerDue)
class FarmerDueAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from django.shortcuts import redirect
        return redirect('admin:farmer-due')