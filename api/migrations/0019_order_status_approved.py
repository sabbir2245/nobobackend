from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0018_bangladeshlocation_ward'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('completed', 'Completed'), ('cancelled', 'Cancelled')], default='pending', max_length=20),
        ),
    ]