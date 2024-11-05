from cache import Cache
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security.api_key import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN
from fastapi.middleware.cors import CORSMiddleware
import datetime
import functions
import get_bearer
import configparser
from loguru import logger
from typing import Optional
from pydantic import BaseModel
import config_file
from datetime import datetime as dt

app = FastAPI()
schedule_cache = Cache(ttl_seconds=300)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AUTH_NAME = "X-API-Key"
auth_key_header = APIKeyHeader(name=AUTH_NAME, auto_error=False)

async def get_auth_key(auth_key_header: str = Security(auth_key_header)):
    if auth_key_header is None:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN, detail="Could not validate API key"
        )
    
    if auth_key_header != config_file.AUTH_KEY:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN, detail="Could not validate API key"
        )
    return auth_key_header

async def validate_and_refresh_token(headers: dict) -> dict:
    """Validates the current token and refreshes if needed."""
    if functions.test_token(headers).status_code == 401:
        logger.warning("Token invalid. Generating new token...")
        new_token = get_bearer.get_token()
        headers = {"Authorization": new_token}
        
        if functions.test_token(headers).status_code == 400:
            config = configparser.ConfigParser()
            config.read("config.cfg")
            config["DEFAULT"]["Bearer"] = new_token
            with open("config.cfg", "w") as configfile:
                config.write(configfile)
        else:
            raise HTTPException(status_code=401, detail="Authentication failed")
    return headers

def get_week_dates(offset_weeks: int = 0) -> tuple[dt, dt]:
    """Returns start (Sunday) and end (Saturday) dates for a given week offset."""
    start_date = dt.now()
    start_date -= datetime.timedelta(start_date.weekday() + 1)
    start_date += datetime.timedelta(weeks=offset_weeks)
    end_date = start_date + datetime.timedelta(6)
    return start_date, end_date

def format_shift_time(shift_date: dt, start_datetime: dt) -> str:
    """Returns human-readable day text (Today/Tomorrow/Day of week)."""
    if shift_date.date() == dt.now().date():
        return "Today"
    elif shift_date.date() == (dt.now() + datetime.timedelta(1)).date():
        return "Tomorrow"
    return shift_date.strftime("%A")

def calculate_shift_hours(start_datetime: dt, end_datetime: dt) -> float:
    """Calculates shift duration accounting for lunch breaks."""
    duration = end_datetime - start_datetime
    hours = duration.total_seconds() / 3600
    return hours - 0.5 if hours >= 5 else hours

async def get_schedule_data(headers: dict, start_date: dt, end_date: dt) -> dict:
    """Fetches and validates schedule data from the API."""
    cache_key = f"schedule_{start_date.date()}_{end_date.date()}"
    
    # Try to get from cache first
    cached_data = schedule_cache.get(cache_key)
    if cached_data is not None:
        logger.info(f"Cache hit for {cache_key}")
        return cached_data
        
    # If not in cache, fetch from API
    logger.info(f"Cache miss for {cache_key}, fetching from API")
    call = functions.call_wfm(headers, start_date.date(), end_date.date())
    if call.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to fetch schedule from API")
    
    data = call.json()
    schedule_cache.set(cache_key, data)
    return data

async def get_initial_headers() -> dict:
    """Gets initial headers with authorization token."""
    config = configparser.ConfigParser()
    config.read("config.cfg")
    return {"Authorization": config["DEFAULT"]["Bearer"]}

@app.get("/schedule")
async def get_schedule(auth_key: str = Depends(get_auth_key)):
    try:
        logger.info("Starting schedule fetch")
        store_info = functions.Store()
        headers = await get_initial_headers()
        headers = await validate_and_refresh_token(headers)
        schedule_data = []

        # Get 4 weeks of schedules
        for i in range(4):
            start_week_obj, end_week_obj = get_week_dates(i)
            call_json = await get_schedule_data(headers, start_week_obj, end_week_obj)
            
            # Process each day's schedule
            for day in call_json["schedules"]:
                schedule_entry = {
                    "date": day["schedule_date"],
                    "shifts": [],
                    "store_info": None
                }

                if day["total_display_segments"] > 0:
                    for segment in day["display_segments"]:
                        shift_location = segment["location"]
                        
                        if store_info.store_id != shift_location:
                            store_info = functions.get_store_info(shift_location)
                            
                        schedule_entry["shifts"].append({
                            "start_time": segment["segment_start"],
                            "end_time": segment["segment_end"],
                            "job_name": segment["job_name"],
                            "total_jobs": segment["total_jobs"],
                            "location": shift_location
                        })
                        schedule_entry["store_info"] = {
                            "address": store_info.address,
                            "timezone_offset": store_info.timezone_offset,
                            "store_id": store_info.store_id
                        }

                schedule_data.append(schedule_entry)

        return {"schedule": schedule_data}

    except Exception as e:
        logger.error(f"Error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/next_shift")
