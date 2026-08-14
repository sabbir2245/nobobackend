import logging
import random
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from rest_framework import permissions, serializers, status
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

# Set up standard console logging
logger = logging.getLogger(__name__)

User = get_user_model()

# Ensure relative import matches your OTP location
try:
    from .models import OTP
    logger.info("DEBUG: Successfully imported OTP model.")
except ImportError as e:
    logger.error(f"DEBUG CRITICAL: Failed to import OTP model. Error: {e}")
    raise e


# ==========================================
# SERIALIZERS
# ==========================================

class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    method = serializers.ChoiceField(choices=['email', 'sms'], default='email')

    def validate_email(self, value):
        # Generic response on purpose: do NOT reveal whether an account exists.
        logger.info(f"DEBUG: Processing password-reset request for: '{value}'")
        return value


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        email = attrs.get('email')
        otp_code = attrs.get('otp')

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError({"otp": "Invalid OTP."})

        # Latest unused OTP for this user
        otp_record = OTP.objects.filter(user=user, is_used=False).order_by('-created_at').first()

        if not otp_record:
            raise serializers.ValidationError({"otp": "Invalid OTP."})

        if otp_record.is_locked():
            raise serializers.ValidationError(
                {"otp": "Too many attempts. Please request a new code."})

        if otp_record.is_expired():
            raise serializers.ValidationError({"otp": "OTP has expired. Please request a new one."})

        if not otp_record.check_code(otp_code):
            otp_record.failed_attempts += 1
            otp_record.save(update_fields=['failed_attempts'])
            raise serializers.ValidationError({"otp": "Invalid OTP."})

        attrs['user'] = user
        attrs['otp_record'] = otp_record
        return attrs


# ==========================================
# VIEWS
# ==========================================

class ForgotPasswordView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp'

    def post(self, request):
        logger.info(f"DEBUG: Received request payload at ForgotPasswordView: {request.data}")

        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"DEBUG: ForgotPasswordSerializer validation failed: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email']
        method = serializer.validated_data.get('method', 'email')

        user = User.objects.filter(email=email).first()
        otp_code = f"{random.randint(100000, 999999)}"

        if user is not None:
            try:
                otp_obj = OTP.objects.create(user=user, method=method)
                otp_obj.set_code(otp_code)
                otp_obj.save(update_fields=['otp'])
                logger.info(f"DEBUG: OTP record created for user ID: {user.id}")
            except Exception as e:
                logger.error(f"DEBUG CRITICAL: Database write failed while creating OTP record: {e}")
                return Response({"error": "Database error saving OTP record."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            if method == 'email':
                from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@nobanno.com')
                try:
                    send_mail(
                        subject='Your Password Reset OTP',
                        message=f'Your OTP for password reset is: {otp_code}\n\nThis OTP is valid for 5 minutes.',
                        from_email=from_email,
                        recipient_list=[email],
                        fail_silently=False,
                    )
                    logger.info(f"DEBUG: send_mail completed to: '{email}'")
                except Exception as e:
                    logger.error(f"DEBUG CRITICAL: send_mail raised an exception: {e}")
                    return Response({
                        "error": "Email transmission failed. Check server configuration.",
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            elif method == 'sms':
                logger.info("DEBUG: SMS method selected, but no SMS gateway is configured.")

        # Generic message regardless of whether the account exists.
        return Response({
            "message": "If an account exists with that address, an OTP has been sent.",
        }, status=status.HTTP_200_OK)


class ResetPasswordView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp'

    def post(self, request):
        logger.info(f"DEBUG: Received request payload at ResetPasswordView: {request.data}")
        
        serializer = ResetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"DEBUG: ResetPasswordSerializer validation failed: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.validated_data['user']
        otp_record = serializer.validated_data['otp_record']
        new_password = serializer.validated_data['new_password']

        try:
            logger.info(f"DEBUG: Updating password string for user ID: {user.id}")
            user.set_password(new_password)
            user.save()
            logger.info(f"DEBUG: Password encryption and model save successful for user ID: {user.id}")
            
            otp_record.is_used = True
            otp_record.save()
            logger.info(f"DEBUG: OTP record ID {otp_record.id} successfully updated to is_used=True.")
            
        except Exception as e:
            logger.error(f"DEBUG CRITICAL: Encountered an error modifying user or OTP persistence data: {e}")
            return Response({"error": "Data update failed.", "details": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Handle Auth tokens cleanup
        try:
            deleted_count, _ = Token.objects.filter(user=user).delete()
            logger.info(f"DEBUG: Revoked and dropped {deleted_count} active token sessions for user ID {user.id}")
        except Exception as e:
            logger.warning(f"DEBUG WARNING: Could not delete old auth tokens (might not be using rest_framework.authtoken). Error: {e}")

        return Response({
            "message": "Password has been reset successfully. Please login with your new password."
        }, status=status.HTTP_200_OK)