# leLab/app/video.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
import aiofiles, subprocess, uuid, os, pathlib

router = APIRouter()
MEDIA_DIR = pathlib.Path(__file__).parent.parent / "episodes"
MEDIA_DIR.mkdir(exist_ok=True)

async def _write_chunks(ws: WebSocket, dst):
    async with aiofiles.open(dst, "wb") as f:
        try:
            while True:
                chunk = await ws.receive_bytes()
                await f.write(chunk)
        except WebSocketDisconnect:
            pass

@router.websocket("/ws/episodes/{episode_id}/video")
async def video_ws(ws: WebSocket, episode_id: str):
    await ws.accept()
    tmp = MEDIA_DIR / f"{episode_id}_{uuid.uuid4()}.fmp4"
    await _write_chunks(ws, tmp)

    # seal fragmented MP4 so it plays everywhere
    final = MEDIA_DIR / f"{episode_id}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", tmp, "-c", "copy", final],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
    )
    tmp.unlink(missing_ok=True)
