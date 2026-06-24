# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for ESSOAr/Authorea per-version DOI deduplication.

ESS Open Archive mints one DOI per version of a preprint. These cover the
versionless-base normalization and the reconcile/sweep that collapse versions
onto the latest one (works/utils/doi.py + works/dedup.py).
"""

from django.contrib.gis.geos import GeometryCollection
from django.test import TestCase

from works import dedup
from works.models import Work
from works.utils.doi import normalize_versioned_doi


def _make_work(doi, *, status="h"):
    return Work.objects.create(
        title=f"Work {doi}",
        status=status,
        doi=doi,
        url=f"https://doi.org/{doi}",
        openalex_id=None,
        locations=[],
        openalex_ids={},
        geometry=GeometryCollection(),
    )


class NormalizeVersionedDoiTests(TestCase):
    def test_current_era_slash_version(self):
        self.assertEqual(
            normalize_versioned_doi("10.22541/essoar.176858434.43447149/v2"),
            ("10.22541/essoar.176858434.43447149", 2),
        )

    def test_legacy_era_dotted_version(self):
        self.assertEqual(
            normalize_versioned_doi("10.1002/essoar.10512157.3"),
            ("10.1002/essoar.10512157", 3),
        )

    def test_plain_doi_is_untouched(self):
        self.assertEqual(
            normalize_versioned_doi("10.5194/egusphere-2024-123"),
            ("10.5194/egusphere-2024-123", None),
        )

    def test_current_era_versionless_base_is_not_misparsed_as_legacy(self):
        # The two-dotted current-era base (essoar.<a>.<b>) must NOT be read as a
        # legacy version; the dotted regex is anchored to the 10.1002 prefix.
        doi = "10.22541/essoar.123.456"
        self.assertEqual(normalize_versioned_doi(doi), (doi, None))

    def test_non_essoar_versioned_doi_is_untouched(self):
        # General Authorea (au.*) is a different venue we never harvest.
        doi = "10.22541/au.165388691.10496458/v1"
        self.assertEqual(normalize_versioned_doi(doi), (doi, None))

    def test_none(self):
        self.assertEqual(normalize_versioned_doi(None), (None, None))


class ReconcileVersionsTests(TestCase):
    def test_collapses_to_latest_version(self):
        v1 = _make_work("10.22541/essoar.111.222/v1")
        v2 = _make_work("10.22541/essoar.111.222/v2")

        canonical = dedup.reconcile_versions(v1)

        self.assertEqual(canonical.id, v2.id)
        v1.refresh_from_db()
        v2.refresh_from_db()
        self.assertEqual(v2.status, "h")  # latest stays live
        self.assertEqual(v1.status, "r")  # older becomes a tombstone
        self.assertEqual(v1.provenance["redirect"]["canonical_work_id"], v2.id)

    def test_legacy_dotted_versions_collapse(self):
        v1 = _make_work("10.1002/essoar.10500507.1")
        v2 = _make_work("10.1002/essoar.10500507.2")

        dedup.reconcile_versions(v2)

        v1.refresh_from_db()
        v2.refresh_from_db()
        self.assertEqual(v1.status, "r")
        self.assertEqual(v2.status, "h")

    def test_similar_id_prefix_is_not_merged(self):
        # Legacy base 10500507 must not swallow the unrelated id 105005070.
        a = _make_work("10.1002/essoar.10500507.1")
        b = _make_work("10.1002/essoar.105005070.1")

        dedup.reconcile_versions(a)

        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.status, "h")
        self.assertEqual(b.status, "h")

    def test_plain_doi_is_a_noop(self):
        w = _make_work("10.5194/egusphere-2024-123")
        self.assertEqual(dedup.reconcile_versions(w).id, w.id)
        w.refresh_from_db()
        self.assertEqual(w.status, "h")


class VersionSweepTests(TestCase):
    def test_sweep_collapses_existing_versions(self):
        v1 = _make_work("10.22541/essoar.999.888/v1")
        v2 = _make_work("10.22541/essoar.999.888/v2")
        v3 = _make_work("10.22541/essoar.999.888/v3")
        _make_work("10.22541/essoar.777.666/v1")  # lone version — untouched

        stats = dedup.version_sweep()

        self.assertEqual(stats["groups_merged"], 1)
        self.assertEqual(stats["works_redirected"], 2)
        for older in (v1, v2):
            older.refresh_from_db()
            self.assertEqual(older.status, "r")
        v3.refresh_from_db()
        self.assertEqual(v3.status, "h")

    def test_dry_run_changes_nothing(self):
        v1 = _make_work("10.22541/essoar.1.2/v1")
        _make_work("10.22541/essoar.1.2/v2")

        stats = dedup.version_sweep(dry_run=True)

        self.assertEqual(stats["groups_merged"], 1)
        v1.refresh_from_db()
        self.assertEqual(v1.status, "h")
