from django.db import migrations, models
from django.utils.text import slugify


def backfill_country_slugs(apps, schema_editor):
    Country = apps.get_model("works", "Country")
    for country in Country.objects.all().only("id", "name", "slug"):
        slug = slugify(country.name)
        if country.slug != slug:
            country.slug = slug
            country.save(update_fields=["slug"])


class Migration(migrations.Migration):
    dependencies = [
        ("works", "0029_country_continent"),
    ]

    operations = [
        migrations.AddField(
            model_name="country",
            name="slug",
            field=models.SlugField(
                blank=True,
                db_index=True,
                default="",
                help_text="URL slug for /at/<slug>/, derived from the name. Indexed so place_page can look it up without scanning every country.",
                max_length=100,
            ),
        ),
        migrations.RunPython(backfill_country_slugs, migrations.RunPython.noop),
    ]
