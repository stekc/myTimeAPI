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

class Schedule(BaseModel):
    date: str
    shifts: list
    store_info: Optional[dict] = None

@app.get("/schedule")
async def get_schedule(auth_key: str = Depends(get_auth_key)):
    try:
        logger.info("Starting schedule fetch")
        config = configparser.ConfigParser()
        store_info = functions.Store()
        config.read("config.cfg")
        headers = {"Authorization": config["DEFAULT"]["Bearer"]}

        # Test token and get new one if needed
        if functions.test_token(headers).status_code == 401:
            logger.warning("Token invalid. Generating new token...")
            new_token = get_bearer.get_token()
            headers = {"Authorization": new_token}
            
            if functions.test_token(headers).status_code == 400:
                config["DEFAULT"]["Bearer"] = new_token
                with open("config.cfg", "w") as configfile:
                    config.write(configfile)
            else:
                raise HTTPException(status_code=401, detail="Authentication failed")

        # Set up date range
        start_week_obj = datetime.datetime.now()
        start_week_obj -= datetime.timedelta(start_week_obj.weekday() + 1)
        end_week_obj = start_week_obj + datetime.timedelta(6)

        schedule_data = []

        # Get 4 weeks of schedules
        for i in range(4):
            if i > 0:
                start_week_obj += datetime.timedelta(7)
                end_week_obj += datetime.timedelta(7)

            call = functions.call_wfm(headers, start_week_obj.date(), end_week_obj.date())
            
            if call.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to fetch schedule from API")

            call_json = call.json()
            
            # Process each day's schedule
            for day in call_json["schedules"]:
                schedule_entry = Schedule(
                    date=day["schedule_date"],
                    shifts=[],
                    store_info=None
                )

                if day["total_display_segments"] > 0:
                    for segment in day["display_segments"]:
                        shift_location = segment["location"]
                        
                        if store_info.store_id != shift_location:
                            store_info = functions.get_store_info(shift_location)
                            
                        shift = {
                            "start_time": segment["segment_start"],
                            "end_time": segment["segment_end"],
                            "job_name": segment["job_name"],
                            "total_jobs": segment["total_jobs"],
                            "location": shift_location
                        }
                        
                        schedule_entry.shifts.append(shift)
                        schedule_entry.store_info = {
                            "address": store_info.address,
                            "timezone_offset": store_info.timezone_offset,
                            "store_id": store_info.store_id
                        }

                schedule_data.append(schedule_entry.dict())

        return {"schedule": schedule_data}

    except Exception as e:
        logger.error(f"Error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/next_shift")
async def get_next_shift(auth_key: str = Depends(get_auth_key)):
    try:
        logger.info("Starting next shift fetch")
        config = configparser.ConfigParser()
        store_info = functions.Store()
        config.read("config.cfg")
        headers = {"Authorization": config["DEFAULT"]["Bearer"]}

        # Test token and get new one if needed
        if functions.test_token(headers).status_code == 401:
            logger.warning("Token invalid. Generating new token...")
            new_token = get_bearer.get_token()
            headers = {"Authorization": new_token}
            
            if functions.test_token(headers).status_code == 400:
                config["DEFAULT"]["Bearer"] = new_token
                with open("config.cfg", "w") as configfile:
                    config.write(configfile)
            else:
                raise HTTPException(status_code=401, detail="Authentication failed")

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
        config = configparser.ConfigParser()
        store_info = functions.Store()
        config.read("config.cfg")
        headers = {"Authorization": config["DEFAULT"]["Bearer"]}

        # Test token and get new one if needed
        if functions.test_token(headers).status_code == 401:
            logger.warning("Token invalid. Generating new token...")
            new_token = get_bearer.get_token()
            headers = {"Authorization": new_token}
            
            if functions.test_token(headers).status_code == 400:
                config["DEFAULT"]["Bearer"] = new_token
                with open("config.cfg", "w") as configfile:
                    config.write(configfile)
            else:
                raise HTTPException(status_code=401, detail="Authentication failed")

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 