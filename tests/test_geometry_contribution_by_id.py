# SPDX-FileCopyrightText: 2025 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for ID-based geometry contribution (publications without DOI)."""

import json

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import GeometryCollection, Point
from django.test import TestCase

from works.models import Source, Work

User = get_user_model()


class GeometryContributionByIdTests(TestCase):
    """Test ID-based geometry contribution API endpoint for publications without DOI."""

    def setUp(self):
        # Create source
        self.source = Source.objects.create(name="Test Source", is_oa=True, is_preprint=False)

        # Create users
        self.contributor = User.objects.create_user(
            username="contributor@example.com", email="contributor@example.com", password="testpass123"
        )

        self.admin_user = User.objects.create_user(
            username="admin@example.com",
            email="admin@example.com",
            password="adminpass123",
            is_staff=True,
            is_superuser=True,
        )

        # Create test publication WITHOUT DOI (harvested, no geometry)
        self.pub_without_doi = Work.objects.create(
            title="Publication Without DOI",
            status="h",  # Harvested
            doi=None,  # No DOI
            url="http://repository.example.org/id/12345",
            geometry=GeometryCollection(),
            source=self.source,
        )

        # Create test publication with contributed geometry but no DOI
        self.pub_contributed_no_doi = Work.objects.create(
            title="Contributed Publication Without DOI",
            status="c",  # Contributed
            doi=None,
            url="http://repository.example.org/id/67890",
            geometry=GeometryCollection(Point(13.405, 52.52)),
            source=self.source,
        )

        self.test_geometry = {
            "type": "GeometryCollection",
            "geometries": [{"type": "Point", "coordinates": [13.405, 52.52]}],
        }

    def test_contribute_geometry_by_id_success(self):
        """Test successful geometry contribution using publication ID."""
        self.client.login(username="contributor@example.com", password="testpass123")

        url = f"/work/{self.pub_without_doi.id}/contribute-geometry/"
        response = self.client.post(
            url, data=json.dumps({"geometry": self.test_geometry}), content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])

        # Verify database changes
        self.pub_without_doi.refresh_from_db()
        self.assertEqual(self.pub_without_doi.status, "c")  # Contributed
        self.assertFalse(self.pub_without_doi.geometry.empty)

        # Verify provenance event was appended (structured JSON since 0.13.0)
        events = self.pub_without_doi.provenance.get("events", [])
        self.assertTrue(
            any(
                ev.get("type") == "contribution" and ev.get("user_email") == "contributor@example.com" for ev in events
            ),
            f"contribution event not found in {events!r}",
        )

    def test_contribute_simplified_switzerland_geometry_is_salvaged(self):
        """Regression for the Switzerland NER bug: a GeometryCollection whose
        Polygon has a valid exterior ring plus degenerate 2-point interior
        rings (the collapsed enclaves) must be salvaged (200), not 500."""
        self.client.login(username="contributor@example.com", password="testpass123")

        switzerland = {
            "type": "GeometryCollection",
            "geometries": [
                {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [5.955902, 46.132356],
                            [6.640611, 46.454873],
                            [7.064056, 45.90093],
                            [8.442212, 46.463223],
                            [9.330488, 46.505529],
                            [9.566503, 47.491949],
                            [8.590188, 47.800386],
                            [7.00011, 47.49896],
                            [6.171661, 46.612518],
                            [5.955902, 46.132356],
                        ],
                        [[8.658608, 47.691339], [8.658608, 47.691339]],
                        [[8.958544, 45.964816], [8.958544, 45.964816]],
                    ],
                }
            ],
        }

        url = f"/work/{self.pub_without_doi.id}/contribute-geometry/"
        response = self.client.post(url, data=json.dumps({"geometry": switzerland}), content_type="application/json")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        # User is told the geometry was auto-corrected.
        self.assertIn("warning", data)

        self.pub_without_doi.refresh_from_db()
        self.assertFalse(self.pub_without_doi.geometry.empty)
        self.assertTrue(self.pub_without_doi.geometry.valid)

    def test_contribute_fully_invalid_geometry_returns_400_not_500(self):
        """A geometry with no salvageable part returns a clean 400, never 500."""
        self.client.login(username="contributor@example.com", password="testpass123")

        bad = {
            "type": "GeometryCollection",
            "geometries": [{"type": "Polygon", "coordinates": [[[1.0, 1.0], [1.0, 1.0]]]}],
        }
        url = f"/work/{self.pub_without_doi.id}/contribute-geometry/"
        response = self.client.post(url, data=json.dumps({"geometry": bad}), content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_contribute_geometry_by_id_requires_authentication(self):
        """Test that contribution by ID requires authentication."""
        url = f"/work/{self.pub_without_doi.id}/contribute-geometry/"
        response = self.client.post(
            url, data=json.dumps({"geometry": self.test_geometry}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 401)

    def test_publish_work_by_id_success(self):
        """Test successful publishing using publication ID."""
        self.client.login(username="admin@example.com", password="adminpass123")

        url = f"/work/{self.pub_contributed_no_doi.id}/publish/"
        response = self.client.post(url, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])

        # Verify database changes
        self.pub_contributed_no_doi.refresh_from_db()
        self.assertEqual(self.pub_contributed_no_doi.status, "p")  # Published

        # Verify provenance event was appended (structured JSON since 0.13.0)
        events = self.pub_contributed_no_doi.provenance.get("events", [])
        self.assertTrue(
            any(ev.get("type") == "publish" and ev.get("user_email") == "admin@example.com" for ev in events),
            f"publish event not found in {events!r}",
        )

    def test_work_landing_by_id_accessible(self):
        """Test that publication landing page is accessible by ID."""
        # Make publication published so it's accessible
        self.pub_without_doi.status = "p"
        self.pub_without_doi.save()

        url = f"/work/{self.pub_without_doi.id}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.pub_without_doi.title)
        # Check that ID URLs flag is set in JavaScript
        self.assertContains(response, "const useIdUrls = true")
        # Check that publication ID is available in JavaScript
        self.assertContains(response, f"const pubId = {self.pub_without_doi.id}")


class MixedDOIAndIDTests(TestCase):
    """Test that both DOI-based and ID-based URLs work correctly."""

    def setUp(self):
        self.source = Source.objects.create(name="Test Source", is_oa=True, is_preprint=False)

        self.user = User.objects.create_user(
            username="user@example.com", email="user@example.com", password="testpass123"
        )

        # Publication with DOI
        self.pub_with_doi = Work.objects.create(
            title="Publication With DOI",
            status="h",
            doi="10.5555/test123",
            geometry=GeometryCollection(),
            source=self.source,
        )

        # Publication without DOI
        self.pub_without_doi = Work.objects.create(
            title="Publication Without DOI",
            status="h",
            doi=None,
            url="http://example.org/123",
            geometry=GeometryCollection(),
            source=self.source,
        )

        self.test_geometry = {
            "type": "GeometryCollection",
            "geometries": [{"type": "Point", "coordinates": [13.405, 52.52]}],
        }

    def test_both_url_types_work(self):
        """Test that both DOI-based and ID-based contribution URLs work."""
        self.client.login(username="user@example.com", password="testpass123")

        # Test DOI-based URL
        doi_url = f"/work/{self.pub_with_doi.doi}/contribute-geometry/"
        response1 = self.client.post(
            doi_url, data=json.dumps({"geometry": self.test_geometry}), content_type="application/json"
        )
        self.assertEqual(response1.status_code, 200)

        # Test ID-based URL
        id_url = f"/work/{self.pub_without_doi.id}/contribute-geometry/"
        response2 = self.client.post(
            id_url, data=json.dumps({"geometry": self.test_geometry}), content_type="application/json"
        )
        self.assertEqual(response2.status_code, 200)

        # Verify both publications were updated
        self.pub_with_doi.refresh_from_db()
        self.pub_without_doi.refresh_from_db()
        self.assertEqual(self.pub_with_doi.status, "c")
        self.assertEqual(self.pub_without_doi.status, "c")
