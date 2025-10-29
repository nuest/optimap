from unittest import TestCase
import os
from helium import *

class UsermenuTest(TestCase):
    def test_user_menu_dropdown(self):
        """Test user menu dropdown navigation."""
        start_chrome('localhost:8000/', headless=True)
        try:
            click(S("#navbarDarkDropdown"))
            get_driver().save_screenshot(os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'UserMenu.png'))
        finally:
            kill_browser()
