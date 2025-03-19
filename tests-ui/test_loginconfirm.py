from unittest import TestCase
import os
from helium import start_chrome,get_driver,click,Text,Button,kill_browser

class LoginconfirmationTest(TestCase):
    
    start_chrome('localhost:8000/loginconfirm/')  
    get_driver().save_screenshot(os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'UserMenu.png'))
    if Text("Welcome to OPTIMAP!").exists():
        click(Button("×"))
    kill_browser()
    