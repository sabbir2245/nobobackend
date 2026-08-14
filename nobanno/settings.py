from pathlib import Path
import os
from dotenv import load_dotenv


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from the .env file located at your project root
load_dotenv(os.path.join(BASE_DIR, '.env'))

# Quick-start development settings - unsuitable for production
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-r=e*)_!hg93m=x89d_=(k9*9c)uhy&5rxodfrm^#e^!c41_xj*')

DEBUG = os.environ.get('DJANGO_DEBUG', 'false').lower() == 'true'

ALLOWED_HOSTS = [
    'localhost', '127.0.0.1', 'testserver',
    'nobannoapp.online',
    '200.234.36.38',
] + [h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if h.strip()]

if DEBUG:
    # Dev convenience: accept any Host header so a phone/emulator can reach the
    # backend over a changing LAN IP (e.g. 192.168.0.196).
    ALLOWED_HOSTS.append('*')


# Application definition
INSTALLED_APPS = [
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party apps
    'rest_framework',
    'rest_framework.authtoken',
    'corsheaders',
    # Local apps
    'api',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'nobanno.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [str(BASE_DIR / 'nobanno' / 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'nobanno.wsgi.application'


# Database Configuration
import sys
TESTING = 'test' in sys.argv or 'test_password_reset_flow' in sys.argv[0]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ['DB_NAME'],
        'USER': os.environ.get('DB_USER', ''),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript)
STATIC_URL = 'static/'
STATIC_ROOT = os.environ.get('STATIC_ROOT', str(BASE_DIR / 'staticfiles'))

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom User Model configuration
AUTH_USER_MODEL = 'api.User'

AUTHENTICATION_BACKENDS = [
    'api.backends.EmailOrPhoneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Token auth lifetime (seconds). Default 7 days.
TOKEN_TTL_SECONDS = int(os.environ.get('TOKEN_TTL_SECONDS', str(7 * 24 * 3600)))

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'api.auth.ExpiringTokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '2000/hour',
        'user': '5000/hour',
        'auth': '10/min',
        'otp': '5/hour',
    },
}

# Rate limiting is disabled during tests to avoid accumulation in the shared cache.
if TESTING:
    REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'].update({
        'anon': '10000/min',
        'user': '10000/min',
        'auth': '10000/min',
        'otp': '10000/min',
    })

# CORS configuration for cross-origin mobile requests
CORS_ALLOW_ALL_ORIGINS = True

# ── BKASH PAYMENT GATEWAY ─────────────────────────────────────────────────
BKASH_SANDBOX = os.environ.get('BKASH_SANDBOX', 'true').lower() == 'true'
BKASH_USERNAME = os.environ.get('BKASH_USERNAME', 'sandboxTokenizedUser02')
BKASH_PASSWORD = os.environ.get('BKASH_PASSWORD', 'sandboxTokenizedUser02@12345')
BKASH_APP_KEY = os.environ.get('BKASH_APP_KEY', '4f6o0cjiki2rfm34kfdadl1eqq')
BKASH_APP_SECRET = os.environ.get('BKASH_APP_SECRET', '2is7hdktrekvrbljjh44ll3d9l1dtjo4pasmjvs5vl5qr3fug4b')
BKASH_CALLBACK_URL = os.environ.get(
    'BKASH_CALLBACK_URL',
    'http://localhost:8000/api/payments/bkash/callback/'
)

# ── SSLCOMMERZ PAYMENT GATEWAY (Deprecated — kept for reference) ──────────
SSLCOMMERZ_STORE_ID = os.environ.get('SSLCOMMERZ_STORE_ID', 'testbox')
SSLCOMMERZ_STORE_PASSWORD = os.environ.get('SSLCOMMERZ_STORE_PASSWORD', 'qwerty')
SSLCOMMERZ_IS_SANDBOX = os.environ.get('SSLCOMMERZ_IS_SANDBOX', 'true').lower() == 'true'
CLOUDFLARE_TUNNEL_URL = os.environ.get('CLOUDFLARE_TUNNEL_URL')

# Media configuration
MEDIA_URL = '/media/'
MEDIA_ROOT = os.environ.get('MEDIA_ROOT', str(BASE_DIR / 'timage'))

# Settlement xlsx ledger (appended when a customer payment is marked successful)
SETTLEMENT_XLSX_PATH = BASE_DIR / 'settlements' / 'admin_settlement.xlsx'

# ── Jazzmin Admin Theme ───────────────────────────────────────────────────

JAZZMIN_SETTINGS = {
    "site_title": "Nobanno Admin",
    "site_header": "Nobanno",
    "site_brand": "Nobanno",
    "welcome_sign": "Welcome to Nobanno Admin",
    "copyright": "Nobanno Agricultural Marketplace",
    "search_model": ["api.User", "api.Post", "api.Order"],
    "topmenu_links": [
        {"name": "Dashboard", "url": "admin:stats", "permissions": ["is_staff"]},
        {"name": "API Browser", "url": "/api/", "permissions": ["is_staff"], "new_window": True},
    ],
    "icons": {
        "api.User": "fas fa-users",
        "api.ProductType": "fas fa-tags",
        "api.Post": "fas fa-seedling",
        "api.PostImage": "fas fa-image",
        "api.Order": "fas fa-truck",
        "api.Review": "fas fa-star",
        "api.ReviewImage": "fas fa-image",
        "api.OTP": "fas fa-key",
        "api.Payment": "fas fa-credit-card",
        "api.FarmerBankAccount": "fas fa-university",
        "api.BangladeshLocation": "fas fa-map-marker-alt",
    },
    "order_with_respect_to": [
        "api.User",
        "api.ProductType",
        "api.Post",
        "api.Order",
        "api.Review",
        "api.OTP",
        "api.FarmerBankAccount",
        "api.BangladeshLocation",
    ],
    "show_sidebar": True,
    "navigation_expanded": True,
    "hide_apps": [],
    "hide_models": ["api.ReviewImage", "api.PostImage", "api.OTP"],
    "related_modal_active": True,
    "custom_css": None,
    "custom_js": None,
    "use_google_fonts_cdn": True,
    "show_ui_builder": False,
}

JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": "navbar-success",
    "accent": "accent-success",
    "navbar": "navbar-dark navbar-success",
    "no_navbar_border": False,
    "navbar_fixed": True,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": True,
    "sidebar": "sidebar-dark-success",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": True,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": False,
    "theme": "flatly",
    "default_theme_mode": "auto",
    "button_classes": {
        "primary": "btn-outline-primary",
        "secondary": "btn-outline-secondary",
        "info": "btn-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success",
    },
}

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True

EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', '')
EMAIL_FAIL_SILENTLY = False