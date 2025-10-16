# Generated migration to add openalex_authors field

from django.contrib.postgres.fields import ArrayField
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('publications', '0002_add_openalex_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='publication',
            name='openalex_authors',
            field=ArrayField(
                models.CharField(max_length=255),
                blank=True,
                null=True,
                help_text='Author names from OpenAlex'
            ),
        ),
    ]
