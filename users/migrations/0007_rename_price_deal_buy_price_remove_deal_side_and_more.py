# Generated by Django 5.2 on 2025-04-13 21:38

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_deal'),
    ]

    operations = [
        migrations.RenameField(
            model_name='deal',
            old_name='price',
            new_name='buy_price',
        ),
        migrations.RemoveField(
            model_name='deal',
            name='side',
        ),
        migrations.AddField(
            model_name='deal',
            name='sell_price',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=20, null=True),
        ),
    ]
