"""
UI tests for admin-only content visibility.
Tests verify that admin-only buttons and features are:
1. NOT visible to anonymous users
2. NOT visible to regular authenticated users
3. VISIBLE to admin/staff users
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from helium import (
    start_chrome,
    kill_browser,
    get_driver,
    Text,
    Button,
)
import requests

from works.models import Work

User = get_user_model()


def get_work_from_api():
    """Helper function to get a work (id, doi) from the API instead of database."""
    response = requests.get('http://localhost:8000/api/v1/works/', timeout=5)
    if response.status_code == 200:
        data = response.json()
        if data.get('results') and len(data['results']) > 0:
            work = data['results']['features'][0]
            return {'id': work.get('id'), 'doi': work.get('properties').get('doi'), 'title': work.get('properties').get('title')}
    

class AdminContentVisibilityTests(TestCase):
    """Test that admin-only content is properly restricted."""

    fixtures = ['test_data_optimap.json']

    @classmethod
    def setUpClass(cls):
        """Create test users."""
        super().setUpClass()

    def setUp(self):
        """Set up test users for each test."""
        # Create admin user
        self.admin_user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpass123'
        )

        # Create regular user
        self.regular_user = User.objects.create_user(
            username='regular',
            email='regular@example.com',
            password='regularpass123'
        )

    def test_work_landing_admin_buttons_not_visible_anonymous(self):
        """Test that admin buttons are not visible on work landing page for anonymous users."""
        # Get a work from fixtures - works are loaded with specific IDs from fixture
        # Try a few common IDs or skip if no works exist
        work = Work.objects.filter(status="p",doi__isnull=False).first()
        if work:
            response = self.client.get(f'/work/{work.doi}/')
            if response.status_code == 200:
                # Admin edit button should not be present
                self.assertNotContains(response, 'Edit in Admin')
                self.assertNotContains(response, '/admin/works/work/')
        else:
            self.skipTest('No works available in test database')

    def test_work_landing_admin_buttons_not_visible_regular_user(self):
        """Test that admin buttons are not visible to regular authenticated users."""
        # Login as regular user
        self.client.login(username='regular', password='regularpass123')

        work = Work.objects.filter(status="p",doi__isnull=False).first()
        if work:
            response = self.client.get(f'/work/{work.doi}/')
            if response.status_code == 200:
                # Admin edit button should not be present
                self.assertNotContains(response, 'Edit in Admin')
                self.assertNotContains(response, '/admin/works/work/')
        else:
            self.skipTest('No works available in test database')

    def test_work_landing_admin_buttons_visible_to_staff(self):
        """Test that admin buttons ARE visible to staff users."""
        # Login as admin user
        self.client.login(username='admin', password='adminpass123')

        work = Work.objects.filter(status="p",doi__isnull=False).first()
        if work:
            response = self.client.get(f'/work/{work.doi}/')
            if response.status_code == 200:
                # Admin edit button should be present
                self.assertContains(response, 'Edit in Admin')
                self.assertContains(response, '/admin/works/work/')
        else:
            self.skipTest('No works available in test database')

    def test_admin_panel_not_accessible_anonymous(self):
        """Test that admin panel redirects anonymous users to login."""
        response = self.client.get('/admin/')
        # Should redirect to login page
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login', response.url)

    def test_admin_panel_not_accessible_regular_user(self):
        """Test that admin panel is not accessible to regular users."""
        self.client.login(username='regular', password='regularpass123')
        response = self.client.get('/admin/')
        # Should redirect to login page (regular users can't access admin)
        self.assertEqual(response.status_code, 302)

    def test_admin_panel_accessible_to_staff(self):
        """Test that admin panel is accessible to staff users."""
        self.client.login(username='admin', password='adminpass123')
        response = self.client.get('/admin/')
        # Should show admin page
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Site administration')


class AdminButtonsBrowserTests(TestCase):
    """Browser-based tests for admin button visibility."""

    fixtures = ['test_data_optimap.json']

    def setUp(self):
        """Set up test users for each test."""
        # Create admin user
        self.admin_user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpass123'
        )

    def test_work_landing_page_anonymous_no_admin_buttons(self):
        """Test that work landing page doesn't show admin buttons to anonymous users."""

        # Get work from API instead of database
        work_data = get_work_from_api()

        try:
            start_chrome(f'localhost:8000/work/{work_data["doi"]}/', headless=True)
            driver = get_driver()

            # Wait for page to load
            self.assertIn("OPTIMAP", driver.title)

            # Check that admin buttons are not present
            edit_buttons = driver.find_elements("xpath", "//a[contains(text(), 'Edit in Admin')]")
            self.assertEqual(len(edit_buttons), 0, "Edit in Admin button should not be visible")

        finally:
            kill_browser()

    def test_contribute_page_anonymous_no_publish_buttons(self):
        """Test that contribute page doesn't show publish buttons to anonymous users."""
        try:
            start_chrome('localhost:8000/contribute/', headless=True)
            driver = get_driver()

            # Wait for page to load
            self.assertIn("OPTIMAP", driver.title)

            # Check for absence of admin-only buttons
            publish_buttons = driver.find_elements("xpath", "//button[contains(text(), 'Publish')]")

            # Should have no visible publish buttons for anonymous users
            self.assertEqual(len(publish_buttons), 0, "Publish buttons should not be visible to anonymous users")

        finally:
            kill_browser()
