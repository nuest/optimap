# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("works", "0012_alter_source_abbreviated_title_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="consented_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text=(
                    "Timestamp of the user's initial privacy-policy consent "
                    "(set when they click 'I consent' on first login). "
                    "Null for accounts created before this field was introduced."
                ),
            ),
        ),
    ]
