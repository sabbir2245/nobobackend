import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.files import File

from api.models import Post, PostImage

# A fallback placeholder is a tiny 1x1 GIF (43 bytes when stored). Anything
# under 2000 bytes is junk; real photos are many KB.
FALLBACK_SIZE = 2000


def _real_path(stored_name):
    """Map 'fallback_<name>.gif' back to the original '<name>' in MEDIA_ROOT.

    Returns the absolute path of the real photo, or None if not found.
    """
    name = os.path.basename(stored_name)
    if not name.startswith('fallback_'):
        return None
    stripped = name[len('fallback_'):]
    if stripped.lower().endswith('.gif'):
        stripped = stripped[:-4]
    candidate = os.path.join(settings.MEDIA_ROOT, stripped)
    if os.path.isfile(candidate):
        return candidate
    # media files are stored under <MEDIA_ROOT>/<upload_to>/<name>
    candidate = os.path.join(settings.MEDIA_ROOT, os.path.dirname(stored_name), stripped)
    if os.path.isfile(candidate):
        return candidate
    return None


class Command(BaseCommand):
    help = (
        "Re-points Post.image / PostImage.image to the real photos in MEDIA_ROOT "
        "when they are currently the 1x1 GIF fallback created by seed_data.py."
    )

    def handle(self, *args, **options):
        if not os.path.isdir(settings.MEDIA_ROOT):
            self.stderr.write(f"MEDIA_ROOT does not exist: {settings.MEDIA_ROOT}")
            return

        fixed_posts = 0
        for post in Post.objects.all().iterator():
            if not post.image:
                continue
            if post.image.size > FALLBACK_SIZE:
                continue
            real = _real_path(post.image.name)
            if not real:
                self.stdout.write(f"  [post {post.id}] no real image for '{post.image.name}'")
                continue
            with open(real, 'rb') as fh:
                post.image.save(os.path.basename(real), File(fh), save=False)
            post.save(update_fields=['image'])
            fixed_posts += 1
            self.stdout.write(f"  [post {post.id}] -> {os.path.basename(real)}")

        fixed_imgs = 0
        for pi in PostImage.objects.all().iterator():
            if not pi.image:
                continue
            if pi.image.size > FALLBACK_SIZE:
                continue
            real = _real_path(pi.image.name)
            if not real:
                self.stdout.write(f"  [postimage {pi.id}] no real image for '{pi.image.name}'")
                continue
            with open(real, 'rb') as fh:
                pi.image.save(os.path.basename(real), File(fh), save=False)
            pi.save(update_fields=['image'])
            fixed_imgs += 1
            self.stdout.write(f"  [postimage {pi.id}] -> {os.path.basename(real)}")

        self.stdout.write(self.style.SUCCESS(
            f"Done. Fixed {fixed_posts} posts, {fixed_imgs} gallery images."))