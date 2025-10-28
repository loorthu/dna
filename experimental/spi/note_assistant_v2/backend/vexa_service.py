from fastapi import APIRouter, HTTPException, Request
from vexa_client import VexaClient
import os

router = APIRouter(prefix="/vexa", tags=["vexa"])

API_KEY = os.getenv("VEXA_API_KEY")
ADMIN_KEY = os.getenv("VEXA_ADMIN_KEY")
BASE_URL = os.getenv("VEXA_BASE_URL", "http://localhost:18056")
client = VexaClient(base_url=BASE_URL, api_key=API_KEY, admin_key=ADMIN_KEY)

@router.get("/bots/status")
async def get_bots_status():
    try:
        bots = client.get_running_bots_status()
        return bots
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/bots")
async def post_bot(request: Request):
    data = await request.json()
    print("Received bot request data:", data)
    print("client config:", client)
    try:
        bot = client.request_bot(
            platform=data.get("platform"),
            native_meeting_id=data.get("native_meeting_id"),
            bot_name=data.get("bot_name"),
            language=data.get("language"),
            task=data.get("task")
        )
        return bot
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/bots/{platform}/{native_meeting_id}")
async def delete_bot_route(platform: str, native_meeting_id: str):
    try:
        result = client.stop_bot(platform, native_meeting_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
