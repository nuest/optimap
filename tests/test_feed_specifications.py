"""
Test cases to validate RSS 2.0 and Atom 1.0 feeds against their specifications.

RSS 2.0 Specification: https://www.rssboard.org/rss-specification
Atom 1.0 Specification: https://www.ietf.org/rfc/rfc4287.txt
GeoRSS Specification: http://www.georss.org/georss
"""

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
import django
django.setup()

import xml.etree.ElementTree as ET
from datetime import datetime
from django.test import TestCase
from django.contrib.gis.geos import Point, LineString, Polygon, GeometryCollection
from publications.models import Publication, Source


class RSS20SpecificationTestCase(TestCase):
    """
    Test cases validating RSS 2.0 feed against the RSS 2.0 specification.

    Required channel elements:
    - title
    - link
    - description

    Optional channel elements tested:
    - language
    - pubDate
    - lastBuildDate
    - generator
    - docs

    Required item elements:
    - title or description (at least one)

    Optional item elements tested:
    - link
    - description
    - author / dc:creator
    - category
    - guid
    - pubDate
    - source
    """

    @classmethod
    def setUpTestData(cls):
        """Set up test data with various publication types."""
        Publication.objects.all().delete()

        # Create a test source
        cls.source = Source.objects.create(
            name="Test Journal",
            url_field="https://example.com/feed",
            abbreviated_title="Test J.",
            homepage_url="https://example.com",
            issn_l="1234-5678",
            publisher_name="Test Publisher",
            is_oa=True,
            is_preprint=False,
            cited_by_count=100,
            works_count=500,
        )

        # Publication with full metadata
        cls.pub_full = Publication.objects.create(
            title="Complete Publication Test",
            abstract="A complete publication with all metadata fields populated.",
            url="https://example.com/complete",
            status="p",
            publicationDate=datetime(2023, 6, 15),
            doi="10.1234/complete-test",
            source=cls.source,
            geometry=GeometryCollection(Point(13.0, 52.0)),
            openalex_id="https://openalex.org/W123456789",
            openalex_authors=["Alice Smith", "Bob Jones", "Carol Williams"],
            openalex_keywords=["test", "validation", "feeds"],
            openalex_topics=["Computer Science", "Data Science"],
        )

        # Publication without authors (should not have dc:creator)
        cls.pub_no_authors = Publication.objects.create(
            title="Publication Without Authors",
            abstract="A publication without author information.",
            url="https://example.com/no-authors",
            status="p",
            publicationDate=datetime(2023, 7, 20),
            doi="10.1234/no-authors",
            source=cls.source,
            geometry=GeometryCollection(Point(14.0, 53.0)),
        )

        # Publication with many authors (should use "et al.")
        cls.pub_many_authors = Publication.objects.create(
            title="Publication With Many Authors",
            abstract="A publication with more than 10 authors.",
            url="https://example.com/many-authors",
            status="p",
            publicationDate=datetime(2023, 8, 25),
            doi="10.1234/many-authors",
            geometry=GeometryCollection(Polygon([
                (10.0, 50.0), (11.0, 51.0), (12.0, 50.0), (10.0, 50.0)
            ])),
            openalex_authors=[
                f"Author{i}" for i in range(1, 15)
            ],  # 14 authors - should trigger "et al."
        )

        # Publication with GeoRSS line geometry
        cls.pub_line = Publication.objects.create(
            title="Publication With LineString",
            abstract="A publication with line geometry.",
            url="https://example.com/line",
            status="p",
            publicationDate=datetime(2023, 9, 10),
            doi="10.1234/line-test",
            geometry=GeometryCollection(LineString([
                (5.0, 45.0), (6.0, 46.0), (7.0, 45.5)
            ])),
        )

    def _fetch_rss_feed(self):
        """Fetch the global RSS feed."""
        response = self.client.get('/api/v1/feeds/optimap-global.rss')
        self.assertEqual(response.status_code, 200, "RSS feed should return 200")
        self.assertEqual(
            response['Content-Type'],
            'application/rss+xml; charset=utf-8',
            "RSS feed should have correct Content-Type"
        )
        return response.content.decode('utf-8')

    def _parse_rss(self, xml_content):
        """Parse RSS XML and return root element."""
        try:
            root = ET.fromstring(xml_content)
            return root
        except ET.ParseError as e:
            self.fail(f"RSS feed is not valid XML: {e}")

    def test_rss_valid_xml(self):
        """Test that RSS feed is valid XML."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)
        self.assertIsNotNone(root, "RSS feed should be valid XML")

    def test_rss_root_element(self):
        """Test RSS root element is <rss> with version 2.0."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        self.assertEqual(root.tag, 'rss', "Root element should be <rss>")
        self.assertEqual(
            root.get('version'),
            '2.0',
            "RSS version should be 2.0"
        )

    def test_rss_namespaces(self):
        """Test RSS feed declares required namespaces."""
        xml_content = self._fetch_rss_feed()

        # Check for required namespaces
        self.assertIn('xmlns:atom="http://www.w3.org/2005/Atom"', xml_content,
                     "RSS should declare Atom namespace")
        self.assertIn('xmlns:georss="http://www.georss.org/georss"', xml_content,
                     "RSS should declare GeoRSS namespace")
        self.assertIn('xmlns:gml="http://www.opengis.net/gml"', xml_content,
                     "RSS should declare GML namespace")

    def test_rss_channel_required_elements(self):
        """Test RSS channel has all required elements."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        channel = root.find('channel')
        self.assertIsNotNone(channel, "RSS should have a <channel> element")

        # Required elements per RSS 2.0 spec
        title = channel.find('title')
        self.assertIsNotNone(title, "Channel should have <title>")
        self.assertTrue(len(title.text) > 0, "Channel title should not be empty")

        link = channel.find('link')
        self.assertIsNotNone(link, "Channel should have <link>")
        self.assertTrue(len(link.text) > 0, "Channel link should not be empty")

        description = channel.find('description')
        self.assertIsNotNone(description, "Channel should have <description>")
        self.assertTrue(len(description.text) > 0, "Channel description should not be empty")

    def test_rss_channel_atom_link(self):
        """Test RSS channel has atom:link for self-reference."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        channel = root.find('channel')
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        atom_links = channel.findall('atom:link', ns)
        self.assertGreater(len(atom_links), 0, "Channel should have atom:link")

        # Find a self link (there may be multiple)
        self_link = None
        for link in atom_links:
            if link.get('rel') == 'self':
                self_link = link
                # Prefer link with type attribute
                if link.get('type') == 'application/rss+xml':
                    break

        self.assertIsNotNone(self_link, "Channel should have atom:link with rel='self'")
        self.assertTrue(
            self_link.get('href').endswith('.rss'),
            "atom:link href should end with .rss"
        )
        # At least one self link should have the proper type
        typed_self_links = [
            link for link in atom_links
            if link.get('rel') == 'self' and link.get('type') == 'application/rss+xml'
        ]
        self.assertGreater(
            len(typed_self_links), 0,
            "At least one atom:link should have type='application/rss+xml'"
        )

    def test_rss_items_exist(self):
        """Test RSS feed contains items."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        channel = root.find('channel')
        items = channel.findall('item')

        self.assertGreater(len(items), 0, "RSS feed should contain at least one item")
        self.assertEqual(len(items), 4, "RSS feed should contain 4 test publications")

    def test_rss_item_required_elements(self):
        """Test each RSS item has required elements (title or description)."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        channel = root.find('channel')
        items = channel.findall('item')

        for i, item in enumerate(items):
            title = item.find('title')
            description = item.find('description')

            # RSS 2.0 spec requires at least one of title or description
            has_title = title is not None and len(title.text or '') > 0
            has_description = description is not None and len(description.text or '') > 0

            self.assertTrue(
                has_title or has_description,
                f"Item {i} should have either <title> or <description>"
            )

    def test_rss_item_link(self):
        """Test RSS items have valid link elements."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        channel = root.find('channel')
        items = channel.findall('item')

        for item in items:
            link = item.find('link')
            self.assertIsNotNone(link, "Item should have <link>")
            self.assertTrue(
                link.text.startswith('http'),
                f"Item link should be a valid URL: {link.text}"
            )

    def test_rss_item_guid(self):
        """Test RSS items have valid GUID elements."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        channel = root.find('channel')
        items = channel.findall('item')

        for item in items:
            guid = item.find('guid')
            # GUID is optional in RSS 2.0, but if present should be valid
            if guid is not None:
                self.assertTrue(
                    len(guid.text) > 0,
                    "GUID should not be empty if present"
                )

    def test_rss_item_pubdate_format(self):
        """Test RSS items have valid pubDate in RFC 822 format."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        channel = root.find('channel')
        items = channel.findall('item')

        for item in items:
            pubdate = item.find('pubDate')
            if pubdate is not None and pubdate.text:
                # RFC 822 date format: "Wed, 02 Oct 2002 13:00:00 GMT"
                # Should contain day name, day, month name, year, time
                date_parts = pubdate.text.split()
                self.assertGreaterEqual(
                    len(date_parts), 5,
                    f"pubDate should be in RFC 822 format: {pubdate.text}"
                )

    def test_rss_item_author_with_openalex(self):
        """Test RSS items with OpenAlex authors have dc:creator."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        channel = root.find('channel')
        items = channel.findall('item')

        ns = {'dc': 'http://purl.org/dc/elements/1.1/'}

        # Find item with "Complete Publication Test" title
        for item in items:
            title = item.find('title')
            if title.text == "Complete Publication Test":
                creator = item.find('dc:creator', ns)
                self.assertIsNotNone(
                    creator,
                    "Item with authors should have dc:creator"
                )
                # Should have multiple authors listed
                self.assertIn(',', creator.text, "Multiple authors should be comma-separated")
                break
        else:
            self.fail("Could not find test item 'Complete Publication Test'")

    def test_rss_item_author_et_al_threshold(self):
        """Test RSS items with >10 authors use 'et al.'."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        channel = root.find('channel')
        items = channel.findall('item')

        ns = {'dc': 'http://purl.org/dc/elements/1.1/'}

        # Find item with many authors
        for item in items:
            title = item.find('title')
            if title.text == "Publication With Many Authors":
                creator = item.find('dc:creator', ns)
                self.assertIsNotNone(creator, "Item should have dc:creator")
                self.assertIn(
                    'et al.',
                    creator.text,
                    "Items with >10 authors should use 'et al.'"
                )
                break
        else:
            self.fail("Could not find test item 'Publication With Many Authors'")

    def test_rss_item_no_author(self):
        """Test RSS items without authors don't have dc:creator."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        channel = root.find('channel')
        items = channel.findall('item')

        ns = {'dc': 'http://purl.org/dc/elements/1.1/'}

        # Find item without authors
        for item in items:
            title = item.find('title')
            if title.text == "Publication Without Authors":
                creator = item.find('dc:creator', ns)
                self.assertIsNone(
                    creator,
                    "Item without authors should not have dc:creator"
                )
                break
        else:
            self.fail("Could not find test item 'Publication Without Authors'")

    def test_rss_item_source_element(self):
        """Test RSS items have source element for publishing venue."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        channel = root.find('channel')
        items = channel.findall('item')

        # Find item with source
        for item in items:
            title = item.find('title')
            if title.text == "Complete Publication Test":
                source = item.find('source')
                self.assertIsNotNone(
                    source,
                    "Item with source should have <source> element"
                )

                source_title = source.find('title')
                self.assertIsNotNone(
                    source_title,
                    "Source should have <title>"
                )
                self.assertEqual(
                    source_title.text,
                    "Test Journal",
                    "Source title should match publication source"
                )

                source_url = source.find('url')
                self.assertIsNotNone(
                    source_url,
                    "Source should have <url>"
                )
                break
        else:
            self.fail("Could not find test item 'Complete Publication Test'")

    def test_rss_item_categories(self):
        """Test RSS items have category elements for keywords/topics."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        channel = root.find('channel')
        items = channel.findall('item')

        # Find item with categories
        for item in items:
            title = item.find('title')
            if title.text == "Complete Publication Test":
                categories = item.findall('category')
                self.assertGreater(
                    len(categories), 0,
                    "Item with keywords/topics should have categories"
                )

                category_texts = [cat.text for cat in categories]
                # Check for test keywords
                self.assertIn('test', category_texts, "Should include keyword 'test'")
                break
        else:
            self.fail("Could not find test item 'Complete Publication Test'")

    def test_rss_georss_point(self):
        """Test RSS items with point geometry have georss:point."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        channel = root.find('channel')
        items = channel.findall('item')

        ns = {'georss': 'http://www.georss.org/georss'}

        # Find item with point geometry
        for item in items:
            title = item.find('title')
            if title.text == "Complete Publication Test":
                georss_point = item.find('georss:point', ns)
                self.assertIsNotNone(
                    georss_point,
                    "Item with point geometry should have georss:point"
                )

                # Point should be in "lat lon" format
                coords = georss_point.text.split()
                self.assertEqual(
                    len(coords), 2,
                    "georss:point should have 2 coordinates (lat lon)"
                )

                # Verify coordinates are numeric
                lat, lon = coords
                self.assertTrue(
                    -90 <= float(lat) <= 90,
                    "Latitude should be in valid range"
                )
                self.assertTrue(
                    -180 <= float(lon) <= 180,
                    "Longitude should be in valid range"
                )
                break
        else:
            self.fail("Could not find test item 'Complete Publication Test'")

    def test_rss_georss_polygon(self):
        """Test RSS items with polygon geometry have georss:polygon."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        channel = root.find('channel')
        items = channel.findall('item')

        ns = {'georss': 'http://www.georss.org/georss'}

        # Find item with polygon geometry
        for item in items:
            title = item.find('title')
            if title.text == "Publication With Many Authors":
                georss_polygon = item.find('georss:polygon', ns)
                self.assertIsNotNone(
                    georss_polygon,
                    "Item with polygon geometry should have georss:polygon"
                )

                # Polygon should be space-separated lat/lon pairs
                coords = georss_polygon.text.split()
                self.assertGreater(
                    len(coords), 0,
                    "georss:polygon should have coordinates"
                )
                self.assertEqual(
                    len(coords) % 2, 0,
                    "georss:polygon should have even number of values (lat/lon pairs)"
                )
                break
        else:
            self.fail("Could not find test item 'Publication With Many Authors'")

    def test_rss_georss_line(self):
        """Test RSS items with line geometry have georss:line."""
        xml_content = self._fetch_rss_feed()
        root = self._parse_rss(xml_content)

        channel = root.find('channel')
        items = channel.findall('item')

        ns = {'georss': 'http://www.georss.org/georss'}

        # Find item with line geometry
        for item in items:
            title = item.find('title')
            if title.text == "Publication With LineString":
                georss_line = item.find('georss:line', ns)
                self.assertIsNotNone(
                    georss_line,
                    "Item with line geometry should have georss:line"
                )

                # Line should be space-separated lat/lon pairs
                coords = georss_line.text.split()
                self.assertGreaterEqual(
                    len(coords), 4,
                    "georss:line should have at least 2 points (4 values)"
                )
                self.assertEqual(
                    len(coords) % 2, 0,
                    "georss:line should have even number of values (lat/lon pairs)"
                )
                break
        else:
            self.fail("Could not find test item 'Publication With LineString'")


