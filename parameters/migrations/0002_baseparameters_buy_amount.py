# Generated by Django 5.2 on 2025-04-13 19:06

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('parameters', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='baseparameters',
            name='buy_amount',
            field=models.DecimalField(decimal_places=2, default=10.0, max_digits=10),
        ),
    ]
