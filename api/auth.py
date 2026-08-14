from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


class ExpiringTokenAuthentication(TokenAuthentication):
    """DRF Token auth that rejects tokens older than `TOKEN_TTL_SECONDS`."""

    keyword = 'Token'
    model = None

    def authenticate_credentials(self, key):
        model = self.get_model()
        try:
            token = model.objects.select_related('user').get(key=key)
        except model.DoesNotExist:
            raise AuthenticationFailed('Invalid token.')

        if not token.user.is_active:
            raise AuthenticationFailed('User inactive or deleted.')

        ttl = getattr(settings, 'TOKEN_TTL_SECONDS', 7 * 24 * 3600)
        if token.created:
            age = (timezone.now() - token.created).total_seconds()
            if age > ttl:
                token.delete()
                raise AuthenticationFailed('Token has expired.')

        return token.user, token