async def get_next_shift(auth_key: str = Depends(get_auth_key)):
    try:
        logger.info("Starting next shift fetch")
        store_info = functions.Store()
        headers = await get_initial_headers()
        headers = await validate_and_refresh_token(headers)

        # Get current Sunday and next Saturday
        start_date = dt.now()
        start_date -= datetime.timedelta(start_date.weekday() + 1)  # Adjust to previous Sunday
        end_date = start_date + datetime.timedelta(6)  # Get to Saturday

        call = functions.call_wfm(headers, start_date.date(), end_date.date())
        
        if call.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to fetch schedule from API")

        call_json = call.json()
        
        # Find the next shift
        for day in call_json["schedules"]:
            if day["total_display_segments"] > 0:
                for segment in day["display_segments"]:
                    shift_date = dt.strptime(day["schedule_date"], "%Y-%m-%d")
                    # Parse full datetime and extract time
                    start_datetime = dt.strptime(segment["segment_start"], "%Y-%m-%d %H:%M:%S")
                    end_datetime = dt.strptime(segment["segment_end"], "%Y-%m-%d %H:%M:%S")
                    start_time = start_datetime.time()
                    end_time = end_datetime.time()
                    
                    shift_start = dt.combine(shift_date.date(), start_time)
                    
                    if shift_start > dt.now():
                        # Get store info
                        if store_info.store_id != segment["location"]:
                            store_info = functions.get_store_info(segment["location"])
                        
                        # Format the date/time for human readable output
                        if shift_start.date() == dt.now().date():
                            day_text = "Today"
                        elif shift_start.date() == (dt.now() + datetime.timedelta(1)).date():
                            day_text = "Tomorrow"
                        else:
                            day_text = shift_start.strftime("%A")
                        
                        # Format times removing leading zeros
                        start_time_str = start_time.strftime("%I%p").lower().lstrip('0')
                        end_time_str = end_time.strftime("%I%p").lower().lstrip('0')
                        
                        return {
                            "next_shift": {
                                "human_readable": f"{day_text} from {start_time_str} to {end_time_str}",
                                "date": day["schedule_date"],
                                "start_time": start_datetime.strftime("%H:%M"),
                                "end_time": end_datetime.strftime("%H:%M"),
                                "job_name": segment["job_name"],
                                "location": {
                                    "store_id": store_info.store_id,
                                    "address": store_info.address,
                                    "timezone_offset": store_info.timezone_offset
                                }
                            }
                        }
        
        return {"next_shift": None}

    except Exception as e:
        logger.error(f"Error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/summary")
async def get_schedule_summary(auth_key: str = Depends(get_auth_key)):
    try:
        logger.info("Starting schedule summary fetch")
        store_info = functions.Store()
        headers = await get_initial_headers()
        headers = await validate_and_refresh_token(headers)

        # Get current Sunday and next Saturday
        start_date = dt.now()
        start_date -= datetime.timedelta(start_date.weekday() + 1)
        end_date = start_date + datetime.timedelta(6)

        call = functions.call_wfm(headers, start_date.date(), end_date.date())
        
        if call.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to fetch schedule from API")

        call_json = call.json()
        
        upcoming_shifts = 0
        next_shift = None
        total_hours = 0
        
        # Process all shifts
        for day in call_json["schedules"]:
            if day["total_display_segments"] > 0:
                for segment in day["display_segments"]:
                    shift_date = dt.strptime(day["schedule_date"], "%Y-%m-%d")
                    start_datetime = dt.strptime(segment["segment_start"], "%Y-%m-%d %H:%M:%S")
                    end_datetime = dt.strptime(segment["segment_end"], "%Y-%m-%d %H:%M:%S")
                    
                    # Calculate shift duration
                    duration = end_datetime - start_datetime
                    shift_hours = duration.total_seconds() / 3600
                    
                    # Subtract 30 min lunch break for shifts 5 hours or longer
                    if shift_hours >= 5:
                        shift_hours -= 0.5
                    
                    total_hours += shift_hours
                    
                    if start_datetime > dt.now():
                        upcoming_shifts += 1
                        
                        if next_shift is None:
                            # Get store info if needed
                            if store_info.store_id != segment["location"]:
                                store_info = functions.get_store_info(segment["location"])
                            
                            # Format the date/time
                            if shift_date.date() == dt.now().date():
                                day_text = "today"
                            elif shift_date.date() == (dt.now() + datetime.timedelta(1)).date():
                                day_text = "tomorrow"
                            else:
                                day_text = shift_date.strftime("%A").lower()
                            
                            start_time = start_datetime.strftime("%I:%M%p").lower().lstrip('0')
                            end_time = end_datetime.strftime("%I:%M%p").lower().lstrip('0')
                            
                            next_shift = f"{day_text} from {start_time} to {end_time}"

        # Create the summary message
        if upcoming_shifts == 0:
            summary = "You have no upcoming shifts scheduled this week."
        else:
            # Format hours to remove .0 if it's a whole number
            hours_display = int(total_hours) if total_hours.is_integer() else round(total_hours, 1)
            
            if next_shift:
                summary = f"Your next shift is {next_shift}. "
            else:
                summary = ""
            
            summary += f"You have {upcoming_shifts} shift{'s' if upcoming_shifts != 1 else ''} scheduled this week"
            summary += f" for a total of {hours_display} hours."

        return {
            "summary": summary
        }

    except Exception as e:
        logger.error(f"Error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/working_today")
