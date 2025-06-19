import socketio
import logging
from typing import Dict, Set, Optional, Any
import time  # Use regular time instead of asyncio for timestamps
import uuid
import json
import asyncio
from datetime import datetime

# Set up logging
logger = logging.getLogger(__name__)

# Socket.IO server for WebRTC signaling
sio = socketio.AsyncServer(
    cors_allowed_origins="*",
    logger=True,
    engineio_logger=True
)

# Store active WebRTC sessions
active_sessions: Dict[str, Dict] = {}
session_clients: Dict[str, Set[str]] = {}  # webrtc_id -> set of client session IDs

# Store active video streams
active_streams: Dict[str, Dict] = {}  # stream_id -> stream metadata
stream_buffers: Dict[str, list] = {}  # stream_id -> buffered video frames

# Stream configuration
MAX_BUFFER_SIZE = 100  # Maximum frames to buffer per stream
STREAM_TIMEOUT = 300   # Stream timeout in seconds

@sio.event
async def connect(sid, environ):
    """Handle client connection"""
    logger.info(f"Client connected: {sid}")
    
@sio.event
async def disconnect(sid):
    """Handle client disconnection"""
    logger.info(f"Client disconnected: {sid}")
    
    # Clean up any sessions this client was part of
    sessions_to_clean = []
    streams_to_clean = []
    
    for webrtc_id, clients in session_clients.items():
        if sid in clients:
            clients.remove(sid)
            if len(clients) == 0:
                sessions_to_clean.append(webrtc_id)
                
                # Mark associated stream for cleanup
                session = active_sessions.get(webrtc_id)
                if session and session.get('stream_id'):
                    streams_to_clean.append(session['stream_id'])
    
    # Remove empty sessions and associated streams
    for webrtc_id in sessions_to_clean:
        if webrtc_id in active_sessions:
            del active_sessions[webrtc_id]
        if webrtc_id in session_clients:
            del session_clients[webrtc_id]
        logger.info(f"Cleaned up empty WebRTC session: {webrtc_id}")
    
    # Clean up streams
    for stream_id in streams_to_clean:
        if stream_id in active_streams:
            del active_streams[stream_id]
        if stream_id in stream_buffers:
            del stream_buffers[stream_id]
        logger.info(f"Cleaned up stream: {stream_id}")

@sio.event
async def create_session(sid, data):
    """Create a new WebRTC session for a phone camera"""
    webrtc_id = data.get('webrtcId')
    if not webrtc_id:
        await sio.emit('session-error', {'error': 'No webrtcId provided'}, room=sid)
        return
    
    logger.info(f"Creating WebRTC session: {webrtc_id} for client: {sid}")
    
    # Generate unique stream ID for this session
    stream_id = str(uuid.uuid4())
    
    # Initialize session
    active_sessions[webrtc_id] = {
        'created_at': time.time(),
        'status': 'waiting_for_phone',
        'desktop_client': sid,
        'phone_client': None,
        'stream_id': stream_id,
        'session_id': str(uuid.uuid4())  # Unique session identifier
    }
    
    # Initialize stream storage
    active_streams[stream_id] = {
        'stream_id': stream_id,
        'webrtc_id': webrtc_id,
        'created_at': datetime.now().isoformat(),
        'status': 'waiting_for_stream',
        'metadata': {
            'width': None,
            'height': None,
            'fps': None,
            'codec': None
        }
    }
    
    stream_buffers[stream_id] = []
    
    if webrtc_id not in session_clients:
        session_clients[webrtc_id] = set()
    session_clients[webrtc_id].add(sid)
    
    await sio.emit('session-created', {
        'webrtcId': webrtc_id,
        'streamId': stream_id,
        'sessionId': active_sessions[webrtc_id]['session_id']
    }, room=sid)

@sio.event
async def join_session(sid, data):
    """Phone joins an existing WebRTC session"""
    webrtc_id = data.get('webrtcId')
    if not webrtc_id:
        await sio.emit('session-error', {'error': 'No webrtcId provided'}, room=sid)
        return
    
    logger.info(f"Phone joining WebRTC session: {webrtc_id} from client: {sid}")
    
    if webrtc_id not in active_sessions:
        await sio.emit('session-error', {'error': 'Session not found'}, room=sid)
        return
    
    # Update session with phone client
    session = active_sessions[webrtc_id]
    session['phone_client'] = sid
    session['status'] = 'phone_connected'
    
    if webrtc_id not in session_clients:
        session_clients[webrtc_id] = set()
    session_clients[webrtc_id].add(sid)
    
    # Notify desktop client that phone has connected
    desktop_client = session.get('desktop_client')
    if desktop_client:
        await sio.emit('phone-connected', {'webrtcId': webrtc_id}, room=desktop_client)
    
    await sio.emit('session-joined', {'webrtcId': webrtc_id}, room=sid)

@sio.event
async def signal(sid, data):
    """Forward WebRTC signaling data between desktop and phone"""
    webrtc_id = data.get('webrtcId')
    signal_data = data.get('signal')
    
    if not webrtc_id or not signal_data:
        await sio.emit('session-error', {'error': 'Invalid signaling data'}, room=sid)
        return
    
    logger.info(f"Forwarding signal for session: {webrtc_id} from client: {sid}")
    
    if webrtc_id not in active_sessions:
        await sio.emit('session-error', {'error': 'Session not found'}, room=sid)
        return
    
    session = active_sessions[webrtc_id]
    
    # Forward signal to the other client in the session
    if sid == session.get('desktop_client'):
        # Signal from desktop to phone
        phone_client = session.get('phone_client')
        if phone_client:
            await sio.emit('signal', {
                'webrtcId': webrtc_id,
                'signal': signal_data
            }, room=phone_client)
    elif sid == session.get('phone_client'):
        # Signal from phone to desktop
        desktop_client = session.get('desktop_client')
        if desktop_client:
            await sio.emit('signal', {
                'webrtcId': webrtc_id,
                'signal': signal_data
            }, room=desktop_client)
    else:
        await sio.emit('session-error', {'error': 'Client not part of session'}, room=sid)

