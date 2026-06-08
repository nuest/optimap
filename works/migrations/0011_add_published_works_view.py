# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

from django.db import migrations

_CREATE_VIEW = """
CREATE OR REPLACE VIEW works_published AS
    SELECT * FROM works_work WHERE status = 'p';
"""

_DROP_VIEW = "DROP VIEW IF EXISTS works_published;"


class Migration(migrations.Migration):

    dependencies = [
        ("works", "0010_remove_text_log_from_provenance"),
    ]

    operations = [
        migrations.RunSQL(_CREATE_VIEW, reverse_sql=_DROP_VIEW),
    ]
