from django.test import TestCase, override_settings
from django.core import mail
from django.conf import settings
from publications.models import Subscription, Publication, EmailLog, UserProfile
from publications.tasks import send_subscription_based_email
from django.contrib.auth import get_user_model
from django.utils.timezone import now
from datetime import timedelta
from django.contrib.gis.geos import Point, GeometryCollection

User = get_user_model()

@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    BASE_URL='http://testserver'
)
class SubscriptionEmailTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="subuser", email="subuser@example.com", password="testpass"
        )
        UserProfile.objects.get_or_create(user=self.user)
        self.subscription = Subscription.objects.create(
            user=self.user,
            name="Test Subscription",
            search_term="AI",
            region=GeometryCollection(Point(12.4924, 41.8902)),
            subscribed=True
        )

    def test_subscription_email_sent_when_publication_matches(self):
        """Email is sent and includes site-local permalink when a pub with DOI matches."""
        pub = Publication.objects.create(
            title="Rome AI Paper",
            abstract="Test abstract",
            url="https://example.com/pub",
            status="p",
            publicationDate=now() - timedelta(days=5),
            doi="10.1234/sub-doi",
            geometry=GeometryCollection(Point(12.4924, 41.8902)),
        )
        send_subscription_based_email(sent_by=self.user)

        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body

        self.assertIn(pub.title, body)
        self.assertIn("Unsubscribe", body)  # casing differs in the template block, keep “U” here

        # Expect site-local permalink (NOT doi.org)
        expected_link = f"{settings.BASE_URL.rstrip('/')}/work/{pub.doi}"
        self.assertIn(expected_link, body)

        # log entry
        log = EmailLog.objects.latest("sent_at")
        self.assertEqual(log.recipient_email, self.user.email)
        self.assertEqual(log.sent_by, self.user)

    def test_subscription_email_fallback_to_url_when_no_doi(self):
        """Falls back to pub.url when DOI is missing."""
        pub = Publication.objects.create(
            title="No DOI Sub Paper",
            abstract="Test abstract",
            url="https://example.com/no-doi-sub",
            status="p",
            publicationDate=now() - timedelta(days=2),
            doi=None,
            geometry=GeometryCollection(Point(12.4924, 41.8902)),
        )
        mail.outbox.clear()

        send_subscription_based_email(sent_by=self.user)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn(pub.title, body)
        self.assertIn(pub.url, body)

    def test_subscription_email_not_sent_if_no_publication_matches(self):
        """No email or log if no pubs intersect the region."""
        Publication.objects.create(
            title="Outside Region Paper",
            abstract="Should not match",
            url="https://example.com/outside",
            status="p",
            publicationDate=now(),
            doi="10.1234/outside-doi",
            geometry=GeometryCollection(Point(0, 0)),
        )

        send_subscription_based_email(sent_by=self.user)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(EmailLog.objects.exists())
