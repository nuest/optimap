import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
django.setup()

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from works.models import Subscription, GlobalRegion
from django.contrib.gis.geos import MultiPolygon, Polygon

User = get_user_model()


class SubscriptionTests(TestCase):
    """Tests for regional subscription functionality"""

    def setUp(self):
        """Set up test user, client, and test regions"""
        self.client = Client()

        # Create test user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )

        # Create test regions (continents and oceans)
        # Simple polygon for testing (a small square)
        test_polygon = Polygon(((0, 0), (0, 1), (1, 1), (1, 0), (0, 0)))
        test_multipolygon = MultiPolygon(test_polygon)

        self.africa = GlobalRegion.objects.create(
            name="Africa",
            region_type=GlobalRegion.CONTINENT,
            source_url="https://example.com/africa",
            license="CC0",
            geom=test_multipolygon
        )

        self.asia = GlobalRegion.objects.create(
            name="Asia",
            region_type=GlobalRegion.CONTINENT,
            source_url="https://example.com/asia",
            license="CC0",
            geom=test_multipolygon
        )

        self.pacific = GlobalRegion.objects.create(
            name="Pacific Ocean",
            region_type=GlobalRegion.OCEAN,
            source_url="https://example.com/pacific",
            license="CC0",
            geom=test_multipolygon
        )

        self.atlantic = GlobalRegion.objects.create(
            name="Atlantic Ocean",
            region_type=GlobalRegion.OCEAN,
            source_url="https://example.com/atlantic",
            license="CC0",
            geom=test_multipolygon
        )

    def test_subscription_page_requires_authentication(self):
        """Test that subscription page requires login"""
        response = self.client.get(reverse('optimap:subscriptions'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
        # Redirects to homepage with next parameter for login
        self.assertIn('next=/subscriptions/', response.url)

    def test_subscription_page_shows_regions(self):
        """Test that subscription page displays all available regions"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('optimap:subscriptions'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Africa')
        self.assertContains(response, 'Asia')
        self.assertContains(response, 'Pacific Ocean')
        self.assertContains(response, 'Atlantic Ocean')

        # Check that regions are properly grouped
        self.assertContains(response, 'Continents')
        self.assertContains(response, 'Oceans')

    def test_create_subscription_with_single_region(self):
        """Test creating a subscription with a single region"""
        self.client.login(username='testuser', password='testpass123')

        response = self.client.post(
            reverse('optimap:addsubscriptions'),
            {'regions': [self.africa.id]}
        )

        self.assertEqual(response.status_code, 302)  # Redirect after success

        # Verify subscription was created
        subscription = Subscription.objects.get(user=self.user)
        self.assertEqual(subscription.regions.count(), 1)
        self.assertIn(self.africa, subscription.regions.all())

    def test_create_subscription_with_multiple_regions(self):
        """Test creating a subscription with multiple regions"""
        self.client.login(username='testuser', password='testpass123')

        response = self.client.post(
            reverse('optimap:addsubscriptions'),
            {'regions': [self.africa.id, self.asia.id, self.pacific.id]}
        )

        self.assertEqual(response.status_code, 302)

        # Verify subscription has all three regions
        subscription = Subscription.objects.get(user=self.user)
        self.assertEqual(subscription.regions.count(), 3)
        self.assertIn(self.africa, subscription.regions.all())
        self.assertIn(self.asia, subscription.regions.all())
        self.assertIn(self.pacific, subscription.regions.all())

    def test_update_existing_subscription(self):
        """Test updating an existing subscription's regions"""
        self.client.login(username='testuser', password='testpass123')

        # Create initial subscription with Africa
        self.client.post(
            reverse('optimap:addsubscriptions'),
            {'regions': [self.africa.id]}
        )

        subscription = Subscription.objects.get(user=self.user)
        self.assertEqual(subscription.regions.count(), 1)

        # Update to include Asia and Pacific, removing Africa
        response = self.client.post(
            reverse('optimap:addsubscriptions'),
            {'regions': [self.asia.id, self.pacific.id]}
        )

        self.assertEqual(response.status_code, 302)

        # Verify subscription was updated
        subscription.refresh_from_db()
        self.assertEqual(subscription.regions.count(), 2)
        self.assertNotIn(self.africa, subscription.regions.all())
        self.assertIn(self.asia, subscription.regions.all())
        self.assertIn(self.pacific, subscription.regions.all())

    def test_clear_all_regions(self):
        """Test removing all regions from subscription"""
        self.client.login(username='testuser', password='testpass123')

        # Create subscription with regions
        self.client.post(
            reverse('optimap:addsubscriptions'),
            {'regions': [self.africa.id, self.asia.id]}
        )

        # Clear all regions (submit with no regions)
        response = self.client.post(
            reverse('optimap:addsubscriptions'),
            {'regions': []}  # Empty list
        )

        self.assertEqual(response.status_code, 302)

        # Verify all regions were removed
        subscription = Subscription.objects.get(user=self.user)
        self.assertEqual(subscription.regions.count(), 0)

    def test_subscription_page_shows_selected_regions(self):
        """Test that subscription page shows currently selected regions"""
        self.client.login(username='testuser', password='testpass123')

        # Create subscription with specific regions
        subscription = Subscription.objects.create(
            user=self.user,
            name=f'{self.user.username}_subscription'
        )
        subscription.regions.add(self.africa, self.pacific)

        # Load subscription page
        response = self.client.get(reverse('optimap:subscriptions'))

        self.assertEqual(response.status_code, 200)

        # Check that selected regions are marked as checked
        self.assertContains(response, f'value="{self.africa.id}"')
        self.assertContains(response, f'value="{self.pacific.id}"')

        # Check the summary shows correct count (note: contains HTML <strong> tags)
        self.assertContains(response, 'Currently monitoring')
        self.assertContains(response, '2 region')

    def test_subscription_summary_shows_region_names(self):
        """Test that subscription summary displays region names"""
        self.client.login(username='testuser', password='testpass123')

        # Create subscription with regions
        subscription = Subscription.objects.create(
            user=self.user,
            name=f'{self.user.username}_subscription'
        )
        subscription.regions.add(self.africa, self.asia, self.atlantic)

        # Load page
        response = self.client.get(reverse('optimap:subscriptions'))

        # Verify region names appear in summary
        self.assertContains(response, 'Africa')
        self.assertContains(response, 'Asia')
        self.assertContains(response, 'Atlantic Ocean')

    def test_no_regions_warning(self):
        """Test that warning shows when no regions are selected"""
        self.client.login(username='testuser', password='testpass123')

        # Create subscription with no regions
        Subscription.objects.create(
            user=self.user,
            name=f'{self.user.username}_subscription'
        )

        response = self.client.get(reverse('optimap:subscriptions'))

        self.assertContains(response, 'No regions selected')
        self.assertContains(response, 'text-warning')

    def test_invalid_region_id_ignored(self):
        """Test that invalid region IDs are ignored"""
        self.client.login(username='testuser', password='testpass123')

        response = self.client.post(
            reverse('optimap:addsubscriptions'),
            {'regions': [self.africa.id, 99999]}  # 99999 doesn't exist
        )

        self.assertEqual(response.status_code, 302)

        # Verify only valid region was added
        subscription = Subscription.objects.get(user=self.user)
        self.assertEqual(subscription.regions.count(), 1)
        self.assertIn(self.africa, subscription.regions.all())

    def test_subscription_persists_across_sessions(self):
        """Test that subscription settings persist across login sessions"""
        self.client.login(username='testuser', password='testpass123')

        # Create subscription
        self.client.post(
            reverse('optimap:addsubscriptions'),
            {'regions': [self.africa.id, self.pacific.id]}
        )

        # Logout and login again
        self.client.logout()
        self.client.login(username='testuser', password='testpass123')

        # Verify subscription still exists
        response = self.client.get(reverse('optimap:subscriptions'))
        self.assertContains(response, 'Currently monitoring')
        self.assertContains(response, '2 region')

    def test_different_users_have_separate_subscriptions(self):
        """Test that subscriptions are user-specific"""
        # Create second user
        user2 = User.objects.create_user(
            username="testuser2",
            email="test2@example.com",
            password="testpass123"
        )

        # User 1 subscribes to Africa
        self.client.login(username='testuser', password='testpass123')
        self.client.post(
            reverse('optimap:addsubscriptions'),
            {'regions': [self.africa.id]}
        )
        self.client.logout()

        # User 2 subscribes to Asia
        self.client.login(username='testuser2', password='testpass123')
        self.client.post(
            reverse('optimap:addsubscriptions'),
            {'regions': [self.asia.id]}
        )

        # Verify subscriptions are separate
        sub1 = Subscription.objects.get(user=self.user)
        sub2 = Subscription.objects.get(user=user2)

        self.assertEqual(sub1.regions.count(), 1)
        self.assertEqual(sub2.regions.count(), 1)
        self.assertIn(self.africa, sub1.regions.all())
        self.assertIn(self.asia, sub2.regions.all())
        self.assertNotIn(self.asia, sub1.regions.all())
        self.assertNotIn(self.africa, sub2.regions.all())

    def test_post_without_regions_parameter(self):
        """Test POST request without regions parameter clears subscription"""
        self.client.login(username='testuser', password='testpass123')

        # Create subscription with regions
        self.client.post(
            reverse('optimap:addsubscriptions'),
            {'regions': [self.africa.id]}
        )

        # POST without regions parameter (simulates unchecking all)
        response = self.client.post(reverse('optimap:addsubscriptions'), {})

        self.assertEqual(response.status_code, 302)

        # Verify regions were cleared
        subscription = Subscription.objects.get(user=self.user)
        self.assertEqual(subscription.regions.count(), 0)

    def test_subscription_success_message(self):
        """Test that success message is shown after updating subscription"""
        self.client.login(username='testuser', password='testpass123')

        response = self.client.post(
            reverse('optimap:addsubscriptions'),
            {'regions': [self.africa.id, self.asia.id]},
            follow=True  # Follow redirect to see messages
        )

        # Check for success message
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertIn('2 regions', str(messages[0]))
        self.assertIn('updated', str(messages[0]).lower())


class SubscriptionQueryTests(TestCase):
    """Tests for querying publications by subscribed regions"""

    def setUp(self):
        """Set up test data for query tests"""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )

        # Create test regions
        test_polygon = Polygon(((0, 0), (0, 1), (1, 1), (1, 0), (0, 0)))
        test_multipolygon = MultiPolygon(test_polygon)

        self.africa = GlobalRegion.objects.create(
            name="Africa",
            region_type=GlobalRegion.CONTINENT,
            source_url="https://example.com/africa",
            license="CC0",
            geom=test_multipolygon
        )

    def test_subscription_model_string_representation(self):
        """Test the __str__ method of Subscription model"""
        subscription = Subscription.objects.create(
            user=self.user,
            name="test_subscription"
        )

        expected = f"{self.user.username} - test_subscription"
        self.assertEqual(str(subscription), expected)

    def test_subscription_regions_relationship(self):
        """Test the many-to-many relationship between Subscription and GlobalRegion"""
        subscription = Subscription.objects.create(
            user=self.user,
            name="test_subscription"
        )

        # Test adding regions
        subscription.regions.add(self.africa)
        self.assertEqual(subscription.regions.count(), 1)

        # Test reverse relationship
        self.assertEqual(self.africa.subscriptions.count(), 1)
        self.assertIn(subscription, self.africa.subscriptions.all())
