import logging
import time
from django.core.management.base import BaseCommand
from publications.models import Journal
from pyalex import Sources
import requests

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Sync journal metadata and articles list from OpenAlex"

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
                logger.warning("Skipping '%s': no ISSN-L", journal.display_name)
                continue

            # 1. Fetch metadata (PyAlex first)
            fetched = False
            try:
                src = client.get_single_source(journal.issn_l, id_type='issn')
                journal.display_name = src.get('display_name') or journal.display_name
                journal.publisher    = src.get('publisher')   or journal.publisher
                journal.openalex_id  = src.get('id')          or journal.openalex_id
                journal.issn_list    = src.get('issn')        or journal.issn_list
                journal.save()
                logger.info("Metadata synced (PyAlex) for ISSN %s", journal.issn_l)
                fetched = True
            except Exception as e:
                logger.debug("PyAlex fetch failed for %s: %s", journal.issn_l, e)

            if not fetched:
                url = f"https://api.openalex.org/sources/issn:{journal.issn_l}"
                resp = requests.get(url, params={'mailto': 'you@domain.com'})
                if resp.status_code == 200:
                    data = resp.json()
                    journal.display_name = data.get('display_name') or journal.display_name
                    journal.publisher    = data.get('publisher')   or journal.publisher
                    journal.openalex_id  = data.get('id')          or journal.openalex_id
                    journal.issn_list    = data.get('issn')        or journal.issn_list
                    journal.save()
                    logger.info("Metadata synced (HTTP) for ISSN %s", journal.issn_l)
                else:
                    logger.error(
                        "Failed metadata sync for %s: HTTP %d – %s",
                        journal.issn_l, resp.status_code, resp.text
                    )
                    continue

            # Throttle to respect 10/sec limit
            time.sleep(0.2)

            # 2. Fetch works list
            try:
                source_id = journal.openalex_id.rstrip('/').rsplit('/', 1)[-1]
                resp_w = requests.get(
                    "https://api.openalex.org/works",
                    params={
                      'filter': f'host_venue.source_id:{source_id}',
                      'per-page': 100,
                      'mailto': 'you@domain.com'
                    }
                )
                if resp_w.status_code == 200:
                    works = resp_w.json().get('results', [])
                    journal.articles = [w['id'] for w in works if w.get('id')]
                    journal.save()
                    logger.info("Fetched %d works for %s", len(journal.articles), journal.issn_l)
                elif resp_w.status_code == 403:
                    logger.error("403 fetching works for %s: %s", journal.issn_l, resp_w.text)
                else:
                    logger.warning("HTTP %d on works fetch for %s: %s",
                                   resp_w.status_code, journal.issn_l, resp_w.text)
            except Exception as e:
                logger.exception("Error fetching works for %s: %s", journal.issn_l, e)
