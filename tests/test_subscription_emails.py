import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
django.setup()

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import MultiPolygon, Polygon, Point, GeometryCollection
from works.models import Subscription, GlobalRegion, Work, Source, EmailLog
from works.tasks import send_subscription_based_email
from unittest.mock import patch
from django.conf import settings

User = get_user_model()


class SubscriptionEmailTests(TestCase):
    """Tests for regional subscription email notifications"""

    def setUp(self):
        """Set up test data"""
        # Create test user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )

        # Create test source
        self.source = Source.objects.create(
            name="Test Journal",
            url_field="https://example.com/test",
            issn_l="1234-5678"
        )

        # Create test regions
        # Africa region (simple polygon around coordinates 0,0 to 10,10)
        africa_polygon = Polygon(((0, 0), (0, 10), (10, 10), (10, 0), (0, 0)))
        self.africa = GlobalRegion.objects.create(
            name="Africa",
            region_type=GlobalRegion.CONTINENT,
            source_url="https://example.com/africa",
            license="CC0",
            geom=MultiPolygon(africa_polygon)
        )

        # Asia region (simple polygon around coordinates 20,20 to 30,30)
        asia_polygon = Polygon(((20, 20), (20, 30), (30, 30), (30, 20), (20, 20)))
        self.asia = GlobalRegion.objects.create(
            name="Asia",
            region_type=GlobalRegion.CONTINENT,
            source_url="https://example.com/asia",
            license="CC0",
            geom=MultiPolygon(asia_polygon)
        )

        # Pacific Ocean region (simple polygon around coordinates 40,40 to 50,50)
        pacific_polygon = Polygon(((40, 40), (40, 50), (50, 50), (50, 40), (40, 40)))
        self.pacific = GlobalRegion.objects.create(
            name="Pacific Ocean",
            region_type=GlobalRegion.OCEAN,
            source_url="https://example.com/pacific",
            license="CC0",
            geom=MultiPolygon(pacific_polygon)
        )

        # Create test publications in different regions
        # Publication in Africa
        africa_point = Point(5, 5)
        self.pub_africa = Work.objects.create(
            title="African Study on Climate Change",
            doi="10.1234/africa.2024",
            status="p",  # Published
            source=self.source,
            geometry=GeometryCollection(africa_point)
        )

        # Publication in Asia
        asia_point = Point(25, 25)
        self.pub_asia = Work.objects.create(
            title="Asian Biodiversity Research",
            doi="10.1234/asia.2024",
            status="p",  # Published
            source=self.source,
            geometry=GeometryCollection(asia_point)
        )

        # Publication in Pacific Ocean
        pacific_point = Point(45, 45)
        self.pub_pacific = Work.objects.create(
            title="Pacific Ocean Current Patterns",
            doi="10.1234/pacific.2024",
            status="p",  # Published
            source=self.source,
            geometry=GeometryCollection(pacific_point)
        )

    def test_globalregion_get_slug(self):
        """Test that GlobalRegion generates correct slugs"""
        self.assertEqual(self.africa.get_slug(), "africa")
        self.assertEqual(self.pacific.get_slug(), "pacific-ocean")

    def test_globalregion_get_absolute_url(self):
        """Test that GlobalRegion generates correct URLs"""
        africa_url = self.africa.get_absolute_url()
        self.assertIn('/feeds/continent/africa/', africa_url)

        pacific_url = self.pacific.get_absolute_url()
        self.assertIn('/feeds/ocean/pacific-ocean/', pacific_url)

    def test_globalregion_str_representation(self):
        """Test the __str__ method of GlobalRegion"""
        self.assertEqual(str(self.africa), "Africa (Continent)")
        self.assertEqual(str(self.pacific), "Pacific Ocean (Ocean)")

    @patch('works.tasks.EmailMessage')
    def test_email_sent_for_subscribed_regions(self, mock_email):
        """Test that emails are sent when publications match subscribed regions"""
        # Create subscription for Africa
        subscription = Subscription.objects.create(
            user=self.user,
            name="test_subscription",
            subscribed=True
        )
        subscription.regions.add(self.africa)

        # Send emails
        send_subscription_based_email(trigger_source='test')

        # Verify email was sent
        self.assertTrue(mock_email.called)
        call_args = mock_email.call_args

        # Check subject
        subject = call_args[0][0]
        self.assertIn("New Publications", subject)

        # Check content includes region name and publication
        content = call_args[0][1]
        self.assertIn("Africa", content)
        self.assertIn("African Study on Climate Change", content)

    @patch('works.tasks.EmailMessage')
    def test_email_grouped_by_region(self, mock_email):
        """Test that email content groups publications by region"""
        # Create subscription for multiple regions
        subscription = Subscription.objects.create(
            user=self.user,
            name="multi_region_subscription",
            subscribed=True
        )
        subscription.regions.add(self.africa, self.asia)

        # Send emails
        send_subscription_based_email(trigger_source='test')

        # Verify email structure
        self.assertTrue(mock_email.called)
        content = mock_email.call_args[0][1]

        # Check that both regions appear
        self.assertIn("Africa", content)
        self.assertIn("Asia", content)

        # Check that publications are grouped correctly
        self.assertIn("African Study on Climate Change", content)
        self.assertIn("Asian Biodiversity Research", content)

        # Pacific publication should NOT be included
        self.assertNotIn("Pacific Ocean Current Patterns", content)

    @patch('works.tasks.EmailMessage')
    def test_email_includes_region_landing_page_links(self, mock_email):
        """Test that email includes links to region landing pages"""
        subscription = Subscription.objects.create(
            user=self.user,
            name="test_subscription",
            subscribed=True
        )
        subscription.regions.add(self.africa)

        send_subscription_based_email(trigger_source='test')

        content = mock_email.call_args[0][1]

        # Check for region landing page link
        self.assertIn("View all publications in this region", content)
        self.assertIn("/feeds/continent/africa/", content)

    @patch('works.tasks.EmailMessage')
    def test_no_email_sent_when_no_publications(self, mock_email):
        """Test that no email is sent when there are no matching publications"""
        # Create subscription for Pacific (which has a publication)
        subscription = Subscription.objects.create(
            user=self.user,
            name="test_subscription",
            subscribed=True
        )
        subscription.regions.add(self.pacific)

        # Delete the Pacific publication
        self.pub_pacific.delete()

        # Send emails
        send_subscription_based_email(trigger_source='test')

        # Verify no email was sent
        self.assertFalse(mock_email.called)

    @patch('works.tasks.EmailMessage')
    def test_no_email_sent_when_no_regions_selected(self, mock_email):
        """Test that no email is sent when user has no regions selected"""
        # Create subscription without regions
        Subscription.objects.create(
            user=self.user,
            name="empty_subscription",
            subscribed=True
        )

        # Send emails
        send_subscription_based_email(trigger_source='test')

        # Verify no email was sent
        self.assertFalse(mock_email.called)

    @patch('works.tasks.EmailMessage')
    def test_email_includes_manage_subscriptions_link(self, mock_email):
        """Test that email includes link to manage subscriptions"""
        subscription = Subscription.objects.create(
            user=self.user,
            name="test_subscription",
            subscribed=True
        )
        subscription.regions.add(self.africa)

        send_subscription_based_email(trigger_source='test')

        content = mock_email.call_args[0][1]

        # Check for management links
        self.assertIn("Manage your regional subscriptions", content)
        self.assertIn("/subscriptions", content)
        self.assertIn("Unsubscribe from all notifications", content)

    @patch('works.tasks.EmailMessage')
    def test_email_shows_correct_publication_count(self, mock_email):
        """Test that email shows correct count of publications per region"""
        # Add a second publication to Africa
        africa_point2 = Point(7, 7)
        Work.objects.create(
            title="Another African Study",
            doi="10.1234/africa2.2024",
            status="p",
            source=self.source,
            geometry=GeometryCollection(africa_point2)
        )

        subscription = Subscription.objects.create(
            user=self.user,
            name="test_subscription",
            subscribed=True
        )
        subscription.regions.add(self.africa)

        send_subscription_based_email(trigger_source='test')

        content = mock_email.call_args[0][1]

        # Check count in subject
        subject = mock_email.call_args[0][0]
        self.assertIn("2 New Publications", subject)

        # Check count per region
        self.assertIn("Africa (Continent) - 2 work(s)", content)

    @patch('works.tasks.EmailMessage')
    def test_only_published_works_included(self, mock_email):
        """Test that only published works are included in notifications"""
        # Create a draft publication in Africa
        africa_point_draft = Point(6, 6)
        Work.objects.create(
            title="Draft African Study",
            doi="10.1234/africa_draft.2024",
            status="d",  # Draft
            source=self.source,
            geometry=GeometryCollection(africa_point_draft)
        )

        subscription = Subscription.objects.create(
            user=self.user,
            name="test_subscription",
            subscribed=True
        )
        subscription.regions.add(self.africa)

        send_subscription_based_email(trigger_source='test')

        content = mock_email.call_args[0][1]

        # Draft publication should not be included
        self.assertNotIn("Draft African Study", content)
        # Only the published one
        self.assertIn("African Study on Climate Change", content)

    @patch('works.tasks.EmailMessage')
    def test_email_limits_publications_per_region(self, mock_email):
        """Test that email limits the number of publications shown per region"""
        # Create 15 publications in Africa (more than the 10 per region limit)
        for i in range(15):
            point = Point(5 + i * 0.1, 5 + i * 0.1)
            Work.objects.create(
                title=f"African Study {i+2}",
                doi=f"10.1234/africa{i+2}.2024",
                status="p",
                source=self.source,
                geometry=GeometryCollection(point)
            )

        subscription = Subscription.objects.create(
            user=self.user,
            name="test_subscription",
            subscribed=True
        )
        subscription.regions.add(self.africa)

        send_subscription_based_email(trigger_source='test')

        content = mock_email.call_args[0][1]

        # Should mention "and X more"
        self.assertIn("and", content)
        self.assertIn("more in Africa", content)

    def test_email_log_created_on_success(self):
        """Test that EmailLog entry is created when email is sent successfully"""
        subscription = Subscription.objects.create(
            user=self.user,
            name="test_subscription",
            subscribed=True
        )
        subscription.regions.add(self.africa)

        with patch('works.tasks.EmailMessage') as mock_email:
            mock_instance = mock_email.return_value
            mock_instance.send.return_value = None

            send_subscription_based_email(trigger_source='test')

            # Check EmailLog was created
            log_entry = EmailLog.objects.filter(recipient_email=self.user.email).first()
            self.assertIsNotNone(log_entry)
            self.assertEqual(log_entry.status, "success")
