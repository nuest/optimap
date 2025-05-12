from django.core.management.base import BaseCommand
from publications.models import Journal
from pyalex import Sources
import requests

class Command(BaseCommand):
    help = "Sync journal metadata from OpenAlex"

    def add_arguments(self, parser):
        parser.add_argument(
            '--issn',
            type=str,
            help='If provided, sync only this ISSN-L'
        )

    def handle(self, *args, **options):
        client = Sources()
        qs = Journal.objects.all()
        if options.get('issn'):
            qs = qs.filter(issn_l=options['issn'])

        for journal in qs:
            if not journal.issn_l:
                self.stdout.write(self.style.WARNING(
                    f"Skipping '{journal.display_name}': no ISSN-L"))
                continue

            # Try PyAlex wrapper first
            try:
                src = client.get_single_source(journal.issn_l, id_type='issn')
                journal.display_name = src.get('display_name') or journal.display_name
                journal.publisher = src.get('publisher') or journal.publisher
                journal.openalex_id = src.get('id') or journal.openalex_id
                journal.issn_list = src.get('issn') or journal.issn_list
                journal.save()
                self.stdout.write(self.style.SUCCESS(
                    f"Synced {journal.issn_l} via PyAlex"))
                continue
            except Exception:
                pass

            # Fallback: direct HTTP request
            url = f"https://api.openalex.org/sources/issn:{journal.issn_l}"
            resp = requests.get(url, params={'mailto': 'you@domain.com'})
            if resp.status_code == 200:
                data = resp.json()
                journal.display_name = data.get('display_name') or journal.display_name
                journal.publisher = data.get('publisher') or journal.publisher
                journal.openalex_id = data.get('id') or journal.openalex_id
                journal.issn_list = data.get('issn') or journal.issn_list
                journal.save()
                self.stdout.write(self.style.SUCCESS(
                    f"Synced {journal.issn_l} via HTTP"))
            else:
                self.stdout.write(self.style.WARNING(
                    f"Failed to sync {journal.issn_l}: HTTP {resp.status_code}"
                ))
