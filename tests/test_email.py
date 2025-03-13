import django
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings") 
django.setup()

from django.test import TestCase, override_settings
from django.core import mail
from publications.tasks import send_monthly_email
from publications.models import EmailLog, Publication, UserProfile
from django.utils.timezone import now
from django.contrib.auth.models import User
from datetime import timedelta
from datetime import datetime
from django.contrib.gis.geos import Point, LineString, Polygon, GeometryCollection

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailIntegrationTest(TestCase):
    def setUp(self):
        """Setup test data before each test"""
        Publication.objects.all().delete()
        EmailLog.objects.all().delete()
        User.objects.all().delete()
        
        self.user = User.objects.create_user(username="testuser1", email="test@example.com", password="testpass")
        self.user_profile = UserProfile.objects.get(user=self.user)

        self.user_profile.notify_new_manuscripts = True
        self.user_profile.save()

    def test_send_monthly_email_with_publications(self):
        """Test if the monthly email is sent when publications exist"""

        last_month = now().replace(day=1) - timedelta(days=1)  
        publication = Publication.objects.create(
            title="Point Test",
            abstract="Publication with a single point inside a collection.",
            url="https://example.com/point",
            status="p",
            publicationDate=last_month,
            doi="10.1234/test-doi-1",
            geometry=GeometryCollection(Point(12.4924, 41.8902)),
        )

        Publication.objects.filter(id=publication.id).update(creationDate=last_month)

        publication.refresh_from_db()
 
        self.assertEqual(len(mail.outbox), 0)

        send_monthly_email(sent_by=self.user)

        self.assertEqual(len(mail.outbox), 1)

        sent_email = mail.outbox[0]

        self.assertIn(publication.title, sent_email.body)

        self.assertEqual(sent_email.to, ["test@example.com"])

        email_log = EmailLog.objects.latest('sent_at')  
        self.assertEqual(email_log.recipient_email, "test@example.com")
        self.assertEqual(email_log.sent_by, self.user)


    def test_send_monthly_email_without_publications(self):
        """Test that no email is sent when no new publications exist"""

        self.assertEqual(len(mail.outbox), 0)

        send_monthly_email(sent_by=self.user)

        self.assertEqual(len(mail.outbox), 0)

        self.assertFalse(EmailLog.objects.exists())



