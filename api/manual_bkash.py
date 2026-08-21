from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Order, ManualBkashPayment
from .services import add_order_to_pool


class ManualBkashSubmitView(APIView):
    """
    POST /api/payments/manual-bkash/submit/
    Body: { order_id, payment_type: 'advance'|'final', trx_id, sender_number, amount? }

    Customer submits a manual bKash Send Money payment for admin verification.
    Payment stays in 'pending' status until an admin approves it.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        order_id = request.data.get("order_id")
        payment_type = request.data.get("payment_type", "advance")
        trx_id = request.data.get("trx_id", "").strip()
        sender_number = request.data.get("sender_number", "").strip()

        if not order_id:
            return Response({"error": "order_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        if payment_type not in ("advance", "final"):
            return Response({"error": "payment_type must be 'advance' or 'final'."}, status=status.HTTP_400_BAD_REQUEST)
        if not trx_id:
            return Response({"error": "trx_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not sender_number:
            return Response({"error": "sender_number is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(pk=order_id)
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

        # Admin override for amount
        if request.data.get("amount") and (request.user.is_staff or request.user.role == 'admin'):
            try:
                amount = Decimal(str(request.data["amount"]))
            except (ValueError, InvalidOperation):
                return Response({"error": "Invalid amount."}, status=status.HTTP_400_BAD_REQUEST)

        if amount <= 0:
            return Response({"error": "Order has no payable amount for this stage."}, status=status.HTTP_400_BAD_REQUEST)

        # Check for duplicate trx_id submission (same user + same order + same type = reject)
        if ManualBkashPayment.objects.filter(
            trx_id=trx_id, order=order, payment_type=payment_type, status='pending'
        ).exists():
            return Response({"error": "This transaction ID already has a pending submission for this order."}, status=status.HTTP_400_BAD_REQUEST)

        submission = ManualBkashPayment.objects.create(
            user=request.user,
            order=order,
            sender_number=sender_number,
            amount=amount,
            trx_id=trx_id,
            payment_type=payment_type,
            status='pending',
        )

        return Response({
            "submission_id": submission.id,
            "order_id": order.id,
            "payment_type": payment_type,
            "amount": f"{amount:.2f}",
            "trx_id": trx_id,
            "sender_number": sender_number,
            "status": "pending",
            "message": "Payment submitted for admin verification. You will be notified once it is approved.",
        }, status=status.HTTP_201_CREATED)


class ManualBkashListView(APIView):
    """
    GET /api/payments/manual-bkash/list/
    Admin-only. List all manual bKash submissions.
    Query params: status=pending|approved|rejected
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if request.user.role != "admin" and not request.user.is_staff:
            return Response({"error": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        qs = ManualBkashPayment.objects.select_related('user', 'order', 'payment', 'approved_by')

        status_filter = request.query_params.get('status')
        if status_filter in ('pending', 'approved', 'rejected'):
            qs = qs.filter(status=status_filter)

        submissions = []
        for sub in qs[:100]:
            submissions.append({
                "id": sub.id,
                "user_id": sub.user_id,
                "user_username": sub.user.username,
                "sender_number": sub.sender_number,
                "amount": str(sub.amount),
                "trx_id": sub.trx_id,
                "payment_type": sub.payment_type,
                "status": sub.status,
                "order_id": sub.order_id,
                "payment_id": sub.payment_id,
                "admin_note": sub.admin_note,
                "approved_by": sub.approved_by_id,
                "approved_at": sub.approved_at,
                "created_at": sub.created_at,
            })

        return Response(submissions)


class ManualBkashApproveView(APIView):
    """
    POST /api/payments/manual-bkash/<id>/approve/
    Admin-only. Approve a pending manual bKash submission.
    Creates a Payment record, links to order, updates order payment flags.
    Body (optional): { note: "..." }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != "admin" and not request.user.is_staff:
            return Response({"error": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        try:
            sub = ManualBkashPayment.objects.select_for_update().get(pk=pk)
        except ManualBkashPayment.DoesNotExist:
            return Response({"error": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)

        if sub.status != 'pending':
            return Response({"error": f"This submission is already {sub.status}."}, status=status.HTTP_400_BAD_REQUEST)

        note = request.data.get("note", "")

        from .payments import _append_settlement_xlsx

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
                    paid_at=timezone.now(),
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
                sub.approved_at = timezone.now()
                sub.admin_note = note
                sub.save(update_fields=['status', 'payment', 'approved_by', 'approved_at', 'admin_note'])

        except Exception as e:
            return Response({"error": f"Approval failed: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            "id": sub.id,
            "status": "approved",
            "payment_id": payment.id,
            "order_id": sub.order_id,
            "message": "Payment approved and linked to order.",
        })


class ManualBkashRejectView(APIView):
    """
    POST /api/payments/manual-bkash/<id>/reject/
    Admin-only. Reject a pending manual bKash submission.
    Body (optional): { note: "..." }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if request.user.role != "admin" and not request.user.is_staff:
            return Response({"error": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

        try:
            sub = ManualBkashPayment.objects.get(pk=pk)
        except ManualBkashPayment.DoesNotExist:
            return Response({"error": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)

        if sub.status != 'pending':
            return Response({"error": f"This submission is already {sub.status}."}, status=status.HTTP_400_BAD_REQUEST)

        note = request.data.get("note", "")
        sub.status = 'rejected'
        sub.approved_by = request.user
        sub.approved_at = timezone.now()
        sub.admin_note = note
        sub.save(update_fields=['status', 'approved_by', 'approved_at', 'admin_note'])

        return Response({
            "id": sub.id,
            "status": "rejected",
            "message": "Submission rejected.",
        })


# Need to import Payment for the approve view
from .models import Payment
