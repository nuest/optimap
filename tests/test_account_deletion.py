import os
import django
import subprocess
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "optimap.settings")
django.setup()
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
import uuid
User = get_user_model()

class AccountDeletionTests(TestCase):
    def setUp(self):
        """Set up a test user and client"""
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="password")
        self.client.login(username="testuser", password="password")
        self.delete_token = uuid.uuid4().hex
        cache.set(f"user_delete_token_{self.delete_token}", self.user.id, timeout=600)

    def test_request_delete_account(self):
        """Test that a user can request account deletion"""
        response = self.client.post(reverse("optimap:request_delete"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("message=Check%20your%20email", response.url)

    def test_confirm_delete_account(self):
        """Test that a user can confirm account deletion"""
        response = self.client.get(reverse("optimap:confirm_delete", args=[self.delete_token]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get("user_delete_token"))

    def test_finalize_delete_account(self):
        """Test that a user can finalize account deletion"""
        session = self.client.session
        session["user_delete_token"] = self.delete_token 
        session.save() 

        # Send delete request
        response = self.client.post(reverse("optimap:finalize_delete"))

        # Fetch user from DB again
        user = User.objects.filter(id=self.user.id).first()

        self.assertEqual(response.status_code, 302) 

        if user:  
            self.assertTrue(user.deleted)  
        else: 
            self.assertIsNone(user)

    def test_invalid_token(self):
        """Test invalid or expired deletion token"""
        response = self.client.get(reverse("optimap:confirm_delete", args=["invalidtoken"]))
        messages_list = list(response.wsgi_request._messages)     
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("Invalid or expired deletion token" in str(m) for m in messages_list))

    def test_logout_and_click_delete_link(self):
        """Test scenario where user logs out and clicks deletion link"""
        self.client.logout()
        response = self.client.get(reverse("optimap:confirm_delete", args=[self.delete_token]))
        expected_redirect = reverse("optimap:main")
        self.assertTrue(response.url.startswith(expected_redirect))