@sio.event
async def stream_ready(sid, data):
    """Handle notification that stream is ready to send data"""
    webrtc_id = data.get('webrtcId')
    stream_metadata = data.get('metadata', {})
    
    if not webrtc_id:
        await sio.emit('stream-error', {'error': 'No webrtcId provided'}, room=sid)
        return
    
    session = active_sessions.get(webrtc_id)
    if not session:
        await sio.emit('stream-error', {'error': 'Session not found'}, room=sid)
        return
    
    stream_id = session.get('stream_id')
    if stream_id and stream_id in active_streams:
        # Update stream metadata
        active_streams[stream_id]['status'] = 'active'
        active_streams[stream_id]['metadata'].update(stream_metadata)
        
        logger.info(f"Stream {stream_id} is now active for session {webrtc_id}")
        
        # Notify other participants
        await sio.emit('stream-started', {
            'webrtcId': webrtc_id,
            'streamId': stream_id,
            'metadata': active_streams[stream_id]['metadata']
        }, room=session.get('desktop_client'))

@sio.event
async def stream_data(sid, data):
    """Handle incoming video stream data"""
    webrtc_id = data.get('webrtcId')
    frame_data = data.get('frameData')
    timestamp = data.get('timestamp', time.time())
    
    if not webrtc_id or not frame_data:
        return
    
    session = active_sessions.get(webrtc_id)
    if not session:
        return
    
    stream_id = session.get('stream_id')
    if not stream_id or stream_id not in stream_buffers:
        return
    
    # Add frame to buffer
    frame_entry = {
        'timestamp': timestamp,
        'data': frame_data,
        'sequence': len(stream_buffers[stream_id])
    }
    
    # Manage buffer size
    if len(stream_buffers[stream_id]) >= MAX_BUFFER_SIZE:
        stream_buffers[stream_id].pop(0)  # Remove oldest frame
    
    stream_buffers[stream_id].append(frame_entry)
    
    # Update stream status
    if stream_id in active_streams:
        active_streams[stream_id]['last_frame'] = timestamp
    
    # Forward to frontend clients if needed
    desktop_client = session.get('desktop_client')
    if desktop_client:
        await sio.emit('stream-frame', {
            'webrtcId': webrtc_id,
            'streamId': stream_id,
            'frameData': frame_data,
            'timestamp': timestamp
        }, room=desktop_client)

@sio.event
async def get_stream_info(sid, data):
    """Get information about a specific stream"""
    stream_id = data.get('streamId')
    
    if not stream_id:
        await sio.emit('stream-error', {'error': 'No streamId provided'}, room=sid)
        return
    
    if stream_id not in active_streams:
        await sio.emit('stream-error', {'error': 'Stream not found'}, room=sid)
        return
    
    stream_info = active_streams[stream_id].copy()
    stream_info['buffer_size'] = len(stream_buffers.get(stream_id, []))
    
    await sio.emit('stream-info', stream_info, room=sid)

@sio.event
async def list_active_streams(sid, data):
    """List all active streams"""
    streams = []
    for stream_id, stream_data in active_streams.items():
        stream_copy = stream_data.copy()
        stream_copy['buffer_size'] = len(stream_buffers.get(stream_id, []))
        streams.append(stream_copy)
    
    await sio.emit('active-streams', {'streams': streams}, room=sid)

@sio.event
async def destroy_session(sid, data):
    """Destroy a WebRTC session"""
    webrtc_id = data.get('webrtcId')
    if not webrtc_id:
        return
    
    logger.info(f"Destroying WebRTC session: {webrtc_id} by client: {sid}")
    
    # Clean up session
    if webrtc_id in active_sessions:
        session = active_sessions[webrtc_id]
        
        # Notify other client in session
        for client_type in ['desktop_client', 'phone_client']:
            client_sid = session.get(client_type)
            if client_sid and client_sid != sid:
                await sio.emit('session-destroyed', {'webrtcId': webrtc_id}, room=client_sid)
        
        del active_sessions[webrtc_id]
    
    if webrtc_id in session_clients:
        del session_clients[webrtc_id]

async def cleanup_expired_sessions():
    """Clean up sessions that have been inactive for too long"""
    current_time = time.time()  # Use regular time
    expired_sessions = []
    
    for webrtc_id, session in active_sessions.items():
        # Expire sessions after 1 hour
        if current_time - session['created_at'] > 3600:
            expired_sessions.append(webrtc_id)
    
    for webrtc_id in expired_sessions:
        logger.info(f"Cleaning up expired session: {webrtc_id}")
        if webrtc_id in active_sessions:
            del active_sessions[webrtc_id]
        if webrtc_id in session_clients:
            del session_clients[webrtc_id]

# Periodic cleanup task
async def start_cleanup_task():
    """Start periodic cleanup of expired sessions"""
    import asyncio
    while True:
        await asyncio.sleep(300)  # Check every 5 minutes
        await cleanup_expired_sessions()

def get_socketio_app():
    """Get the Socket.IO app for integration with FastAPI"""
    return sio 
