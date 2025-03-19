from unittest import TestCase
import os
from helium import *
import time

class LoginresponseTest(TestCase):
    start_chrome('localhost:8000/')  
    click(Button("signup"))
    write('dev@example.com', into='email')
    get_driver().save_screenshot(os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'Loginmailid.png'))
    click("Login")
    # time to allow loading
    time.sleep(2)
    get_driver().save_screenshot(os.path.join(os.getcwd(), 'tests-ui', 'screenshots', 'Loginresponse.png'))
    if Text("Awesome!").exists():
        click(Button("×"))
    kill_browser()
