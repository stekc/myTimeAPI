import os
import requests
import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import engine, SeenShift

from loguru import logger

import config_file
from cache import Cache

logger.info("Changing cwd to file path")
os.chdir(os.path.dirname(__file__))

creds = None
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Add store cache
_store_cache = {}
# Add API response caches with 5 minute TTL
_wfm_cache = Cache(ttl_seconds=300)
_available_shifts_cache = Cache(ttl_seconds=300)


class Store:
    def __init__(self):
        self.address = ""
        self.timezone_offset = "00:00:00"
        self.store_id = "0000"


def notify_user(message):
    if config_file.PUSHOVER_APP_API_KEY == "" or config_file.PUSHOVER_USER_API_KEY == "":
        logger.info("Config file for pushover is empty, ignoring")
        return
    logger.info("Notifying User via Pushover...")
    r = requests.post(
        "https://api.pushover.net/1/messages.json",
        data={
            "token": config_file.PUSHOVER_APP_API_KEY,
            "user": config_file.PUSHOVER_USER_API_KEY,
            "message": message,
        },
    )
    # try to notify the user, if it fails then log
    try:
        r.raise_for_status()
        logger.success("User Notified")
    except:
        logger.error(f"Notifying FAILED {r.text}")


def check_cfg_file():
    # This function will ensure that there is a configuration file, and if there isn't then it will generate one.
    # This file will only be used to hold the bearer token
    logger.info("Checking configuration file...")
    cwd = os.getcwd()
    # Get Current working directory
    config_path = os.path.join(cwd, "config.cfg")
    # Create path
    if not os.path.isfile(config_path):
        # Poke file to see if it exists.
        logger.warning("Config file does not exist! Generating new...")
        f = open("config.cfg", "a")
        f.write(
            """[DEFAULT]
    Bearer = """
        )
        f.close()
        # generate config file
        logger.success("Config File Generated")
    else:
        logger.info("Config File already exists")


def get_current_timezone_offset():
    # Get the host's timezone offset
    current_time = datetime.datetime.now()
    current_timezone = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo
    utc_offset = current_timezone.utcoffset(current_time).total_seconds() / 3600
    offset = int(utc_offset)
    # Simple logic to sort timezones to make google calendar happy.
    if offset == 0:
        offset = "-00:00"
    elif offset <= -10:
        offset = f"{offset}:00"
    elif offset < 0:
        offset = f"-0{offset * -1}:00"
    else:
        offset = f"-0{offset}:00"

    return offset


def get_store_info(store_id):
    # Check cache first
    if store_id in _store_cache:
        logger.success(f"Cache hit for store info {store_id}")
        return _store_cache[store_id]
        
    logger.warning(f"Cache miss for store info {store_id}, fetching from API")
    # Get store address and TimeZone offset
    r = requests.get(
        "https://redsky.target.com/redsky_aggregations/v1/web/store_location_v1"
        f"?store_id={store_id}"
        f"&key={config_file.API_KEY}",
        headers=config_file.get_schedule_headers,
    )
    s = Store()
    # Initialize store object

    store_json = r.json()["data"]["store"]["mailing_address"]
    # create object to reduce lines of code.
    s.address = (
        f"{store_json['address_line1']} {store_json['city']}, "
        f"{store_json['region']}, {store_json['postal_code']}"
    )
    s.timezone_offset = get_current_timezone_offset()
    s.store_id = store_id
    
    # Cache the store info
    _store_cache[store_id] = s
    return s


def call_wfm(
    hdr,
    start_date,
    end_date,
):
    # Function to call and retrieve schedule.
    # Start Date and end date format should be YYYY-MM-DD
    cache_key = f"wfm_{start_date}_{end_date}"
    
    # Check cache first
    cached_response = _wfm_cache.get(cache_key)
    if cached_response is not None:
        logger.success(f"Cache hit for WFM data {cache_key}")
        return cached_response

    logger.warning(f"Cache miss for WFM data {cache_key}, fetching from API")
    r = requests.get(
        f"https://api.target.com/wfm_schedules/v1/weekly_schedules?"
        f"team_member_number=00{config_file.EMPLOYEE_ID}"
        f"&start_date={start_date}"
        f"&end_date={end_date}"
        f"&location_id="  # Needs this flag for some reason.
        f"&key={config_file.API_KEY}",
        headers=hdr,
    )
    
    # Cache the response if successful
    if r.status_code == 200:
        _wfm_cache.set(cache_key, r)
        
    return r


def call_available_shifts(
    hdr,
    start_date,
    end_date,
):
    cache_key = f"available_shifts_{start_date}_{end_date}"
    
    # Check cache first
    cached_response = _available_shifts_cache.get(cache_key)
    if cached_response is not None:
        logger.success(f"Cache hit for available shifts {cache_key}")
        return cached_response

    logger.warning(f"Cache miss for available shifts {cache_key}, fetching from API")
    r = requests.get(
        f"https://api.target.com/wfm_available_shifts/v1/available_shifts?"
        f"worker_id={config_file.EMPLOYEE_ID}"
        f"&start_date={start_date}"
        f"&end_date={end_date}"
        f"&location_ids={config_file.STORE_NUMBER}"  # Needs this flag for some reason.
        f"&key={config_file.API_KEY}",
        headers=hdr,
    )

    # Cache the response if successful
    if r.status_code == 200:
        _available_shifts_cache.set(cache_key, r)

    return r


def test_token(test_header):
    # Function to test if Bearer token is valid
    test_request = requests.get(
        f"https://api.target.com/wfm_schedules/v1/weekly_schedules?"
        f"team_member_number=00{config_file.EMPLOYEE_ID}"
        "&start_date=2020-06-23"
        "&end_date=2020-06-29"  # any date should work here, we're just making sure the key is valid
        "&location_id="  # Needs this flag for some reason.
        f"&key={config_file.API_KEY}",
        headers=test_header,
    )
    return test_request


def seen_or_record(shift):
    with Session(engine) as session:
        logger.info(f"Checking if shift {shift['available_shift_id']} exists")
        result = session.scalar(
            select(SeenShift).filter(SeenShift.id == shift["available_shift_id"])
        )

        if result:
            logger.info("Shift found, exiting function")
            return
        logger.info("Shift not found, adding to database")
        new_shift = SeenShift(id=shift["available_shift_id"])
        session.add(new_shift)
        session.commit()

        dt_start = datetime.datetime.fromisoformat(shift["shift_start"])
        dt_end = datetime.datetime.fromisoformat(shift["shift_end"])

        notify_user(
            f"A new {shift['shift_hours']} hour shift has been posted for {dt_start.date()} "
            f"from {dt_start.strftime('%I:%M %p')} "
            f"to {dt_end.strftime('%I:%M %p')} for "
            f"{shift['org_structure']['job']}"
        )
