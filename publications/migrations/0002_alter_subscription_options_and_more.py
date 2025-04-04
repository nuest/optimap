# Generated by Django 5.1.7 on 2025-04-04 23:58

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("publications", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="subscription",
            options={"ordering": ["name"], "verbose_name": "subscription"},
        ),
        migrations.RenameField(
            model_name="subscription",
            old_name="search_area",
            new_name="region",
        ),
        migrations.RemoveField(
            model_name="subscription",
            name="user_name",
        ),
        migrations.AddField(
            model_name="subscription",
            name="subscribed",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="subscription",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="subscriptions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="subscription",
            name="name",
            field=models.CharField(default="default_subscription", max_length=4096),
        ),
    ]
