import datetime
import functions
import get_bearer
import configparser
from loguru import logger

def get_posted_shifts():
    logger.info("Starting get_posted_shifts function.")
    logger.info("Reading Configuration file. ")
    config = configparser.ConfigParser()
    logger.info("Setting up store info object")
    store_info = functions.Store()
    config.read("config.cfg")
    test_headers = {"Authorization": config["DEFAULT"]["Bearer"]}
    posted_shift_headers = {
        "Authorization": config["DEFAULT"]["Bearer"],
        "Page-Origin": "AVAILABLE_SHIFTS",
    }
    logger.info("Testing previously used token.")
    # test the token.
    if functions.test_token(test_headers).status_code == 401:
        # 401 means that response was invalid
        logger.warning("Token invalid. Generating new token...")
        # get new token
        new_token = get_bearer.get_token()
        logger.success("New Token obtained. Testing new token...")
        # set new header and test new token
        headers = {
            "Authorization": new_token,
        }
        if functions.test_token(headers).status_code == 400:
            # This may seem weird at first, but we're just checking if it authenticated properly, not the actual API
            logger.success("New Token valid! Updating configuration file...")
            config["DEFAULT"]["Bearer"] = new_token
            # Update the new config file.
            with open("config.cfg", "w") as configfile:
                config.write(configfile)
        else:
            logger.error(
                f"ERROR! New Token Invalid! error {functions.test_token(headers).status_code}"
            )
            logger.error("New Token invalid! Exiting...")
            exit(-1)

    logger.success("Existing Token valid!")
    # Now everything is verified and is working properly, we can start to work+

    logger.info("Starting API calls for available shifts.")

    start_week_obj = datetime.datetime.now()
    start_week_obj -= datetime.timedelta(start_week_obj.weekday() + 1)
    end_week_obj = start_week_obj + datetime.timedelta(6)
    # These date time objects allow us to easily move between calendar dates

    for i in range(4):
        # 4 to check 4 weeks of data
        if i > 0:
            start_week_obj += datetime.timedelta(7)
            end_week_obj += datetime.timedelta(7)
        logger.info("Calling available shifts API")
        call = functions.call_available_shifts(
            posted_shift_headers, start_week_obj.date(), end_week_obj.date()
        )
        call_json = call.json()
        # call and check the results
        if call.status_code != 200:
            logger.error("Crap. API returned error exiting safely")
            exit(-2)
        logger.success("Call Returned 200!")

        if not len(call_json["available_shifts"]):
            logger.info("No available shifts found.")
            continue
        logger.success(f"Shifts found!")

        for shift in call_json["available_shifts"]:
            functions.seen_or_record(shift)
