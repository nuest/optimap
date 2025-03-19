from unittest import TestCase
import os
from helium import start_chrome,get_driver,kill_browser

class MainpageTest(TestCase):
    
    start_chrome('localhost:8000/')  
    get_driver().save_screenshot(os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'UserMenu.png'))
    kill_browser()
