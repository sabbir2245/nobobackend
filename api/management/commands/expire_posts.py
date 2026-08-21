from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import Post


class Command(BaseCommand):
    """Flip `is_visible=False` on posts whose availability window has elapsed.

    A post expires when `created_at + time_availability` hours has passed.
    Posts with `time_availability=0` (no window) never expire. Hidden posts are
    excluded from public listings but kept in the DB so historical orders,
    payments, batches and reviews stay intact.

    Safe to run repeatedly; idempotent. Intended to be scheduled (cron) or run
    as part of a deploy.
    """

    help = "Hide posts whose availability window (time_availability) has elapsed."

    def handle(self, *args, **options):
        now = timezone.now()
        expired = []
        for post in Post.objects.filter(is_visible=True):
            exp = post.expires_at
            if exp is not None and now > exp:
                post.is_visible = False
                post.save(update_fields=['is_visible'])
                expired.append(post.id)

        self.stdout.write(
            self.style.SUCCESS(f"Expired {len(expired)} post(s): {expired}")
        )