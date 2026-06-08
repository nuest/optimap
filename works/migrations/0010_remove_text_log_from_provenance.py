# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Strip the legacy ``text_log`` key from Work.provenance.

``text_log`` was a one-time migration artefact from 0004_collections.py: when
Work.provenance was converted from a plain TextField to a JSONField, old
freeform strings were wrapped as ``{"text_log": "<old string>"}``.  All
harvesters since that migration write structured provenance directly, so the key
is redundant and can be removed.
"""

from django.db import migrations


def _remove_text_log(apps, schema_editor):
    Work = apps.get_model('works', 'Work')
    qs = Work.objects.filter(provenance__has_key='text_log')
    for work in qs.only('id', 'provenance').iterator(chunk_size=500):
        if isinstance(work.provenance, dict):
            work.provenance.pop('text_log', None)
            Work.objects.filter(pk=work.pk).update(provenance=work.provenance)


def _noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('works', '0009_lowercase_user_emails'),
    ]

    operations = [
        migrations.RunPython(_remove_text_log, _noop),
    ]
