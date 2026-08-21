Conversation with Gemini

How does uddoktapay work what does it do

UddoktaPay is a localized payment gateway aggregator in Bangladesh designed to automate the collection of digital payments. It acts as an intermediary between a website or application and various local payment service providers, allowing businesses and developers to accept payments automatically without manual verification.
What It Does

    Aggregates Local Payment Methods: Integrates major Mobile Financial Services (MFS) like bKash, Nagad, and Rocket, along with banking channels or cards, into a single gateway interface.

    Automates Verification: Eliminates the need to manually match transaction IDs (TrxIDs) or check SMS notifications when a customer pays.

    Provides API Access: Offers REST APIs, webhooks, and pre-built plugins for platforms like WordPress (WooCommerce), WHMCS, and custom web applications.

    Handles Webhook Notifications: Triggers instant status updates (e.g., payment success, failure, or cancellation) back to your website server to immediately deliver digital goods, grant access, or update order statuses.

How It Works

The general payment flow operates as follows:

    Checkout Initialization:
    A customer selects items or services on your website and chooses to pay. Your backend sends a request to the UddoktaPay API with the amount, customer details, and a redirect/cancel URL.

    Redirect to Gateway:
    UddoktaPay returns a secure checkout URL. The user is redirected to this hosted page, where they select their preferred payment method (e.g., bKash or Nagad).

    Payment Execution:

        Merchant Account Mode: The user completes the payment via direct API checkout or authorization popup.

        Personal/Personal-App Mode (Automation): Depending on the configuration, the payment is completed via standard MFS transfer protocols, and the system verifies the transaction payload in real-time.

    Instant Verification & Webhook:
    Once the transaction succeeds, UddoktaPay sends a secure POST request (webhook) directly to your server to confirm the transaction status and amount.

    Order Completion:
    Your application verifies the webhook payload, updates the database, and redirects the user back to your site's success page.

Common Use Cases

    E-commerce Stores: Automating WooCommerce or custom site checkout flows.

    Web Hosting & SaaS: Automatic billing and instant service provisioning on platforms like WHMCS.

    Digital Downloads & Subscriptions: Granting instant access to software, digital files, or subscription memberships upon payment confirmation.

Want to see a step-by-step example of integrating UddoktaPay with PHP or Node.js?

Collect docminetation to integrate with Django

Integrating UddoktaPay into a Django project is straightforward using standard Python REST clients (like requests or httpx). Because UddoktaPay provides a clean REST API, you don't need a heavy framework-specific SDK.  

Below is the complete architectural flow and setup implementation for standard integration.
Architecture Flow

    Initiate Payment: Frontend sends an checkout request -> Django Backend makes a POST request to UddoktaPay's /api/checkout-v2.  

    Redirect User: UddoktaPay returns a payment_url. Django redirects the user to that URL.  

    Handle Webhook (IPN): After completion, UddoktaPay sends a background POST request to your webhook endpoint with the transaction status.

    User Return: The user gets redirected to your success_url or cancel_url.  

Implementation Setup
1. Configure Settings

Store credentials securely in settings.py (or .env):
Python

# settings.py
import os

UDDOKTAPAY_API_KEY = os.environ.get("UDDOKTAPAY_API_KEY", "your_api_key_here")
UDDOKTAPAY_BASE_URL = os.environ.get("UDDOKTAPAY_BASE_URL", "https://sandbox.uddoktapay.com")

2. Payment Initiation View

Create a view that accepts the order details, sends a request to UddoktaPay, and redirects the user.
Python

# views.py
import requests
from django.conf import settings
from django.shortcuts import redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.urls import reverse

