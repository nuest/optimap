# tests-ui/test_works_page.py
"""
Tests for the works list page (/works).
Tests pagination, statistics, and work display features.
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.conf import settings
from works.models import Work, Source
from works.utils.statistics import update_statistics_cache, STATS_CACHE_KEY

User = get_user_model()


class WorksListViewTest(TestCase):
    """Test the works list view with pagination and statistics"""

    @classmethod
    def setUpTestData(cls):
        """Create test data once for all tests"""
        # Create a test source
        cls.source = Source.objects.create(
            name="Test Journal",
            issn_l="1234-5678"
        )

        # Create test publications (75 total: 60 published, 15 draft)
        cls.publications = []
        for i in range(75):
            status = 'p' if i < 60 else 'd'
            authors = [f"Author {i}A", f"Author {i}B", f"Author {i}C", f"Author {i}D"] if i % 2 == 0 else [f"Author {i}"]
            work = Work.objects.create(
                title=f"Test Work {i}",
                status=status,
                doi=f"10.1234/test.{i}" if i % 3 == 0 else None,
                source=cls.source if i % 4 == 0 else None,
                authors=authors,
                abstract=f"Abstract for work {i}" if i % 5 == 0 else None,
            )
            cls.publications.append(work)

    def setUp(self):
        """Set up for each test"""
        self.client = Client()
        # Clear cache before each test
        cache.clear()

    def test_works_page_loads(self):
        """Test that the works page loads successfully"""
        response = self.client.get(reverse('optimap:works'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'works.html')

    def test_works_page_settings_import(self):
        """Test that settings are properly imported and accessible (regression test)"""
        # This test catches the NameError: name 'settings' is not defined
        # by verifying the view can access settings.WORKS_PAGE_SIZE_DEFAULT
        response = self.client.get(reverse('optimap:works'))
        self.assertEqual(response.status_code, 200)

        # Verify page_size was correctly set using settings
        self.assertIn('page_size', response.context)
        self.assertEqual(
            response.context['page_size'],
            settings.WORKS_PAGE_SIZE_DEFAULT
        )

    def test_pagination_default_page_size(self):
        """Test that default page size is applied"""
        response = self.client.get(reverse('optimap:works'))
        self.assertEqual(response.status_code, 200)

        # Should use default page size (50)
        self.assertEqual(len(response.context['works']), 50)
        self.assertEqual(response.context['page_size'], settings.WORKS_PAGE_SIZE_DEFAULT)

    def test_pagination_custom_page_size(self):
        """Test custom page size selection"""
        response = self.client.get(reverse('optimap:works') + '?size=25')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['works']), 25)
        self.assertEqual(response.context['page_size'], 25)

    def test_pagination_max_limit(self):
        """Test that page size is clamped to maximum"""
        response = self.client.get(reverse('optimap:works') + '?size=1000')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_size'], settings.WORKS_PAGE_SIZE_MAX)

    def test_pagination_min_limit(self):
        """Test that page size is clamped to minimum"""
        response = self.client.get(reverse('optimap:works') + '?size=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_size'], settings.WORKS_PAGE_SIZE_MIN)

    def test_pagination_page_navigation(self):
        """Test navigating between pages"""
        # First page
        response = self.client.get(reverse('optimap:works') + '?page=1&size=25')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].number, 1)
        self.assertTrue(response.context['page_obj'].has_next())
        self.assertFalse(response.context['page_obj'].has_previous())

        # Second page
        response = self.client.get(reverse('optimap:works') + '?page=2&size=25')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].number, 2)
        self.assertTrue(response.context['page_obj'].has_next())
        self.assertTrue(response.context['page_obj'].has_previous())

    def test_only_published_works_shown_to_public(self):
        """Test that non-admin users only see published works"""
        response = self.client.get(reverse('optimap:works'))
        self.assertEqual(response.status_code, 200)

        # Should show 60 published works (not 75 total)
        self.assertEqual(response.context['page_obj'].paginator.count, 60)

    def test_admin_sees_all_works(self):
        """Test that admin users see all works including drafts"""
        # Create admin user
        admin = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123'
        )
        admin.is_staff = True
        admin.save()

        self.client.login(username='admin', password='testpass123')
        response = self.client.get(reverse('optimap:works'))

        self.assertEqual(response.status_code, 200)
        # Should show all 75 works
        self.assertEqual(response.context['page_obj'].paginator.count, 75)
        self.assertTrue(response.context['is_admin'])

    def test_work_includes_authors(self):
        """Test that work data includes author information"""
        response = self.client.get(reverse('optimap:works'))
        self.assertEqual(response.status_code, 200)

        # Check first work has authors
        first_work = response.context['works'][0]
        self.assertIn('authors', first_work)
        self.assertIsInstance(first_work['authors'], list)

    def test_work_includes_doi(self):
        """Test that work data includes DOI"""
        response = self.client.get(reverse('optimap:works'))
        self.assertEqual(response.status_code, 200)

        # Find a work with DOI
        works_with_doi = [w for w in response.context['works'] if w['doi']]
        self.assertGreater(len(works_with_doi), 0)

    def test_work_includes_source(self):
        """Test that work data includes source information"""
        response = self.client.get(reverse('optimap:works'))
        self.assertEqual(response.status_code, 200)

        # Find a work with source
        works_with_source = [w for w in response.context['works'] if w['source']]
        self.assertGreater(len(works_with_source), 0)

    def test_statistics_displayed(self):
        """Test that statistics are included in context"""
        # Update statistics cache
        update_statistics_cache()

        response = self.client.get(reverse('optimap:works'))
        self.assertEqual(response.status_code, 200)

        self.assertIn('statistics', response.context)
        stats = response.context['statistics']

        self.assertIn('total_works', stats)
        self.assertIn('published_works', stats)
        self.assertIn('with_geometry', stats)
        self.assertIn('with_temporal', stats)
        self.assertIn('with_authors', stats)
        self.assertIn('with_doi', stats)

    def test_statistics_cached(self):
        """Test that statistics are cached"""
        # First request should calculate and cache
        cache.delete(STATS_CACHE_KEY)
        response1 = self.client.get(reverse('optimap:works'))
        stats1 = response1.context['statistics']

        # Second request should use cache
        response2 = self.client.get(reverse('optimap:works'))
        stats2 = response2.context['statistics']

        self.assertEqual(stats1, stats2)
        # Verify cache was used
        self.assertIsNotNone(cache.get(STATS_CACHE_KEY))

    def test_api_url_present(self):
        """Test that API URL is included in context"""
        response = self.client.get(reverse('optimap:works') + '?page=2&size=25')
        self.assertEqual(response.status_code, 200)

        self.assertIn('api_url', response.context)
        api_url = response.context['api_url']

        # API URL should include limit and offset (not page)
        # Page 2 with size 25 = offset 25
        self.assertIn('limit=25', api_url)
        self.assertIn('offset=25', api_url)

    def test_pagination_controls_in_template(self):
        """Test that pagination controls are rendered"""
        response = self.client.get(reverse('optimap:works'))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')

        # Check for pagination elements
        self.assertIn('pagination', content)
        self.assertIn('Works per page:', content)
        self.assertIn('page-size', content)

    def test_statistics_section_in_template(self):
        """Test that statistics section is rendered"""
        update_statistics_cache()
        response = self.client.get(reverse('optimap:works'))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')

        # Check for statistics section
        self.assertIn('Statistics', content)
        self.assertIn('Total works in database:', content)
        self.assertIn('Published works:', content)
        self.assertIn('Complete metadata coverage:', content)

    def test_api_link_in_template(self):
        """Test that API link is rendered"""
        response = self.client.get(reverse('optimap:works'))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')

        # Check for API link section
        self.assertIn('API Access:', content)
        self.assertIn('View this page as JSON (API)', content)

    def test_authors_abbreviated_for_many(self):
        """Test that author list is abbreviated for >3 authors"""
        response = self.client.get(reverse('optimap:works'))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')

        # Should find "et al." for publications with >3 authors
        self.assertIn('et al.', content)

    def test_doi_link_external(self):
        """Test that DOI links are external"""
        response = self.client.get(reverse('optimap:works'))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')

        # Check for DOI links
        if 'doi.org' in content:
            self.assertIn('target="_blank"', content)
            self.assertIn('rel="noopener"', content)

    def test_invalid_page_number_handled(self):
        """Test that invalid page numbers are handled gracefully"""
        # Non-integer page number
        response = self.client.get(reverse('optimap:works') + '?page=abc')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].number, 1)

        # Out of range page number
        response = self.client.get(reverse('optimap:works') + '?page=9999')
        self.assertEqual(response.status_code, 200)
        # Should show last page
        self.assertEqual(
            response.context['page_obj'].number,
            response.context['page_obj'].paginator.num_pages
        )

    def test_page_size_options_in_context(self):
        """Test that page size options are in context"""
        response = self.client.get(reverse('optimap:works'))
        self.assertEqual(response.status_code, 200)

        self.assertIn('page_size_options', response.context)
        self.assertEqual(
            response.context['page_size_options'],
            settings.WORKS_PAGE_SIZE_OPTIONS
        )
