import pyotp

# Global Variables
EMPLOYEE_ID = 00000000
PASSWORD = "myPassword"
STORE_NUMBER = 1375
# This is just used as a reference for calling available shifts.
API_KEY = "eb2551e4accc14f38cc42d32fbc2b2ea"
# you can change this but the default one should work
PUSHOVER_APP_API_KEY = ""
PUSHOVER_USER_API_KEY = ""
AUTH_KEY = "password"
# This is the key that will be used to authenticate the API requests

# If you don't want this script to scan for posted shifts
run_posted_shifts = True
# When obtaining the token, headless means it will run in the background, otherwise it'll be visible to the user
headless = True
totp = pyotp.TOTP("")
# MFA code here.

get_schedule_headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Upgrade-Insecure-Requests": "1",
    "DNT": "1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
}


def get_mfa_code():
    return totp.now()
