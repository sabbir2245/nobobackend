from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .forget import ForgotPasswordView, ResetPasswordView
from .views import (
    RegisterView, CustomLoginView, LogoutView, UserProfileView,
    UserManagementViewSet, PostViewSet, OrderViewSet,
    ReviewViewSet, FarmerWalletView, AdminAnalyticsView,
    ProductTypeViewSet,
    BangladeshLocationView, AssignServiceAreaView,
    AreaViewSet, BatchViewSet, DemoPayView,
)
from .update import UserUpdateView, PostUpdateView
from .payments import (
    BKashPaymentInitiateView, BKashPaymentCallbackView,
    BKashPaymentSuccessView, BKashPaymentFailView,
    BKashPaymentStatusView, BKashPaymentRefundView,
    BEFTNInvoiceView, SettlementDownloadView,
)

router = DefaultRouter()
router.register(r'users', UserManagementViewSet, basename='user-mgmt')
router.register(r'posts', PostViewSet, basename='posts')
router.register(r'orders', OrderViewSet, basename='orders')
router.register(r'reviews', ReviewViewSet, basename='reviews')
router.register(r'product-types', ProductTypeViewSet, basename='product-types')
router.register(r'areas', AreaViewSet, basename='areas')
router.register(r'batches', BatchViewSet, basename='batches')

urlpatterns = [
    # Router endpoints
    path('', include(router.urls)),

    # Custom auth endpoints
    path('auth/register/', RegisterView.as_view(), name='auth-register'),
    path('auth/login/', CustomLoginView.as_view(), name='auth-login'),
    path('auth/logout/', LogoutView.as_view(), name='auth-logout'),
    path('auth/profile/', UserProfileView.as_view(), name='auth-profile'),

    # Password reset endpoints
    path('auth/forgot-password/', ForgotPasswordView.as_view(), name='auth-forgot-password'),
    path('auth/reset-password/', ResetPasswordView.as_view(), name='auth-reset-password'),

    # Custom dashboards
    path('farmer/wallet/', FarmerWalletView.as_view(), name='farmer-wallet'),
    path('admin/analytics/', AdminAnalyticsView.as_view(), name='admin-analytics'),

    path('profile/update/', UserUpdateView.as_view(), name='profile-update'),
    path('posts/<int:pk>/update/', PostUpdateView.as_view(), name='post-update'),

    # ── BKASH PAYMENT ROUTES ────────────────────────────────────────────────
    # Leg 1: Customer → Admin via bKash Tokenized Checkout
    path('payments/bkash/initiate/', BKashPaymentInitiateView.as_view(), name='bkash-payment-initiate'),
    path('payments/bkash/callback/', BKashPaymentCallbackView.as_view(), name='bkash-payment-callback'),
    path('payments/bkash/success/', BKashPaymentSuccessView.as_view(), name='bkash-payment-success'),
    path('payments/bkash/fail/', BKashPaymentFailView.as_view(), name='bkash-payment-fail'),
    path('payments/bkash/status/<str:transaction_id>/', BKashPaymentStatusView.as_view(), name='bkash-payment-status'),
    path('payments/bkash/refund/', BKashPaymentRefundView.as_view(), name='bkash-payment-refund'),
    path('payments/demo/', DemoPayView.as_view(), name='demo-pay'),
    path('payments/settlement/download/', SettlementDownloadView.as_view(), name='settlement-download'),

    # ── BEFTN CSV INVOICE (Leg 2: Admin → Farmer bank settlement) ───────────
    path('payments/beftn/invoice/', BEFTNInvoiceView.as_view(), name='beftn-invoice'),

    # ── LOCATION HIERARCHY (cascading dropdowns for delivery system) ─────────
    path('locations/', BangladeshLocationView.as_view(), name='locations-list'),

    # ── DELIVERYMAN SERVICE AREAS ────────────────────────────────────────────
    path('deliveryman/service-areas/', AssignServiceAreaView.as_view(), name='deliveryman-service-areas'),

    # ── DEPRECATED SSLCOMMERZ ROUTES (kept for reference, not routed) ───────
    # SSLCommerz routes have been removed. bKash is the only payment method.
]