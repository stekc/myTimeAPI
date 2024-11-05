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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 