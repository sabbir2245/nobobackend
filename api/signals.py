from django.db.models import Avg, Count
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Review


@receiver(post_save, sender=Review)
@receiver(post_delete, sender=Review)
def update_farmer_rating_stats(sender, instance, **kwargs):
    farmer = instance.post.farmer
    stats = Review.objects.filter(post__farmer=farmer).aggregate(
        avg=Avg('rating'),
        count=Count('id')
    )
    farmer.average_rating = round(stats['avg'], 2) if stats['avg'] else None
    farmer.ratings_count = stats['count'] or 0
    farmer.save(update_fields=['average_rating', 'ratings_count'])
