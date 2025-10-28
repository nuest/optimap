# publications/management/commands/update_openalex_journals.py

import logging
import requests
import hashlib
import json

from django.core.management.base import BaseCommand
from django.db.models import Q
from works.models import Source

logger = logging.getLogger(__name__)

ISSN_ENDPOINT   = "https://api.openalex.org/sources/issn:{issn}"
SEARCH_ENDPOINT = "https://api.openalex.org/sources"


def fetch_by_issn(issn: str) -> dict | None:
    try:
        resp = requests.get(ISSN_ENDPOINT.format(issn=issn), timeout=10)
        if resp.status_code == 302 and "Location" in resp.headers:
            resp = requests.get(resp.headers["Location"], timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException as e:
        logger.debug("ISSN lookup failed for %s: %s", issn, e)
    return None


def fetch_by_name(name: str) -> dict | None:
    try:
        resp = requests.get(
            SEARCH_ENDPOINT,
            params={"filter": f"display_name.search:{name}"},
            timeout=10
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return results[0] if results else None
    except requests.RequestException as e:
        logger.debug("Name lookup failed for %s: %s", name, e)
    return None


class Command(BaseCommand):
    help = "Update Source metadata from OpenAlex (ISSN-based or name lookup)."

    def handle(self, *args, **options):
        qs = Source.objects.filter(Q(issn_l__isnull=False) | Q(is_preprint=True))
        self.stdout.write(f"Found {qs.count()} source(s) to update.\n")

        for src in qs:
            try:
                key = src.issn_l or src.name
                self.stdout.write(f"[{key}] querying OpenAlex…")
                logger.info("Fetching source metadata for %s", key)

                data = fetch_by_issn(src.issn_l) if src.issn_l else fetch_by_name(src.name)
                if not data:
                    self.stdout.write(f"[{key}] nothing found\n")
                    continue

                remote_updated = data.get("updated_date")

                full_id = data.get("id", "")
                new_id = full_id.rsplit("/", 1)[-1] if full_id else None
                works_count = data.get("works_count")
                works_api_url = data.get("works_api_url")
                raw_host = data.get("host_organization")
                publisher = (
                    raw_host.get("display_name") if isinstance(raw_host, dict) else data.get("display_name")
                )

                metadata = {
                    "openalex_id": new_id,
                    "openalex_url": full_id,
                    "works_count": works_count,
                    "works_api_url": works_api_url,
                    "publisher_name": publisher,
                    "openalex_updated_date": remote_updated,
                }

                # compute hash of metadata dict
                metadata_str = json.dumps(metadata, sort_keys=True)
                new_hash = hashlib.md5(metadata_str.encode()).hexdigest()

                # compare to last_sync_hash
                if getattr(src, "last_sync_hash", None) == new_hash:
                    self.stdout.write(f"[{key}] up-to-date (hash match)\n")
                    continue

                updates = {}
                for field, val in metadata.items():
                    if val is not None and val != getattr(src, field, None):
                        updates[field] = val
                updates['last_sync_hash'] = new_hash

                if updates:
                    Source.objects.filter(pk=src.pk).update(**updates)
                    self.stdout.write(f"[{key}] updated {', '.join(updates)}\n")
                else:
                    self.stdout.write(f"[{key}] nothing changed\n")

            except Exception as e:
                logger.error("Error updating %s: %s", key, e, exc_info=True)
                self.stdout.write(f"[{key}] skipped due to error: {e}\n")

        self.stdout.write("Done updating OpenAlex metadata.")
