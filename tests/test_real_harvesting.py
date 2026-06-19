# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Integration tests for harvesting real journal sources.

These tests perform actual HTTP requests to live OAI-PMH endpoints
and are skipped by default to avoid network dependencies and slow test runs.

To run these tests:
    SKIP_REAL_HARVESTING=0 python manage.py test tests.test_real_harvesting

To run a specific test:
    SKIP_REAL_HARVESTING=0 python manage.py test tests.test_real_harvesting.RealHarvestingTest.test_harvest_essd

Environment variables:
    SKIP_REAL_HARVESTING=0  - Enable real harvesting tests (default: skip)
"""

import os
from unittest import skipIf

import django
from django.test import TestCase

# bootstrap Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
django.setup()

from django.contrib.auth import get_user_model

from works.models import HarvestingEvent, Source, Work
from works.tasks import harvest_crossref_prefix, harvest_oai_endpoint

User = get_user_model()

# Skip these tests by default unless SKIP_REAL_HARVESTING=0
SKIP_REAL_HARVESTING = os.environ.get("SKIP_REAL_HARVESTING", "1") == "1"
skip_reason = "Real harvesting tests disabled. Set SKIP_REAL_HARVESTING=0 to enable."


@skipIf(SKIP_REAL_HARVESTING, skip_reason)
class RealHarvestingTest(TestCase):
    """
    Integration tests for harvesting from real journal OAI-PMH endpoints.

    These tests verify that:
    1. The OAI-PMH endpoint is accessible
    2. Publications are successfully parsed and saved
    3. Metadata extraction works for real-world data
    4. The harvesting event completes successfully

    Each test limits harvesting to ~20 records to keep runtime reasonable.
    """

    def setUp(self):
        """Set up test user for harvesting events."""
        self.user = User.objects.create_user(
            username="harvesting_test_user", email="harvesting@test.optimap.science", password="test_password"
        )

    def tearDown(self):
        """Clean up created publications and sources."""
        Work.objects.filter(source__name__startswith="TEST: ").delete()
        Source.objects.filter(name__startswith="TEST: ").delete()

    def _create_source(self, name, url, collection_name=None):
        """Helper to create a test source. ``collection_name`` arg is kept for caller
        back-compat but is now stored as a real ``Collection`` FK."""
        from django.utils.text import slugify

        from works.models import Collection

        col_name = collection_name or name
        col, _ = Collection.objects.get_or_create(
            identifier=slugify(col_name)[:100] or "test-collection",
            defaults={"name": col_name, "is_published": True},
        )
        return Source.objects.create(
            name=f"TEST: {name}",
            url_field=url,
            collection=col,
            harvest_interval_minutes=60 * 24 * 7,  # Weekly
        )

    def _assert_successful_harvest(self, source, min_publications=1):
        """
        Assert that harvesting completed successfully with expected results.

        Args:
            source: Source model instance
            min_publications: Minimum number of publications expected
        """
        # Get the latest harvesting event
        event = HarvestingEvent.objects.filter(source=source).latest("started_at")

        # Check event completed successfully
        self.assertEqual(event.status, "completed", f"Harvesting event failed with status: {event.status}")
        self.assertIsNotNone(event.completed_at, "Harvesting event has no completion time")

        # Check publications were created
        pub_count = Work.objects.filter(job=event).count()
        self.assertGreaterEqual(
            pub_count, min_publications, f"Expected at least {min_publications} publications, got {pub_count}"
        )

        # Check that publications have required fields
        pubs = Work.objects.filter(job=event)
        for pub in pubs[:5]:  # Check first 5
            self.assertTrue(pub.title, f"Publication {pub.id} missing title")
            # DOI is optional but should be present for most journals
            # Geometry and temporal data are optional

        return pub_count

    def test_harvest_essd(self):
        """
        Test harvesting from Earth System Science Data (ESSD).

        Issue: https://github.com/GeoinformationSystems/optimap/issues/59
        Journal: https://essd.copernicus.org/
        """
        source = self._create_source(
            name="Earth System Science Data", url="https://oai-pmh.copernicus.org/oai.php", collection_name="ESSD"
        )

        # Harvest with limit of 20 records
        harvest_oai_endpoint(source.id, user=self.user, max_records=20)

        # Verify successful harvest
        pub_count = self._assert_successful_harvest(source, min_publications=10)
        print(f"\n✓ ESSD: Harvested {pub_count} publications")

    def test_harvest_agile_giss(self):
        """
        Test harvesting from AGILE-GISS conference series.

        Issue: https://github.com/GeoinformationSystems/optimap/issues/60
        Journal: https://www.agile-giscience-series.net/
        """
        source = self._create_source(
            name="AGILE-GISS", url="https://oai-pmh.copernicus.org/oai.php", collection_name="AGILE-GISS"
        )

        # Harvest with limit of 20 records
        harvest_oai_endpoint(source.id, user=self.user, max_records=20)

        # Verify successful harvest
        pub_count = self._assert_successful_harvest(source, min_publications=10)
        print(f"\n✓ AGILE-GISS: Harvested {pub_count} publications")

    def test_harvest_geo_leo(self):
        """
        Test harvesting from GEO-LEO e-docs repository.

        Issue: https://github.com/GeoinformationSystems/optimap/issues/13
        Repository: https://e-docs.geo-leo.de/
        """
        source = self._create_source(
            name="GEO-LEO e-docs", url="https://e-docs.geo-leo.de/server/oai/request", collection_name="GEO-LEO"
        )

        # Harvest with limit of 20 records
        harvest_oai_endpoint(source.id, user=self.user, max_records=20)

        # Verify successful harvest
        pub_count = self._assert_successful_harvest(source, min_publications=5)
        print(f"\n✓ GEO-LEO: Harvested {pub_count} publications")

    def test_harvest_eartharxiv_with_openalex_enrichment(self):
        """
        Test harvesting from EarthArXiv preprint repository, including a
        smoke check that OpenAlex enrichment runs.

        Issue: harvesting Janeway-based preprint servers (#18 follow-up).
        Repository: https://eartharxiv.org/

        Validates:
          - The OAI-PMH endpoint is reachable and returns parseable records.
          - Bibliographic metadata (title, authors) is populated.
          - OpenAlex enrichment runs and at least one work picks up
            ``topics`` (which OPTIMAP only ever derives from OpenAlex —
            original sources don't carry research-topic classifications).

        Kept short (5 records) so the live OpenAlex round-trips don't
        dominate the suite. If OpenAlex itself is unreachable this run, the
        topics assertion is soft-skipped — the test only fails if EarthArXiv
        OAI-PMH is broken or our enrichment plumbing regresses.
        """
        source = self._create_source(
            name="EarthArXiv",
            url="https://eartharxiv.org/api/oai/?verb=ListRecords&metadataPrefix=oai_dc",
            collection_name="EarthArXiv",
        )

        harvest_oai_endpoint(source.id, user=self.user, max_records=5)

        pub_count = self._assert_successful_harvest(source, min_publications=3)

        pubs = list(Work.objects.filter(job__source=source))

        # Bibliographic basics — these come from EarthArXiv directly and
        # don't depend on OpenAlex.
        self.assertTrue(any(p.authors for p in pubs), "Expected at least one EarthArXiv work to have authors")

        # OpenAlex enrichment was attempted on every work; we look for the
        # provenance marker that the matcher actually ran successfully.
        enriched = [
            p
            for p in pubs
            if isinstance(p.provenance, dict)
            and any("openalex" in str(v).lower() for v in (p.provenance.get("metadata_sources") or {}).values())
        ]
        if not enriched:
            self.skipTest(
                "OpenAlex did not return any matches during this run (possible rate-limit / network); rerun later"
            )

        # `topics` is OpenAlex-only — its presence on any work proves the
        # enrichment pipeline produced substantive output, not just a
        # provenance line.
        with_topics = [p for p in enriched if p.topics]
        self.assertTrue(
            with_topics,
            f"Of {len(enriched)} OpenAlex-enriched works, none have topics "
            f"populated — enrichment plumbing may have regressed",
        )
        # Sanity check on the topics array shape.
        sample_topics = with_topics[0].topics
        self.assertIsInstance(sample_topics, list)
        self.assertTrue(all(isinstance(t, str) and t.strip() for t in sample_topics))

        print(
            f"\n✓ EarthArXiv: harvested {pub_count} preprints, "
            f"{len(enriched)} with OpenAlex enrichment, "
            f"{len(with_topics)} with topics"
        )

    def test_harvest_essoar(self):
        """
        Test harvesting from ESS Open Archive (ESSOAr) via Crossref.

        Issue: https://github.com/GeoinformationSystems/optimap/issues/99
        Repository: https://essopenarchive.org/

        ESSOAr has no usable native API (Atypon/Cloudflare) and is harvested
        through Crossref. It spans two DOI eras (10.1002/essoar.* legacy and
        10.22541/essoar.* current) that share Wiley member 311 / posted-content
        with Authorea, so a raw ``crossref_filter`` (member+type) base query is
        narrowed by ``doi_contains="essoar"`` to keep only ESSOAr records.
        """
        source = self._create_essoar_source()

        harvest_crossref_prefix(source.id, user=self.user, max_records=10, fetch_abstract_from_publisher=False)

        pub_count = self._assert_successful_harvest(source, min_publications=5)
        # Every saved work must be an ESSOAr record, never an Authorea one.
        dois = list(Work.objects.filter(source=source).values_list("doi", flat=True))
        self.assertTrue(all("essoar" in (d or "").lower() for d in dois), f"Non-ESSOAr DOI leaked in: {dois}")
        print(f"\n✓ ESSOAr: Harvested {pub_count} preprints via Crossref")

    def _create_essoar_source(self):
        """Create the ESS Open Archive Crossref source used by the ESSOAr tests."""
        from django.utils.text import slugify

        from works.models import Collection

        col, _ = Collection.objects.get_or_create(
            identifier=slugify("ESS Open Archive")[:100],
            defaults={"name": "ESS Open Archive", "is_published": True},
        )
        return Source.objects.create(
            name="TEST: ESS Open Archive",
            url_field="https://api.crossref.org/works?filter=member:311,type:posted-content",
            source_type="crossref-prefix",
            collection=col,
            crossref_filter="member:311,type:posted-content",
            doi_contains="essoar",
            is_preprint=True,
            default_work_type="preprint",
            harvest_interval_minutes=60 * 24 * 7,
        )

    def test_essoar_record_has_openalex_and_openaire_ids(self):
        """A harvested ESSOAr record carries its external identifiers: DOI (from
        Crossref), OpenAlex (inline enrichment during harvest) and OpenAIRE (the
        post-harvest sweep). Verifies both enrichment sources are wired into the
        Crossref harvest path and surface on the work's external-identifier links.
        """
        from works.harvesting.openaire import enrich_event_from_openaire
        from works.seo import external_identifier_links

        source = self._create_essoar_source()
        # Harvest a larger batch so at least one record matches in both indexes.
        harvest_crossref_prefix(
            source.id,
            user=self.user,
            max_records=20,
            fetch_abstract_from_publisher=False,
            sort="indexed",
            order="desc",
        )
        works = list(Work.objects.filter(source=source))
        self.assertTrue(works, "No ESSOAr works harvested")

        # OpenAlex enrichment runs inline during the Crossref harvest.
        with_openalex = [w for w in works if w.openalex_id]
        self.assertTrue(
            with_openalex,
            "No harvested ESSOAr work received an OpenAlex id — inline OpenAlex enrichment may have regressed",
        )

        # OpenAIRE enrichment is an async post-harvest sweep; run it synchronously.
        event = HarvestingEvent.objects.filter(source=source).latest("started_at")
        enrich_event_from_openaire(event.id)
        for w in works:
            w.refresh_from_db()
        with_openaire = [w for w in works if w.openaire_url]
        if not with_openaire:
            self.skipTest("OpenAIRE returned no matches this run (possible rate-limit / network); rerun later")

        # A single record should carry DOI + OpenAlex + OpenAIRE identifiers.
        both = [w for w in works if w.doi and w.openalex_id and w.openaire_url]
        self.assertTrue(
            both,
            "No single ESSOAr record carried DOI + OpenAlex + OpenAIRE ids together",
        )
        sample = both[0]
        titles = {link["title"] for link in external_identifier_links(sample)}
        self.assertTrue(
            {"DOI", "OpenAlex", "OpenAIRE"}.issubset(titles),
            f"Expected DOI/OpenAlex/OpenAIRE in external links, got {titles} for {sample.doi}",
        )
        print(
            f"\n✓ ESSOAr external IDs: {len(with_openalex)} w/ OpenAlex, {len(with_openaire)} w/ OpenAIRE; "
            f"sample {sample.doi} → {sorted(titles)}"
        )

    def test_harvest_respects_max_records(self):
        """
        Test that max_records parameter properly limits harvesting.

        Uses ESSD as a test source known to have many records.
        """
        source = self._create_source(
            name="ESSD (limited)", url="https://oai-pmh.copernicus.org/oai.php", collection_name="ESSD"
        )

        # Harvest with very small limit
        max_records = 5
        harvest_oai_endpoint(source.id, user=self.user, max_records=max_records)

        # Verify we got exactly the requested number (or slightly more due to batching)
        event = HarvestingEvent.objects.filter(source=source).latest("started_at")
        pub_count = Work.objects.filter(job=event).count()

        self.assertLessEqual(
            pub_count,
            max_records + 10,  # Allow some tolerance for batch processing
            f"Harvested {pub_count} publications, expected around {max_records}",
        )
        print(f"\n✓ max_records: Harvested {pub_count} publications (limit was {max_records})")

    def test_harvest_with_metadata_extraction(self):
        """
        Test that spatial/temporal metadata is extracted when available.

        Uses GEO-LEO which should have some geospatial metadata.
        """
        source = self._create_source(
            name="GEO-LEO (metadata test)",
            url="https://e-docs.geo-leo.de/server/oai/request",
            collection_name="GEO-LEO",
        )

        harvest_oai_endpoint(source.id, user=self.user, max_records=20)

        event = HarvestingEvent.objects.filter(source=source).latest("started_at")
        pubs = Work.objects.filter(job=event)

        # Check if any publications have spatial metadata
        spatial_count = pubs.exclude(geometry__isnull=True).count()

        # Check if any publications have temporal metadata
        temporal_count = pubs.exclude(timeperiod_startdate=[]).count()

        print(
            f"\n✓ Metadata extraction: {spatial_count} with geometry, "
            f"{temporal_count} with temporal data out of {pubs.count()} total"
        )

        # We don't assert specific counts since metadata availability varies,
        # but we verify the harvesting completed successfully
        self.assertEqual(event.status, "completed")
