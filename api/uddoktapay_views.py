import json
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Order, Payment
from .uddoktapay import (
    uddoktapay_create_charge,
    uddoktapay_verify,
    _finalize_uddoktapay_payment,
)


def _public_base(request):
    """Public base URL for building redirect/cancel/webhook URLs."""
    base = getattr(settings, 'UDDOKTAPAY_PUBLIC_BASE_URL', '') or ''
    if base:
        return base.rstrip('/')
    return request.build_absolute_uri('/').rstrip('/')


def _validate_payment_type(value):
    if value not in ('advance', 'final'):
        return None
    return value


class UddoktaPayCheckoutView(APIView):
    """
    POST /api/payments/uddoktapay/checkout/
    Body: { order_id, payment_type: 'advance'|'final' }

    Validates ownership + escrow stage, creates a Payment (status='initiated',
    gateway='uddoktapay'), initiates a UddoktaPay charge and returns the hosted
    payment_url for the customer to be redirected to.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        order_id = request.data.get('order_id')
        payment_type = _validate_payment_type(request.data.get('payment_type', 'final'))

        if not order_id:
            return Response({"error": "order_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        if payment_type is None:
            return Response({"error": "payment_type must be 'advance' or 'final'."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            order = Order.objects.select_related('customer', 'post__farmer').get(pk=order_id)
        except Order.DoesNotExist:
            return Response({"error": "Order not found."}, status=status.HTTP_404_NOT_FOUND)

        if order.customer != request.user and not (request.user.is_staff or request.user.role == 'admin'):
            return Response({"error": "You do not own this order."}, status=status.HTTP_403_FORBIDDEN)

        # Escrow stage validation
        if payment_type == 'advance':
            if order.advance_paid:
                return Response({"error": "Advance payment already completed for this order."}, status=status.HTTP_400_BAD_REQUEST)
            amount = order.advance_amount or Decimal('0.00')
        else:
            if not order.advance_paid:
                return Response({"error": "Advance payment must be completed before the final payment."}, status=status.HTTP_400_BAD_REQUEST)
            if order.final_paid:
                return Response({"error": "Final payment already completed for this order."}, status=status.HTTP_400_BAD_REQUEST)
            amount = order.final_amount or Decimal('0.00')

        if amount <= 0:
            return Response({"error": "Order has no payable amount for this stage."}, status=status.HTTP_400_BAD_REQUEST)

        base = _public_base(request)
        webhook_url = f"{base}/api/payments/uddoktapay/webhook/"

        try:
            result = uddoktapay_create_charge(
                full_name=request.user.name or request.user.username,
                email=request.user.email,
                amount=amount,
                metadata={
                    "order_id": str(order.id),
                    "payment_type": payment_type,
                    "user_id": str(request.user.id),
                },
                redirect_url=f"{base}/api/payments/uddoktapay/redirect/success/?order_id={order.id}&payment_type={payment_type}",
                cancel_url=f"{base}/api/payments/uddoktapay/redirect/cancel/?order_id={order.id}&payment_type={payment_type}",
                webhook_url=webhook_url,
            )
        except Exception as e:
            print(f"[UDDOKTAPAY CHECKOUT] Failed: {e}")
            return Response({"error": f"Failed to initiate UddoktaPay payment: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        payment = Payment.objects.create(
            user=request.user,
            order=order,
            amount=amount,
            payment_type=payment_type,
            transaction_id=f"UDOKTA-{order.id}-{payment_type}-{result.get('invoice_id', '')}",
            status="initiated",
            gateway="uddoktapay",
            uddokta_invoice_id=result.get("invoice_id"),
            gateway_response=result,
        )
        print(f"[UDDOKTAPAY CHECKOUT] Payment #{payment.id} initiated, invoice={result.get('invoice_id')}")

        return Response({
            "payment_id": payment.id,
            "order_id": order.id,
            "payment_type": payment_type,
            "amount": f"{amount:.2f}",
            "invoice_id": result.get("invoice_id"),
            "payment_url": result.get("payment_url"),
            "status": payment.status,
        }, status=status.HTTP_201_CREATED)


@method_decorator(csrf_exempt, name="dispatch")
class UddoktaPayWebhookView(APIView):
    """
    POST /api/payments/uddoktapay/webhook/
    Background notification sent by UddoktaPay after a transaction completes.

    Header `RT-UDDOKTAPAY-API-KEY` must match. On status == 'COMPLETED' the
    amount is cross-checked against the order's expected advance/final amount
    before the payment is finalized.
    """
    permission_classes = []

    def post(self, request):
        if request.headers.get("RT-UDDOKTAPAY-API-KEY") != settings.UDDOKTAPAY_API_KEY:
            return JsonResponse({"error": "Unauthorized request"}, status=401)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid payload"}, status=400)

        print(f"[UDDOKTAPAY WEBHOOK] {json.dumps(data)}")

        status_value = data.get("status")
        invoice_id = data.get("invoice_id")
        trx_id = data.get("transaction_id")
        sender = data.get("sender_number")
        metadata = data.get("metadata", {}) or {}

        if status_value != "COMPLETED":
            return JsonResponse({"status": False, "message": "Payment not completed."}, status=400)

        order_id = metadata.get("order_id")
        payment_type = metadata.get("payment_type", "final")
        if payment_type not in ('advance', 'final'):
            return JsonResponse({"status": False, "message": "Invalid payment_type in metadata."}, status=400)

        if not order_id:
            return JsonResponse({"status": False, "message": "order_id missing in metadata."}, status=400)

        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            return JsonResponse({"status": False, "message": "Order not found."}, status=404)

        # Find the initiated payment for this invoice (prefer the exact match).
        payment = Payment.objects.filter(
            uddokta_invoice_id=invoice_id, order=order,
        ).order_by('-id').first()

        if payment is None:
            # Fallback: match by order + type + status=initiated.
            payment = Payment.objects.filter(
                order=order, payment_type=payment_type, status='initiated',
            ).order_by('-id').first()

        if payment is None:
            return JsonResponse({"status": False, "message": "No matching initiated payment."}, status=404)

        # Cross-check the reported amount against the expected escrow stage.
        try:
            reported = Decimal(str(data.get("amount", "0")))
        except (TypeError, ValueError, InvalidOperation):
            reported = Decimal('0')
        expected = order.advance_amount if payment_type == 'advance' else order.final_amount
        if expected is not None and reported != expected:
            print(f"[UDDOKTAPAY WEBHOOK] Amount mismatch: got {reported}, expected {expected}")
            return JsonResponse({"status": False, "message": "Amount mismatch."}, status=400)

        _finalize_uddoktapay_payment(
            payment,
            transaction_id=trx_id or invoice_id,
            sender_number=sender,
            gateway_response=data,
        )
        return JsonResponse({"status": True, "message": "Transaction verified and order updated."})


class UddoktaPayVerifyView(APIView):
    """
    GET /api/payments/uddoktapay/verify/<invoice_id>/
    Manual fallback: polls UddoktaPay to confirm payment status when the
    webhook has not arrived yet.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, invoice_id):
        try:
            data = uddoktapay_verify(invoice_id)
        except Exception as e:
            print(f"[UDDOKTAPAY VERIFY VIEW] Failed: {e}")
            return Response({"error": f"Verification failed: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        if data.get("status") == "COMPLETED":
            # Locally finalize the matching initiated payment.
            payment = Payment.objects.filter(
                uddokta_invoice_id=invoice_id, status='initiated',
            ).order_by('-id').first()
            if payment is not None:
                _finalize_uddoktapay_payment(
                    payment,
                    transaction_id=data.get("transaction_id") or invoice_id,
                    sender_number=data.get("sender_number"),
                    gateway_response=data,
                )

        return Response(data)


@method_decorator(csrf_exempt, name="dispatch")
class UddoktaPayRedirectView(APIView):
    """Lightweight browser redirect targets for success/cancel."""
    permission_classes = []

    def get(self, request, outcome):
        order_id = request.query_params.get('order_id')
        payment_type = request.query_params.get('payment_type')
        if outcome == 'success':
            return HttpResponse(
                f"Payment {payment_type} for order {order_id} completed. You can close this page.",
                status=200,
            )
        return HttpResponse(
            f"Payment {payment_type} for order {order_id} was cancelled.",
            status=200,
        )


@require_POST
@csrf_exempt
def uddoktapay_webhook_func(request):
    """Standalone view alias kept for direct URL wiring if ever needed."""
    return UddoktaPayWebhookView.as_view()(request)