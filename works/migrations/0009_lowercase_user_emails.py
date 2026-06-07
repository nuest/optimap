# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

from django.db import migrations
from django.db.models.functions import Lower


def lowercase_user_emails(apps, schema_editor):
    """Normalise all email-based CustomUser rows to lowercase.

    Real user accounts have an '@' in both email and username.  Special
    sentinel/system accounts ('deleted', 'django_admin_command') do not, so
    the contains-'@' filters leave them untouched.

    After this migration every new account is normalised at intake
    (works/views/auth.py::loginres), so exact lookups on these fields are
    safe and can use the B-tree index again.
    """
    CustomUser = apps.get_model("works", "CustomUser")
    CustomUser.objects.filter(email__contains="@").update(email=Lower("email"))
    CustomUser.objects.filter(username__contains="@").update(username=Lower("username"))

    # Normalise BlockedEmail rows so the iexact lookup there stays optional,
    # and existing block-list entries work against the lowercased incoming email.
    BlockedEmail = apps.get_model("works", "BlockedEmail")
    BlockedEmail.objects.all().update(email=Lower("email"))


def reverse_lowercase(apps, schema_editor):
    # Email case cannot be recovered — lowercasing is one-way.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("works", "0008_add_bok_concepts_and_ontology_kind"),
    ]

    operations = [
        migrations.RunPython(lowercase_user_emails, reverse_code=reverse_lowercase),
    ]