class Atom10SpecificationTestCase(TestCase):
    """
    Test cases validating Atom 1.0 feed against the Atom 1.0 specification (RFC 4287).

    Required feed elements:
    - id
    - title
    - updated

    Required entry elements:
    - id
    - title
    - updated

    Optional elements tested:
    - author
    - link
    - category
    - summary
    - content
    - source
    """

    @classmethod
    def setUpTestData(cls):
        """Set up test data - same as RSS tests."""
        Publication.objects.all().delete()

        # Create a test source
        cls.source = Source.objects.create(
            name="Test Journal",
            url_field="https://example.com/feed",
            abbreviated_title="Test J.",
            homepage_url="https://example.com",
            issn_l="1234-5678",
            publisher_name="Test Publisher",
            is_oa=True,
            is_preprint=False,
        )

        # Publication with full metadata
        cls.pub_full = Publication.objects.create(
            title="Complete Publication Test",
            abstract="A complete publication with all metadata fields populated.",
            url="https://example.com/complete",
            status="p",
            publicationDate=datetime(2023, 6, 15),
            doi="10.1234/complete-test",
            source=cls.source,
            geometry=GeometryCollection(Point(13.0, 52.0)),
            openalex_id="https://openalex.org/W123456789",
            openalex_authors=["Alice Smith", "Bob Jones"],
            openalex_keywords=["test", "atom"],
        )

        # Publication without authors
        cls.pub_no_authors = Publication.objects.create(
            title="Publication Without Authors",
            url="https://example.com/no-authors",
            status="p",
            publicationDate=datetime(2023, 7, 20),
            doi="10.1234/no-authors",
            source=cls.source,
            geometry=GeometryCollection(Point(14.0, 53.0)),
        )

    def _fetch_atom_feed(self):
        """Fetch the global Atom feed."""
        response = self.client.get('/api/v1/feeds/optimap-global.atom')
        self.assertEqual(response.status_code, 200, "Atom feed should return 200")
        self.assertEqual(
            response['Content-Type'],
            'application/atom+xml; charset=utf-8',
            "Atom feed should have correct Content-Type"
        )
        return response.content.decode('utf-8')

    def _parse_atom(self, xml_content):
        """Parse Atom XML and return root element."""
        try:
            root = ET.fromstring(xml_content)
            return root
        except ET.ParseError as e:
            self.fail(f"Atom feed is not valid XML: {e}")

    def test_atom_valid_xml(self):
        """Test that Atom feed is valid XML."""
        xml_content = self._fetch_atom_feed()
        root = self._parse_atom(xml_content)
        self.assertIsNotNone(root, "Atom feed should be valid XML")

    def test_atom_root_element(self):
        """Test Atom root element is <feed> with correct namespace."""
        xml_content = self._fetch_atom_feed()
        root = self._parse_atom(xml_content)

        # Remove namespace prefix for comparison
        tag = root.tag.split('}')[-1] if '}' in root.tag else root.tag
        self.assertEqual(tag, 'feed', "Root element should be <feed>")

        # Check namespace
        self.assertIn(
            'http://www.w3.org/2005/Atom',
            root.tag,
            "Feed should use Atom namespace"
        )

    def test_atom_namespaces(self):
        """Test Atom feed declares required namespaces."""
        xml_content = self._fetch_atom_feed()

        self.assertIn(
            'http://www.w3.org/2005/Atom',
            xml_content,
            "Atom feed should have Atom namespace"
        )
        self.assertIn(
            'xmlns:georss="http://www.georss.org/georss"',
            xml_content,
            "Atom feed should declare GeoRSS namespace"
        )

    def test_atom_feed_required_elements(self):
        """Test Atom feed has all required elements."""
        xml_content = self._fetch_atom_feed()
        root = self._parse_atom(xml_content)

        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        # Required elements per Atom spec
        feed_id = root.find('atom:id', ns)
        self.assertIsNotNone(feed_id, "Feed should have <id>")
        self.assertTrue(len(feed_id.text) > 0, "Feed id should not be empty")

        title = root.find('atom:title', ns)
        self.assertIsNotNone(title, "Feed should have <title>")
        self.assertTrue(len(title.text) > 0, "Feed title should not be empty")

        updated = root.find('atom:updated', ns)
        self.assertIsNotNone(updated, "Feed should have <updated>")
        self.assertTrue(len(updated.text) > 0, "Feed updated should not be empty")

    def test_atom_feed_link_self(self):
        """Test Atom feed has self link."""
        xml_content = self._fetch_atom_feed()
        root = self._parse_atom(xml_content)

        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        links = root.findall('atom:link', ns)
        self.assertGreater(len(links), 0, "Feed should have link elements")

        # Find self link
        self_link = None
        for link in links:
            if link.get('rel') == 'self':
                self_link = link
                break

        self.assertIsNotNone(self_link, "Feed should have self link")
        self.assertTrue(
            self_link.get('href').endswith('.atom'),
            "Self link should point to .atom file"
        )

    def test_atom_entries_exist(self):
        """Test Atom feed contains entries."""
        xml_content = self._fetch_atom_feed()
        root = self._parse_atom(xml_content)

        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        entries = root.findall('atom:entry', ns)
        self.assertGreater(len(entries), 0, "Atom feed should contain at least one entry")

    def test_atom_entry_required_elements(self):
        """Test each Atom entry has required elements."""
        xml_content = self._fetch_atom_feed()
        root = self._parse_atom(xml_content)

        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        entries = root.findall('atom:entry', ns)

        for i, entry in enumerate(entries):
            entry_id = entry.find('atom:id', ns)
            self.assertIsNotNone(entry_id, f"Entry {i} should have <id>")
            self.assertTrue(
                len(entry_id.text) > 0,
                f"Entry {i} id should not be empty"
            )

            title = entry.find('atom:title', ns)
            self.assertIsNotNone(title, f"Entry {i} should have <title>")
            self.assertTrue(
                len(title.text) > 0,
                f"Entry {i} title should not be empty"
            )

            updated = entry.find('atom:updated', ns)
            self.assertIsNotNone(updated, f"Entry {i} should have <updated>")
            self.assertTrue(
                len(updated.text) > 0,
                f"Entry {i} updated should not be empty"
            )

    def test_atom_entry_updated_format(self):
        """Test Atom entry updated dates are in ISO 8601 format."""
        xml_content = self._fetch_atom_feed()
        root = self._parse_atom(xml_content)

        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        entries = root.findall('atom:entry', ns)

        for entry in entries:
            updated = entry.find('atom:updated', ns)
            if updated is not None and updated.text:
                # ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ or similar
                self.assertIn('T', updated.text, "Updated should be in ISO 8601 format")
                # Should be parseable as datetime
                try:
                    # Try parsing various ISO 8601 formats
                    from dateutil import parser
                    parser.isoparse(updated.text.replace('Z', '+00:00'))
                except Exception as e:
                    self.fail(f"Updated date should be valid ISO 8601: {updated.text} - {e}")

    def test_atom_entry_author(self):
        """Test Atom entries with authors have author element."""
        xml_content = self._fetch_atom_feed()
        root = self._parse_atom(xml_content)

        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        entries = root.findall('atom:entry', ns)

        # Find entry with authors
        for entry in entries:
            title = entry.find('atom:title', ns)
            if title.text == "Complete Publication Test":
                author = entry.find('atom:author', ns)
                self.assertIsNotNone(author, "Entry with authors should have <author>")

                author_name = author.find('atom:name', ns)
                self.assertIsNotNone(
                    author_name,
                    "Author should have <name>"
                )
                self.assertTrue(
                    len(author_name.text) > 0,
                    "Author name should not be empty"
                )
                break
        else:
            self.fail("Could not find test entry 'Complete Publication Test'")

    def test_atom_entry_link(self):
        """Test Atom entries have link elements."""
        xml_content = self._fetch_atom_feed()
        root = self._parse_atom(xml_content)

        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        entries = root.findall('atom:entry', ns)

        for entry in entries:
            links = entry.findall('atom:link', ns)
            self.assertGreater(
                len(links), 0,
                "Entry should have at least one link"
            )

            # Check for alternate link
            for link in links:
                if link.get('rel') == 'alternate' or not link.get('rel'):
                    href = link.get('href')
                    self.assertIsNotNone(href, "Link should have href")
                    self.assertTrue(
                        href.startswith('http'),
                        "Link href should be a valid URL"
                    )
                    break

    def test_atom_entry_summary(self):
        """Test Atom entries have summary (abstract)."""
        xml_content = self._fetch_atom_feed()
        root = self._parse_atom(xml_content)

        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        entries = root.findall('atom:entry', ns)

        # Find entry with abstract
        for entry in entries:
            title = entry.find('atom:title', ns)
            if title.text == "Complete Publication Test":
                summary = entry.find('atom:summary', ns)
                self.assertIsNotNone(
                    summary,
                    "Entry with abstract should have <summary>"
                )
                self.assertTrue(
                    len(summary.text) > 0,
                    "Summary should not be empty"
                )
                break

    def test_atom_entry_source(self):
        """Test Atom entries have source element for publishing venue."""
        xml_content = self._fetch_atom_feed()
        root = self._parse_atom(xml_content)

        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        entries = root.findall('atom:entry', ns)

        # Find entry with source
        for entry in entries:
            title = entry.find('atom:title', ns)
            if title.text == "Complete Publication Test":
                source = entry.find('atom:source', ns)
                self.assertIsNotNone(
                    source,
                    "Entry with source should have <source> element"
                )

                source_title = source.find('atom:title', ns)
                self.assertIsNotNone(
                    source_title,
                    "Source should have <title>"
                )
                self.assertEqual(
                    source_title.text,
                    "Test Journal",
                    "Source title should match publication source"
                )
                break
        else:
            self.fail("Could not find test entry 'Complete Publication Test'")

    def test_atom_entry_category(self):
        """Test Atom entries have category elements for keywords."""
        xml_content = self._fetch_atom_feed()
        root = self._parse_atom(xml_content)

        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        entries = root.findall('atom:entry', ns)

        # Find entry with categories
        for entry in entries:
            title = entry.find('atom:title', ns)
            if title.text == "Complete Publication Test":
                categories = entry.findall('atom:category', ns)
                self.assertGreater(
                    len(categories), 0,
                    "Entry with keywords should have categories"
                )

                # Categories should have term attribute
                for category in categories:
                    term = category.get('term')
                    self.assertIsNotNone(
                        term,
                        "Category should have term attribute"
                    )
                break
        else:
            self.fail("Could not find test entry 'Complete Publication Test'")

    def test_atom_georss_point(self):
        """Test Atom entries with point geometry have georss:point."""
        xml_content = self._fetch_atom_feed()
        root = self._parse_atom(xml_content)

        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'georss': 'http://www.georss.org/georss'
        }

        entries = root.findall('atom:entry', ns)

        # Find entry with point geometry
        for entry in entries:
            title = entry.find('atom:title', ns)
            if title.text == "Complete Publication Test":
                georss_point = entry.find('georss:point', ns)
                self.assertIsNotNone(
                    georss_point,
                    "Entry with point geometry should have georss:point"
                )

                # Verify format
                coords = georss_point.text.split()
                self.assertEqual(
                    len(coords), 2,
                    "georss:point should have 2 coordinates"
                )
                break
        else:
            self.fail("Could not find test entry 'Complete Publication Test'")