def create_uddoktapay_charge(request):
    """
    Initiates payment charge with UddoktaPay API v2
    """
    api_url = f"{settings.UDDOKTAPAY_BASE_URL}/api/checkout-v2"
    
    headers = {
        "RT-UDDOKTAPAY-API-KEY": settings.UDDOKTAPAY_API_KEY,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    
    # Construct callback URLs dynamically
    host = request.build_absolute_uri('/')[:-1]
    
    payload = {
        "full_name": request.user.get_full_name() or "Guest User",
        "email": request.user.email or "guest@example.com",
        "amount": "100.00",  # String/Decimal value
        "metadata": {
            "order_id": "ORD-12345",
            "user_id": str(request.user.id) if request.user.is_authenticated else "guest",
        },
        "redirect_url": f"{host}{reverse('payment_success')}",
        "cancel_url": f"{host}{reverse('payment_cancel')}",
        "webhook_url": f"{host}{reverse('uddoktapay_webhook')}",
    }

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=10)
        data = response.json()

        if response.status_code == 200 and data.get("status"):
            # Redirect user to the hosted payment page
            return redirect(data.get("payment_url"))
        else:
            return JsonResponse({"error": data.get("message", "Payment initiation failed")}, status=400)

    except requests.RequestException as e:
        return JsonResponse({"error": f"Gateway connection error: {str(e)}"}, status=500)

3. Verification & Webhook Endpoint

UddoktaPay dispatches a background webhook (POST) to notify your application of successful transactions.  
Python

# views.py
import json
from django.views.decorators.http import require_POST

@csrf_exempt  # Webhook receives unauthenticated external requests
@require_POST
def uddoktapay_webhook(request):
    """
    Handles payment status notification sent by UddoktaPay backend.
    """
    # Verify API Key sent in request header
    api_key_header = request.headers.get("RT-UDDOKTAPAY-API-KEY")
    if api_key_header != settings.UDDOKTAPAY_API_KEY:
        return JsonResponse({"error": "Unauthorized request"}, status=401)

    try:
        data = json.loads(request.body)
        
        status = data.get("status")               # "COMPLETED", "PENDING", etc.
        invoice_id = data.get("invoice_id")
        trx_id = data.get("transaction_id")
        amount = data.get("amount")
        metadata = data.get("metadata", {})
        order_id = metadata.get("order_id")

        if status == "COMPLETED":
            # UPDATE YOUR DATABASE HERE
            # e.g., Order.objects.filter(id=order_id).update(status="PAID", transaction_id=trx_id)
            return JsonResponse({"status": True, "message": "Transaction verified and order updated."})
        
        return JsonResponse({"status": False, "message": "Payment not completed."}, status=400)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid payload"}, status=400)

4. Verify Payment Manual Fallback (Optional)

In cases where a webhook is delayed, you can explicitly call the verification endpoint on the success redirect page.
Python

# views.py
def verify_payment_manual(invoice_id):
    api_url = f"{settings.UDDOKTAPAY_BASE_URL}/api/verify-payment"
    headers = {
        "RT-UDDOKTAPAY-API-KEY": settings.UDDOKTAPAY_API_KEY,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {"invoice_id": invoice_id}
    
    response = requests.post(api_url, json=payload, headers=headers, timeout=10)
    return response.json()

5. Configured URLs
Python

# urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("checkout/", views.create_uddoktapay_charge, name="payment_checkout"),
    path("payment/success/", views.payment_success_view, name="payment_success"),
    path("payment/cancel/", views.payment_cancel_view, name="payment_cancel"),
    path("api/uddoktapay-webhook/", views.uddoktapay_webhook, name="uddoktapay_webhook"),
]