async def working_today(auth_key: str = Depends(get_auth_key)):
    try:
        logger.info("Checking if working today")
        store_info = functions.Store()
        headers = await get_initial_headers()
        headers = await validate_and_refresh_token(headers)

        # Get current Sunday and next Saturday
        start_date = dt.now()
        start_date -= datetime.timedelta(start_date.weekday() + 1)  # Adjust to previous Sunday
        end_date = start_date + datetime.timedelta(6)  # Get to Saturday

        call = functions.call_wfm(headers, start_date.date(), end_date.date())
        
        if call.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to fetch schedule from API")

        call_json = call.json()
        today = dt.now().date()
        
        # Find today's schedule
        for day in call_json["schedules"]:
            if day["schedule_date"] == today.strftime("%Y-%m-%d"):
                return {"working": day["total_display_segments"] > 0}
        
        return {"working": False}

    except Exception as e:
        logger.error(f"Error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/working_tomorrow")
async def working_tomorrow(auth_key: str = Depends(get_auth_key)):
    try:
        logger.info("Checking if working tomorrow")
        store_info = functions.Store()
        headers = await get_initial_headers()
        headers = await validate_and_refresh_token(headers)

        # Get current Sunday and next Saturday
        start_date = dt.now()
        start_date -= datetime.timedelta(start_date.weekday() + 1)  # Adjust to previous Sunday
        end_date = start_date + datetime.timedelta(6)  # Get to Saturday

        call = functions.call_wfm(headers, start_date.date(), end_date.date())
        
        if call.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to fetch schedule from API")

        call_json = call.json()
        tomorrow = (dt.now() + datetime.timedelta(days=1)).date()
        
        # Find tomorrow's schedule
        for day in call_json["schedules"]:
            if day["schedule_date"] == tomorrow.strftime("%Y-%m-%d"):
                return {"working": day["total_display_segments"] > 0}
        
        return {"working": False}

    except Exception as e:
        logger.error(f"Error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/next_day_off")
async def get_next_day_off(auth_key: str = Depends(get_auth_key)):
    """Find the next day you're not scheduled to work"""
    try:
        logger.info("Finding next day off")
        headers = await get_initial_headers()
        headers = await validate_and_refresh_token(headers)
        
        # Get schedules for the next 4 weeks to ensure we find a day off
        working_days = set()
        today = dt.now().date()
        
        # Collect all working days
        for i in range(4):
            start_week_obj, end_week_obj = get_week_dates(i)
            call_json = await get_schedule_data(headers, start_week_obj, end_week_obj)
            
            for day in call_json["schedules"]:
                if day["total_display_segments"] > 0:
                    working_days.add(dt.strptime(day["schedule_date"], "%Y-%m-%d").date())
        
        # Find the next day off
        current_date = today
        while current_date in working_days:
            current_date += datetime.timedelta(days=1)
            
        # Format the response
        days_until = (current_date - today).days
        
        if days_until == 0:
            message = "You are off today!"
        elif days_until == 1:
            message = "Your next day off is tomorrow"
        else:
            day_name = current_date.strftime("%A")
            message = f"Your next day off is {day_name}"
            
            if days_until >= 7:
                message += f" ({days_until} days from now)"
        
        return {
            "next_day_off": {
                "date": current_date.strftime("%Y-%m-%d"),
                "days_until": days_until,
                "message": message,
                "is_today": days_until == 0
            }
        }

    except Exception as e:
        logger.error(f"Error occurred while finding next day off: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/clear_cache")
async def clear_cache(auth_key: str = Depends(get_auth_key)):
    """Clear the schedule cache"""
    try:
        logger.info("Clearing schedule cache")
        schedule_cache.clear()
        return {"message": "Cache cleared successfully"}
    except Exception as e:
        logger.error(f"Error clearing cache: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
