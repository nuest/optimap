# Generated migration for WikidataExportLog model

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('publications', '0002_add_regions_to_subscription'),
    ]

    operations = [
        migrations.CreateModel(
            name='WikidataExportLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('publication', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='wikidata_exports', to='publications.publication')),
                ('export_date', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('action', models.CharField(max_length=20, choices=[('created', 'Created'), ('updated', 'Updated'), ('skipped', 'Skipped'), ('error', 'Error')], db_index=True)),
                ('wikidata_qid', models.CharField(max_length=50, blank=True, null=True, help_text='Wikidata Q-ID (e.g., Q12345)')),
                ('wikidata_url', models.URLField(max_length=512, blank=True, null=True, help_text='Full URL to Wikidata item')),
                ('exported_fields', models.JSONField(blank=True, null=True, help_text='List of fields that were exported')),
                ('error_message', models.TextField(blank=True, null=True)),
                ('export_summary', models.TextField(blank=True, null=True, help_text='Summary of what was exported')),
            ],
            options={
                'ordering': ['-export_date'],
                'verbose_name': 'Wikidata Export Log',
                'verbose_name_plural': 'Wikidata Export Logs',
            },
        ),
        migrations.AddIndex(
            model_name='wikidataexportlog',
            index=models.Index(fields=['wikidata_qid'], name='publications_wikidata_qid_idx'),
        ),
    ]
