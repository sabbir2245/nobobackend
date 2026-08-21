from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0019_order_status_approved'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='bkash_number',
            field=models.CharField(blank=True, max_length=15, null=True),
        ),
    ]
