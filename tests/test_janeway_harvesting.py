# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""End-to-end harvest of a Janeway journal exposing the janeway_geometadata
plugin (issues #18 + #15). Hits the local development server at
http://localhost:8000/dqj/ and is skipped automatically when that server is not
reachable, so this file is safe to keep in the regular test suite.
"""

import unittest

import requests
from django.test import TestCase

from works.models import Source, Work
from works.tasks import harvest_oai_endpoint

JANEWAY_OAI_URL = "http://localhost:8000/dqj/api/oai/"
SULAWESI_ARTICLE_URL = "http://localhost:8000/dqj/article/id/53/"


def _janeway_available() -> bool:
    try:
        resp = requests.get(JANEWAY_OAI_URL, timeout=10)
    except requests.RequestException:
        return False
    return resp.status_code == 200


@unittest.skipUnless(
    _janeway_available(),
    f"Janeway dev server not reachable at {JANEWAY_OAI_URL}; start the local server to run this test",
)
class TestJanewayLocal(TestCase):
    """Smoke test against the local DQJ Janeway instance.

    Verifies that:
      * the existing OAI-PMH harvester pulls oai_dc records from a Janeway
        endpoint (issue #18 — no code changes were needed beyond pointing a
        Source at the URL), and
      * the geo metadata signals emitted by the janeway_geometadata plugin are
        picked up by the upgraded extractor (issue #15).
    """

    def test_harvest_dqj_picks_up_sulawesi_geometry_and_temporal(self):
        Work.objects.all().delete()
        src = Source.objects.create(
            url_field=JANEWAY_OAI_URL,
            name="DQJ (local Janeway)",
            harvest_interval_minutes=1440,
        )

        harvest_oai_endpoint(src.id, max_records=10)

        works = Work.objects.all()
        self.assertGreater(works.count(), 0, "expected at least one Work harvested from DQJ")

        try:
            sulawesi = Work.objects.get(url=SULAWESI_ARTICLE_URL)
        except Work.DoesNotExist:
            self.skipTest(f"Article 53 not present in this DQJ deployment ({SULAWESI_ARTICLE_URL})")

        self.assertIsNotNone(sulawesi.geometry)
        self.assertFalse(sulawesi.geometry.empty, "Sulawesi article should have a non-empty geometry")
        west, south, east, north = sulawesi.geometry.extent
        self.assertGreaterEqual(west, 119.0 - 1)
        self.assertLessEqual(east, 125.0 + 1)
        self.assertGreaterEqual(south, -5.7 - 1)
        self.assertLessEqual(north, 1.7 + 1)

        # JSON-LD temporalCoverage is "../2024-12-31"
        self.assertEqual(sulawesi.timeperiod_startdate, [None])
        self.assertEqual(sulawesi.timeperiod_enddate, ["2024-12-31"])

        # Provenance should record which signal we used (structured JSON since 0.13.0).
        # JSON-LD wins on this article; if the publisher ever drops it, "DC.SpatialCoverage"
        # or "DC.box" would be acceptable too.
        metadata_sources = sulawesi.provenance.get("metadata_sources", {})
        geometry_label = metadata_sources.get("geometry")
        self.assertIsNotNone(geometry_label, f"no geometry source label in {sulawesi.provenance!r}")
        self.assertTrue(
            any(
                label in geometry_label
                for label in (
                    "schema.org JSON-LD",
                    "link rel=alternate geo+json",
                    "DC.SpatialCoverage",
                    "DC.box",
                )
            ),
            f"unexpected geometry provenance: {geometry_label!r}",
        )
