import json
import requests
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Payment


# =============================================================================
# UDDOKTAPAY — Bangladesh MFS aggregator (bKash/Nagad/Rocket)
# =============================================================================
# Docs: https://uddoktapay.readme.io
#
# Replaces the insecure manual TrxID escrow flow: UddoktaPay auto-verifies a
# customer's "Send Money" TrxID and dispatches a webhook on COMPLETED status.
#
# Endpoints used:
#   POST {base}/api/checkout-v2      -> initiate a charge, returns payment_url
#   POST {base}/api/verify-payment   -> manual fallback verification by invoice
#
# Auth: header `RT-UDDOKTAPAY-API-KEY: <api_key>`
# =============================================================================

print("[UDDOKTAPAY] Loading UddoktaPay payment module...")

UDDOKTAPAY_API_KEY = settings.UDDOKTAPAY_API_KEY
UDDOKTAPAY_BASE_URL = settings.UDDOKTAPAY_BASE_URL

print(f"[UDDOKTAPAY] Base URL: {UDDOKTAPAY_BASE_URL}")
print(f"[UDDOKTAPAY] API key configured: {bool(UDDOKTAPAY_API_KEY)}")


def _headers():
    return {
        "RT-UDDOKTAPAY-API-KEY": UDDOKTAPAY_API_KEY,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def uddoktapay_create_charge(*, full_name, email, amount, metadata,
                             redirect_url, cancel_url, webhook_url):
    """POST /api/checkout-v2 — initiate a UddoktaPay charge.

    Returns the response JSON, which includes `payment_url` on success.
    Raises Exception on gateway/HTTP failure.
    """
    url = f"{UDDOKTAPAY_BASE_URL}/api/checkout-v2"
    payload = {
        "full_name": full_name or "Guest",
        "email": email or "guest@example.com",
        "amount": f"{Decimal(str(amount)):.2f}",
        "metadata": metadata,
        "redirect_url": redirect_url,
        "cancel_url": cancel_url,
        "webhook_url": webhook_url,
    }
    print(f"[UDDOKTAPAY CREATE] url={url} payload={json.dumps(payload)}")
    resp = requests.post(url, json=payload, headers=_headers(), timeout=30)
    print(f"[UDDOKTAPAY CREATE] status={resp.status_code} body={resp.text[:500]}")
    try:
        data = resp.json()
    except json.JSONDecodeError:
        raise Exception(f"UddoktaPay returned non-JSON (status {resp.status_code}): {resp.text[:500]}")
    if not data.get("status") or not data.get("payment_url"):
        raise Exception(f"UddoktaPay create charge failed: {json.dumps(data)}")
    return data


def uddoktapay_verify(invoice_id):
    """POST /api/verify-payment — manual fallback verification by invoice_id."""
    url = f"{UDDOKTAPAY_BASE_URL}/api/verify-payment"
    payload = {"invoice_id": invoice_id}
    print(f"[UDDOKTAPAY VERIFY] url={url} invoice={invoice_id}")
    resp = requests.post(url, json=payload, headers=_headers(), timeout=30)
    print(f"[UDDOKTAPAY VERIFY] status={resp.status_code} body={resp.text[:500]}")
    try:
        return resp.json()
    except json.JSONDecodeError:
        raise Exception(f"UddoktaPay verify returned non-JSON (status {resp.status_code})")


def _finalize_uddoktapay_payment(payment, *, transaction_id, sender_number=None,
                                 gateway_response=None):
    """Mark a UddoktaPay payment successful and set the order's escrow stage.

    Runs idempotently: if the payment is already `success`, it's a no-op.
    Appends the farmer-payout settlement xlsx row (once) via the existing
    bKash-ledger helper in payments.py.
    """
    from .payments import _append_settlement_xlsx

    if payment.status == 'success':
        return payment

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status == 'success':
            return payment

        payment.status = 'success'
        payment.bkash_trx_id = transaction_id
        payment.sender_number = sender_number
        payment.paid_at = timezone.now()
        if gateway_response is not None:
            payment.gateway_response = gateway_response

        order = payment.order
        if order is not None:
            if payment.payment_type == 'advance':
                order.advance_paid = True
            else:
                order.final_paid = True
            order.paid_amount = payment.amount
            order.bkash_trx_id = transaction_id
            order.bkash_payment_status = 'success'
            order.paid_at = payment.paid_at
            order.save(update_fields=[
                'advance_paid', 'final_paid', 'paid_amount', 'bkash_trx_id',
                'bkash_payment_status', 'paid_at',
            ])
            if not payment.settlement_appended and _append_settlement_xlsx(payment):
                payment.settlement_appended = True

        payment.save()
    return payment