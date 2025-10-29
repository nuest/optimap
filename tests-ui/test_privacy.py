import unittest
from django.test import TestCase
from django.urls import reverse  
from helium import start_chrome,click,get_driver,kill_browser
import os

class PrivacypageTests(TestCase):
    def test_privacy_link(self):
        start_chrome('localhost:8000/', headless=True)
        click("privacy")    
        get_driver().save_screenshot(os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'privacy.png'))
        kill_browser()

    def test_url_exists_at_correct_location(self):
        response = self.client.get("/privacy/")
        self.assertEqual(response.status_code, 200)

    def test_url_available_by_name(self):  
        response = self.client.get(reverse("optimap:privacy"))
        self.assertEqual(response.status_code, 200)

    def test_template_name_correct(self):  
        response = self.client.get(reverse("optimap:privacy"))
        self.assertTemplateUsed(response, "privacy.html")

    def test_template_content(self):
        response = self.client.get(reverse("optimap:privacy"))
        self.assertContains(response, "Privacy policy")

