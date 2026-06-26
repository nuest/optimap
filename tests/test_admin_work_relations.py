# SPDX-FileCopyrightText: 2026 OPTIMETA and KOMET projects <https://projects.tib.eu/komet>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Work admin can edit the Work↔Country and Work↔GlobalRegion M2M relationships."""

from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import GeometryCollection, MultiPolygon, Point, Polygon
from django.test import RequestFactory, TestCase
from django.urls import reverse

from works.models import Country, GlobalRegion, Work


def _box(minx, miny, maxx, maxy):
    return MultiPolygon(Polygon(((minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny))))


class WorkAdminRelationsTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.org", password="x"
        )
        self.client.force_login(self.admin)
        self.de = Country.objects.create(name="Germany", iso_code="DE", geom=_box(5, 47, 10, 55))
        self.pl = Country.objects.create(name="Poland", iso_code="PL", geom=_box(10, 47, 20, 55))
        self.land = GlobalRegion.objects.create(
            name="Testland",
            region_type=GlobalRegion.CONTINENT,
            source_url="x",
            license="CC0",
            geom=_box(5, 47, 10, 55),
        )
        self.work = Work.objects.create(status="p", title="w", geometry=GeometryCollection(Point(-30, 0)))

    def test_change_form_renders_country_and_region_widgets(self):
        url = reverse("admin:works_work_change", args=[self.work.id])
        html = self.client.get(url).content.decode()
        # filter_horizontal renders a multi-select that its JS turns into the
        # dual-list "chosen" widget; the base <select multiple> is in the HTML.
        self.assertIn('id="id_countries"', html)
        self.assertIn('id="id_regions"', html)
        self.assertIn("SelectFilter", html)

    def test_admin_form_exposes_country_and_region_fields(self):
        # The fields are editable form fields (not just read-only display).
        work_admin = site._registry[Work]
        request = RequestFactory().get("/admin/works/work/")
        request.user = self.admin
        form_fields = work_admin.get_form(request, obj=self.work).base_fields
        self.assertIn("countries", form_fields)
        self.assertIn("regions", form_fields)
