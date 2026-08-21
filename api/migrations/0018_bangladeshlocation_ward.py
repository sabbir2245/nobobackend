from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0017_manualbkashpayment'),
    ]

    operations = [
        migrations.AlterField(
            model_name='bangladeshlocation',
            name='level',
            field=models.CharField(choices=[('division', 'Division'), ('district', 'District'), ('upazila', 'Upazila'), ('union', 'Union'), ('ward', 'Ward / City Corporation Area')], max_length=20),
        ),
        migrations.AddField(
            model_name='bangladeshlocation',
            name='city_corp',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='bangladeshlocation',
            name='ward_no',
            field=models.CharField(blank=True, default='', max_length=10),
        ),
    ]