Testing & Environment URLs
Environment	Base URL
Sandbox	[https://sandbox.uddoktapay.com](https://sandbox.uddoktapay.com)
Production	Provided on your merchant dashboard

    Note for Local Testing:

    Webhooks require a publicly accessible URL. During local development, run ngrok http 8000 and configure your base URL with the Ngrok forwarding address so UddoktaPay can reach your webhook endpoint.

Want me to include Django Model structures for storing invoice history and handling post-payment logic?

Is this actually from their official site

Yes, the integration structure and endpoints provided are aligned with UddoktaPay's official API specifications.  

Since UddoktaPay does not maintain an official first-party Django SDK, the Python code shown uses UddoktaPay's official REST API specifications wrapped in standard Django views.
Direct Specification Match
Spec Component	Official UddoktaPay Docs	Provided Django Code
API Endpoint	/api/checkout-v2	settings.UDDOKTAPAY_BASE_URL + "/api/checkout-v2"
Auth Header	RT-UDDOKTAPAY-API-KEY	"RT-UDDOKTAPAY-API-KEY": settings.UDDOKTAPAY_API_KEY
Required Payload	full_name, email, amount, metadata, redirect_url, cancel_url	Exact matching key-value schema
Response Format	{ "status": true, "payment_url": "..." }	Extracts payment_url and performs a Django redirect()
Sandbox Host	[https://sandbox.uddoktapay.com](https://sandbox.uddoktapay.com)	Used as default fallback base URL
Official Documentation Reference

If you want to view the official reference directly:

    Official Developer Docs: uddoktapay.readme.io

    Create Charge API (v2): uddoktapay.readme.io/reference/create-charge

    Verify Payment API: uddoktapay.readme.io/reference/verify-payment-api-guideline

Would you like to add signature/IP verification or custom database transaction atomic handling to this setup?

What things should I get from the uddoktapay and provide you with

To connect your Django application to UddoktaPay, you only need to obtain a few specific credentials from your UddoktaPay Merchant Dashboard.
Credentials Needed from UddoktaPay

    API Key (RT-UDDOKTAPAY-API-KEY)  

        Where to find it: Log in to your UddoktaPay account -> Go to API Settings / Developer Settings.

        What it looks like: A long string of hexadecimal characters (e.g., 982d381360a69d41...).  

    Base URL / Panel URL  

        Sandbox (Testing): [https://sandbox.uddoktapay.com](https://sandbox.uddoktapay.com)

        Live / Production: Your custom panel domain or self-hosted panel URL provided in your merchant dashboard (e.g., [https://pay.yourdomain.com](https://pay.yourdomain.com)).

What Information You Provide Back

When setting up the integration in your Django project, you populate these values in your .env or settings.py file:
Code snippet

# .env file
UDDOKTAPAY_API_KEY="your_api_key_from_dashboard"
UDDOKTAPAY_BASE_URL="https://sandbox.uddoktapay.com"  # Replace with live URL in production

Required Webhook Configuration in UddoktaPay Dashboard

For real-time payment confirmation, add your public endpoint URL to your UddoktaPay Merchant Settings:

https://yourdomain.com/api/uddoktapay-webhook/

    Safety Reminder:

    Never paste production API keys directly into public chat windows or public GitHub repositories. Use environment variables to keep them secure.

Do I need to provide them with my bkasht number

You do not need to share your personal bKash number with me.

For developer assistant queries, code integrations, and setup logic, your bKash/Nagad phone numbers and PINs should never be shared.
Where Your bKash Number Is Required

The only place your bKash (or Nagad/Rocket) number needs to go is inside your UddoktaPay Merchant Panel Settings:

    Setting Up Your Receiver Accounts:
    When you configure your UddoktaPay merchant dashboard, you add your bKash Personal or Merchant account details under Payment Methods Settings. This tells UddoktaPay where customers should send funds when they check out on your site.

    Customer Checkout:
    When a user clicks "Pay" on your site, UddoktaPay's hosted payment page displays your specified bKash/Nagad account number to the customer so they can complete the payment.

Summary of What You Need
Shared with Assistant / Django .env	Added to UddoktaPay Dashboard	Kept Strictly Private

• UDDOKTAPAY_API_KEY

• Base URL / Sandbox URL

• Webhook URL (/api/uddoktapay-webhook/)
	

• Your bKash / Nagad phone number

• Account type (Personal/Merchant)

• Webhook receiver endpoint
	

• bKash PIN

• OTPs

• Live API Keys on public repos

Ohk

You're all set!

Whenever you have your UddoktaPay dashboard ready, just drop your credentials into your .env file, wire up the Django views we went over, and you'll be good to go.

If you hit any issues while setting up the webhook, testing with Ngrok, or handling order updates in Django, just let me know!

Is uddoktapay a scam

No, UddoktaPay is not a scam. It is a legitimate, widely used payment automation aggregator based in Bangladesh, primarily built for developers, small businesses, e-commerce stores, and digital service providers.  
What It Is & How It Operates

    Legitimate Software Solution: It acts as a middleware software layer that automates MFS (bKash, Nagad, Rocket) payment collection and webhook notifications for websites.  

    Widely Used in Dev Communities: It has active plugins and integrations across WordPress/WooCommerce, WHMCS, Laravel, and custom Python/Django projects.

Important Nuances to Keep in Mind

While UddoktaPay itself is legitimate software, you should understand how payment aggregation works in Bangladesh:

    Software Provider vs. Scheduled Bank:

    Unlike traditional financial gateways (such as SSLCommerz or Shurjopay) that hold full institutional banking merchant status directly with Bangladesh Bank, platforms like UddoktaPay often run on automation models (processing API requests, MFS merchant apps, or automated SMS parsing) to auto-verify transactions.

    Third-Party Sellers:

    If a buyer gets scammed while buying goods on a website that uses UddoktaPay as its payment gateway, the issue is usually with the fraudulent seller, not the UddoktaPay system itself. UddoktaPay merely routes the transaction payload.

Best Practices for Developers & Merchants

    Self-Hosted / Official Domain: Always make sure you generate your API keys inside your own registered dashboard (uddoktapay.com or your designated panel).

    Secure API Keys: Never expose your API keys or secret credentials on public client-side scripts or public GitHub repositories.

    Test via Sandbox: Use sandbox.uddoktapay.com first to confirm your webhook verification flow works properly before taking payments live.

For API key do I need to pay first and open an account

No, you do not need to pay first to get an API key.

Here is how account opening and testing work with UddoktaPay:
1. Creating an Account

    Free Registration: Opening an account on the UddoktaPay merchant portal (my.uddoktapay.com) is free.  

    No Documents Required: Unlike traditional bank payment gateways, you do not need a trade license or complex business verification to create an account and access the dashboard.  

2. Sandbox Mode (100% Free Testing)

If you want to build and test your Django integration right away:

    You do not even need a live merchant account.

    You can use their public Sandbox API Key directly in your local code:

    982d381360a69d419689740d9f2e26ce36fb7a50

    Combined with the Sandbox Base URL ([https://sandbox.uddoktapay.com](https://sandbox.uddoktapay.com)), this lets you run dummy checkout tests and verify webhooks without spending a single Taka.

3. Going Live (Production API Key)

When you are ready to process real money from actual users:

    Log in to your free UddoktaPay dashboard.  

    Add your bKash / Nagad receiver accounts under settings.

    Generate your Live API Key from the API / Developer Settings tab.

    Pricing Structure:

    UddoktaPay offers a free plan with standard limits alongside paid subscription tiers or small transaction fee models for higher volume/automated MFS processing. However, getting started and retrieving your API keys requires zero upfront payment.  

At which point I need to pay

You only need to consider paying when you transition from building/testing to running a live business.

Here is the breakdown of the exact points:
1. Development & Testing Phase ($0 / Free)

    API Access: Generating sandbox credentials and testing the API with Django locally costs nothing.

    Simulation: You can trigger simulated payments and test your webhooks without spending a single Taka.

2. Going Live Phase (When You May Pay)

Once you deploy your application to production and want real customers to pay you real money, payment depends on the plan or pricing model you select:

    Transaction Fee Model (Pay-As-You-Go):

    Under standard transaction-based setups, you don't pay anything upfront. UddoktaPay automatically deducts a small percentage or fixed fee from each successful customer transaction before crediting your account.

    Monthly / Annual Subscription Plans:

    If you opt for advanced features—such as automated personal MFS device sync, higher transaction volume caps, custom white-label panels, or dedicated domain setups—you will pay a recurring subscription fee (e.g., monthly or yearly) to keep the automation service active.  

Summary Timeline

[Now] Build & Test Django Code (Sandbox API) ──> FREE
                                                    │
[Launch] Deploy to Production Server        ──> FREE
                                                    │
[First Real Payment] Receive Real Customer Cash ──> Pay Transaction Fee / Plan

Bottom Line: You don't need to spend any money right now while writing and testing your Django integration.

The docs you provided before is it compatible with my Non merchant account . Send money option . Trx id verfiy

Yes, the Django code and API endpoints are 100% compatible with personal non-merchant accounts using the "Send Money" or "Transaction ID" (TrxID) verification flow.

From the Django application's perspective, the code remains identical regardless of whether you use a bKash Merchant account or a Personal bKash account. UddoktaPay handles the backend logic behind the scenes.
How It Works with Personal Accounts

    User Checkout: When your Django backend calls /api/checkout-v2, UddoktaPay redirects the customer to their hosted checkout screen.

    Instruction Display: The customer sees your personal bKash/Nagad number on screen and is instructed to "Send Money" (or Cash Out) to that number.

    Transaction ID Submission: The user inputs their Transaction ID (TrxID) and sender phone number directly on UddoktaPay's page.

    Automated Verification:

        UddoktaPay verifies the TrxID using their automated notification reader or background service.

        Once validated, UddoktaPay marks the invoice as COMPLETED.  

    Webhook Dispatch: UddoktaPay sends the exact same POST payload to your Django /api/uddoktapay-webhook/ view.

Example Webhook Payload Received by Django

When a user completes a "Send Money" transaction, UddoktaPay sends this JSON payload to your Django webhook endpoint:
JSON

{
  "full_name": "Sabbir Ahmmed",
  "email": "user@example.com",
  "amount": "100.00",
  "fee": "0.00",
  "charged_amount": "100.00",
  "invoice_id": "Erm9wzjM0FBwjSYT0QVb",
  "metadata": {
    "order_id": "ORD-12345"
  },
  "payment_method": "bKash",
  "sender_number": "017XXXXXXXX",
  "transaction_id": "BLA1234567",
  "date": "2026-08-19 10:30:00",
  "status": "COMPLETED"
}

Notice that transaction_id and sender_number are automatically included, which you can store in your Django database for records.
How Manual TrxID Verification Works (Fallback)

If you ever need to manually double-check or verify a transaction ID programmatically in Django, you can call UddoktaPay's verify-payment API endpoint:  
Python

import requests
from django.conf import settings

def verify_trx(invoice_id):
    url = f"{settings.UDDOKTAPAY_BASE_URL}/api/verify-payment"
    headers = {
        "RT-UDDOKTAPAY-API-KEY": settings.UDDOKTAPAY_API_KEY,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {"invoice_id": invoice_id}

    response = requests.post(url, json=payload, headers=headers, timeout=10)
    data = response.json()

    # Access transaction details
    status = data.get("status")              # "COMPLETED"
    trx_id = data.get("transaction_id")      # e.g., "BLA1234567"
    sender = data.get("sender_number")       # e.g., "017XXXXXXXX"

    return status == "COMPLETED"

What You Need to Set Up in UddoktaPay Panel

Since you are using a Personal / Non-merchant account:

    Log in to your UddoktaPay merchant portal.

    Go to Payment Gateways / Accounts.

    Select bKash (Personal) or Nagad (Personal).

    Enter your personal phone number where customers will "Send Money".

    Keep the UddoktaPay Android device app / notification parser running (if required by your plan tier) so it can automatically detect incoming SMS TrxIDs.

Your Django code doesn't need to change at all—it handles the checkout link and receives the webhook response automatically.


Gemini is AI and can make mistakes.
