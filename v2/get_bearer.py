def get_token():
    import json
    import time
    import config_file
    from loguru import logger
    import undetected_chromedriver as uc
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.chrome.service import Service

    logger.info("Setting up Chrome Options")
    # Chrome Options
    options = uc.ChromeOptions()
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    options.add_experimental_option("perfLoggingPrefs", {"enableNetwork": True})
    service = Service()
    options.add_argument("--incognito")
    options.headless = config_file.headless
    # NEEDED FOR HEADLESS
    options.add_argument("--enable-automation")
    # Needed for Linux VM Headless
    options.add_argument("--disable-gpu")
    # Needed for Linux VM.
    options.add_argument("--disable-software-rasterizer")

    # options.add_argument("--no-sandbox")
    # options.add_argument("--disable-dev-shm-usage")
    # options.add_argument("--incognito")
    # options.add_argument("--disable-extensions")
    # options.add_argument("--disable-browser-side-navigation")
    # options.add_argument("--disable-web-security")
    # options.add_argument("--disable-dev-shm-usage")
    # options.add_argument("--disable-infobars")
    # options.add_argument("--disable-setuid-sandbox")


    # logger.success("Arguments setup! Starting ChromeDriver")
    browser = uc.Chrome(use_subprocess=True, options=options, service=service)
    logger.success("ChromeDriver Setup! Starting")

    # navigate to a website
    logger.info("Launching myTime")
    browser.get("http://mytime.target.com")
    try:
        element_present = ec.presence_of_element_located((By.ID, "loginID"))
        WebDriverWait(browser, 10).until(element_present)
        time.sleep(1)
    except TimeoutException:
        print("Timed out waiting for Login Page to load")
        browser.close()

    logger.info("entering username and password...")
    username = browser.find_element(By.ID, "loginID")
    password = browser.find_element(By.ID, "password")
    # This finds the login and the password box
    logger.info("Entering Username")
    username.click()
    username.send_keys(config_file.EMPLOYEE_ID)
    username.send_keys(Keys.TAB)

    logger.info("Entering Password")
    username.click()
    password.send_keys(config_file.PASSWORD)
    password.click()

    logger.info("Pressing Submit")
    login_button = browser.find_element(By.ID, "submit-button")
    login_button.submit()
    time.sleep(2)
    mfa_button = browser.find_element(
        By.XPATH, '//*[contains(text(), "Authenticator")]'
    )
    mfa_button.click()

    try:
        element_present = ec.presence_of_element_located((By.ID, "totp-code"))
        WebDriverWait(browser, 10).until(element_present)
        time.sleep(1)
    except TimeoutException:
        logger.error("Timed out OTP button to load")
        browser.close()

    logger.success("Account Valid! Logging into 2FA")
    otp = browser.find_element(By.ID, "totp-code")
    otp.click()
    otp.send_keys(config_file.get_mfa_code())

    browser.find_element(By.ID, "submit-button").click()
    logger.info("Clicking submit...")
    time.sleep(10)

    logger.success("Logged in successfully! Grabbing Bearer token")
    logs = browser.get_log("performance")
    for entry in logs:
        if "Bearer " in str(entry["message"]):
            json_message_data = json.loads(str(entry["message"]))
            authorization_json = json_message_data["message"]["params"]["request"]["headers"]["Authorization"]
            logger.success("Bearer obtained! Closing...")
            browser.close()
            return authorization_json
