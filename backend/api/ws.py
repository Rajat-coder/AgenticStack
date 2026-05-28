from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.ws import connection_manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Browser connects here to receive real-time job status updates.
    Server pushes a message on every state change — no polling needed.

    Message format:
        {"job_id": "...", "status": "PLANNING", "detail": "..."}
    """
    await connection_manager.connect(websocket)
    try:
        while True:
            # Keep the connection alive.
            # One-way push channel: server → browser only.
            await websocket.receive_text()
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)