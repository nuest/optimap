# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("works", "0004_collections"),
    ]

    operations = [
        migrations.AddField(
            model_name="harvestingevent",
            name="records_updated",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
