# Generated migration to rename metadata fields

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('publications', '0003_add_openalex_authors'),
    ]

    operations = [
        # Rename openalex_authors to authors
        migrations.RenameField(
            model_name='publication',
            old_name='openalex_authors',
            new_name='authors',
        ),
        # Rename openalex_keywords to keywords
        migrations.RenameField(
            model_name='publication',
            old_name='openalex_keywords',
            new_name='keywords',
        ),
        # Rename openalex_topics to topics
        migrations.RenameField(
            model_name='publication',
            old_name='openalex_topics',
            new_name='topics',
        ),
    ]
