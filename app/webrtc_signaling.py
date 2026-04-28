# WebRTC Signaling Server for Unified Camera System

import json
import logging
import asyncio
import socket
from typing import Dict, Set, Optional, Any
from fastapi import WebSocket, WebSocketDisconnect
import uuid

logger = logging.getLogger(__name__)

def get_local_ip():
    """Get the local IP address of this machine"""
    try:
        # Connect to a remote address to determine the local IP
        # This doesn't actually send data, just determines the local IP used for routing
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception as e:
        logger.warning(f"Could not determine local IP, using localhost: {e}")
        return "localhost"

class WebRTCSignalingServer:
    """WebRTC signaling server for camera streaming"""
    
    def __init__(self):
        # Active WebSocket connections
        self.connections: Dict[str, WebSocket] = {}
        
        # Camera sources registry
        self.camera_sources: Dict[str, Dict[str, Any]] = {}
        
        # Peer-to-peer mappings (for future remote cameras)
        self.peer_mappings: Dict[str, str] = {}
        
        # Connection metadata
        self.connection_metadata: Dict[str, Dict[str, Any]] = {}
        
        # External camera sessions (legacy: phone_sessions for backward compatibility)
        self.external_sessions: Dict[str, Dict[str, Any]] = {}
        self.phone_sessions: Dict[str, Dict[str, Any]] = {}  # Legacy support
    
    def _get_session(self, session_id: str) -> Dict[str, Any]:
        """Get session from either external_sessions or legacy phone_sessions"""
        return self.external_sessions.get(session_id) or self.phone_sessions.get(session_id)
    
    def _set_session(self, session_id: str, session_data: Dict[str, Any]):
        """Set session, preferring external_sessions for new sessions"""
        if session_id.startswith('external_'):
            self.external_sessions[session_id] = session_data
        else:
            # Legacy support for phone_ prefixed sessions
            self.phone_sessions[session_id] = session_data
    
    def _remove_session(self, session_id: str):
        """Remove session from both locations"""
        self.external_sessions.pop(session_id, None)
        self.phone_sessions.pop(session_id, None)
    
    async def connect(self, websocket: WebSocket) -> str:
        """Accept a new WebSocket connection and return connection ID"""
        await websocket.accept()
        connection_id = str(uuid.uuid4())
        
        self.connections[connection_id] = websocket
        self.connection_metadata[connection_id] = {
            "connected_at": asyncio.get_event_loop().time(),
            "camera_sources": [],
            "peer_id": None
        }
        
        logger.info(f"🔗 WebRTC client connected: {connection_id}")
        logger.info(f"📊 Total connections: {len(self.connections)}")
        
        return connection_id
    
    def disconnect(self, connection_id: str):
        """Handle client disconnection"""
        if connection_id in self.connections:
            # Clean up camera sources for this connection
            metadata = self.connection_metadata.get(connection_id, {})
            camera_sources = metadata.get("camera_sources", [])
            
            for source_id in camera_sources:
                if source_id in self.camera_sources:
                    logger.info(f"🗑️ Removing camera source: {source_id}")
                    del self.camera_sources[source_id]
            
            # Remove connection
            del self.connections[connection_id]
            if connection_id in self.connection_metadata:
                del self.connection_metadata[connection_id]
            
            logger.info(f"🔌 WebRTC client disconnected: {connection_id}")
            logger.info(f"📊 Total connections: {len(self.connections)}")
    
    async def handle_message(self, connection_id: str, message: Dict[str, Any]):
        """Handle incoming signaling message"""
        try:
            message_type = message.get("type")
            source_id = message.get("sourceId")
            
            logger.info(f"📨 Received {message_type} for source {source_id} from {connection_id}")
            
            if message_type == "register-camera":
                await self._handle_register_camera(connection_id, message)
            elif message_type == "offer":
                await self._handle_offer(connection_id, message)
            elif message_type == "answer":
                await self._handle_answer(connection_id, message)
            elif message_type == "ice-candidate":
                await self._handle_ice_candidate(connection_id, message)
            elif message_type == "request-camera-list":
                await self._handle_camera_list_request(connection_id)
            elif message_type == "request-camera-stream":
                await self._handle_camera_stream_request(connection_id, message)
            elif message_type == "create-session":
                await self._handle_create_session(connection_id, message)
            elif message_type == "join-session":
                await self._handle_join_session(connection_id, message)
            else:
                logger.warning(f"⚠️ Unknown message type: {message_type}")
                
        except Exception as e:
            logger.error(f"❌ Error handling message from {connection_id}: {e}")
            await self._send_error(connection_id, str(e))
    
    async def _handle_register_camera(self, connection_id: str, message: Dict[str, Any]):
        """Register a new camera source"""
        source_id = message.get("sourceId")
        payload = message.get("payload", {})
        
        camera_info = {
            "id": source_id,
            "name": payload.get("name", "Unknown Camera"),
            "type": payload.get("type", "local"),
            "width": payload.get("width", 640),
            "height": payload.get("height", 480),
            "fps": payload.get("fps", 30),
            "owner_connection": connection_id,
            "status": "available",
            "registered_at": asyncio.get_event_loop().time()
        }
        
        self.camera_sources[source_id] = camera_info
        
        # Add to connection metadata
        if connection_id in self.connection_metadata:
            self.connection_metadata[connection_id]["camera_sources"].append(source_id)
        
        logger.info(f"📹 Registered camera: {camera_info['name']} ({source_id})")
        
        # Broadcast camera list update to all connections
        await self._broadcast_camera_list()
        
        # Confirm registration
        await self._send_message(connection_id, {
            "type": "camera-registered",
            "sourceId": source_id,
            "payload": {"status": "success"},
            "timestamp": int(asyncio.get_event_loop().time() * 1000)
        })
    
    async def _handle_offer(self, connection_id: str, message: Dict[str, Any]):
        """Handle WebRTC offer"""
        source_id = message.get("sourceId")
        target_id = message.get("targetId")
        
        logger.info(f"📤 Processing offer from {connection_id} for session {source_id}")
        
        # Check if this is an external camera session offer
        session = self._get_session(source_id)
        if session:
            desktop_client = session.get("desktop_client")
            
            logger.info(f"📤 External camera offer for session {source_id}, forwarding to desktop {desktop_client}")
            logger.info(f"📤 Session status: {session.get('status')}")
            logger.info(f"📤 External device client: {session.get('external_client') or session.get('phone_client')}")
            
            if desktop_client and desktop_client in self.connections:
                # Forward offer to desktop client
                await self._send_message(desktop_client, message)
            else:
                logger.error(f"❌ Desktop client {desktop_client} not found for session {source_id}")
                await self._send_error(connection_id, f"Desktop client not connected for session {source_id}")
        elif target_id and target_id in self.connections:
            # Forward offer to target connection (for remote cameras)
            await self._send_message(target_id, message)
        else:
            # For local cameras, this might be an offer to the server
            # We can handle it here or forward to all other connections
            logger.info(f"📤 Broadcasting offer for camera {source_id}")
            await self._broadcast_message(message, exclude=connection_id)
    
    async def _handle_answer(self, connection_id: str, message: Dict[str, Any]):
        """Handle WebRTC answer"""
        source_id = message.get("sourceId")
        target_id = message.get("targetId")
        
        logger.info(f"📥 Processing answer from {connection_id} for session {source_id}")
        
        # Check if this is an external camera session answer
        session = self._get_session(source_id)
        if session:
            external_client = session.get("external_client") or session.get("phone_client")  # Legacy support
            
            logger.info(f"📥 Desktop answer for session {source_id}, forwarding to external device {external_client}")
            
            if external_client and external_client in self.connections:
                # Forward answer to external device client
                await self._send_message(external_client, message)
            else:
                logger.error(f"❌ External device client {external_client} not found for session {source_id}")
                await self._send_error(connection_id, f"External device client not connected for session {source_id}")
        elif target_id and target_id in self.connections:
            # Forward answer to target connection
            await self._send_message(target_id, message)
        else:
            # Broadcast answer
            await self._broadcast_message(message, exclude=connection_id)
    
    async def _handle_ice_candidate(self, connection_id: str, message: Dict[str, Any]):
        """Handle ICE candidate"""
        source_id = message.get("sourceId")
        target_id = message.get("targetId")
        candidate_info = message.get("payload", {}).get("candidate", {})
        
        logger.info(f"🧊 Processing ICE candidate from {connection_id} for session {source_id}")
        logger.info(f"🧊 Candidate type: {candidate_info.get('type', 'unknown')}")
        
        # Check if this is an external camera session ICE candidate
        session = self._get_session(source_id)
        if session:
            external_client = session.get("external_client") or session.get("phone_client")  # Legacy support
            
            # Determine if this is from external device or desktop
            if connection_id == external_client:
                # From external device to desktop
                desktop_client = session.get("desktop_client")
                logger.info(f"🧊 External device ICE candidate for session {source_id}, forwarding to desktop {desktop_client}")
                
                if desktop_client and desktop_client in self.connections:
                    await self._send_message(desktop_client, message)
                else:
                    logger.error(f"❌ Desktop client {desktop_client} not found for ICE candidate")
                    
            elif connection_id == session.get("desktop_client"):
                # From desktop to external device
                logger.info(f"🧊 Desktop ICE candidate for session {source_id}, forwarding to external device {external_client}")
                
                if external_client and external_client in self.connections:
                    await self._send_message(external_client, message)
                else:
                    logger.error(f"❌ External device client {external_client} not found for ICE candidate")
            else:
                logger.warning(f"⚠️ ICE candidate from unknown connection {connection_id} for session {source_id}")
                
        elif target_id and target_id in self.connections:
            # Forward ICE candidate to target connection
            await self._send_message(target_id, message)
        else:
            # Broadcast ICE candidate
            await self._broadcast_message(message, exclude=connection_id)
    
    async def _handle_camera_list_request(self, connection_id: str):
        """Send available camera list to requesting connection"""
        camera_list = []
        for source_id, camera_info in self.camera_sources.items():
            camera_list.append({
                "id": source_id,
                "name": camera_info["name"],
                "type": camera_info["type"],
                "available": camera_info["status"] == "available",
                "width": camera_info["width"],
                "height": camera_info["height"],
                "fps": camera_info["fps"]
            })
        
        await self._send_message(connection_id, {
            "type": "camera-list",
            "sourceId": "server",
            "payload": {"cameras": camera_list},
            "timestamp": int(asyncio.get_event_loop().time() * 1000)
        })
    
    async def _handle_camera_stream_request(self, connection_id: str, message: Dict[str, Any]):
        """Handle request for camera stream"""
        requested_source_id = message.get("payload", {}).get("sourceId")
        
        if requested_source_id in self.camera_sources:
            camera_info = self.camera_sources[requested_source_id]
            owner_connection = camera_info["owner_connection"]
            
            if owner_connection in self.connections:
                # Forward stream request to camera owner
                stream_request = {
                    "type": "stream-request",
                    "sourceId": requested_source_id,
                    "targetId": connection_id,
                    "payload": {"requesterId": connection_id},
                    "timestamp": int(asyncio.get_event_loop().time() * 1000)
                }
                await self._send_message(owner_connection, stream_request)
            else:
                await self._send_error(connection_id, f"Camera owner not connected")
        else:
            await self._send_error(connection_id, f"Camera {requested_source_id} not found")
    
    async def _handle_create_session(self, connection_id: str, message: Dict[str, Any]):
        """Handle external camera session creation"""
        session_id = message.get("sourceId")
        payload = message.get("payload", {})
        
        if not session_id:
            await self._send_error(connection_id, "Session ID is required")
            return
        
        # Check if session already exists
        existing_session = self._get_session(session_id)
        session_existed = existing_session is not None
        
        if existing_session:
            logger.info(f"🌐 Session {session_id} already exists, updating desktop client and re-sending QR URL")
            # Update the desktop client (in case it's a reconnection)
            existing_session["desktop_client"] = connection_id
            existing_session["name"] = payload.get("name", existing_session.get("name", "External Camera"))
            self._set_session(session_id, existing_session)
            
            # Log session status for debugging
            external_client = existing_session.get("external_client") or existing_session.get("phone_client")
            logger.info(f"🌐 Existing session status - external_client: {external_client}, status: {existing_session.get('status')}")
        else:
            # Create new external camera session
            session_info = {
                "session_id": session_id,
                "name": payload.get("name", "External Camera"),
                "desktop_client": connection_id,
                "external_client": None,
                "phone_client": None,  # Legacy support
                "status": "waiting_for_device",
                "created_at": asyncio.get_event_loop().time()
            }
            
            self._set_session(session_id, session_info)
            logger.info(f"🌐 Created new external camera session: {session_id}")
        
        # Generate QR URL - only use external URL (ngrok), no local fallback
        from .config import get_external_url
        external_url = get_external_url()
        
        if external_url:
            # Use external URL (ngrok, tunneling, etc.)
            qr_url = f"{external_url}/remote_cam/{session_id}"
            logger.info(f"📱 Using external URL for QR: {external_url}")
            
            # Send confirmation to desktop with QR URL and session info
            session_info = existing_session if existing_session else self._get_session(session_id)
            external_client = session_info.get("external_client") or session_info.get("phone_client") if session_info else None
            device_connected = external_client is not None and external_client in self.connections
            
            await self._send_message(connection_id, {
                "type": "session-created",
                "sourceId": session_id,
                "payload": {
                    "sessionId": session_id,
                    "qrCodeUrl": qr_url,
                    "sessionExisted": session_existed,
                    "deviceConnected": device_connected,
                    "sessionStatus": session_info.get("status") if session_info else "new"
                },
                "timestamp": int(asyncio.get_event_loop().time() * 1000)
            })
        else:
            # No external URL configured - don't generate local URLs due to HTTPS issues
            logger.warning(f"🌐 No external URL configured - external camera requires ngrok setup")
            
            # Send confirmation to desktop without QR URL (will show ngrok required message)
            session_info = existing_session if existing_session else self._get_session(session_id)
            external_client = session_info.get("external_client") or session_info.get("phone_client") if session_info else None
            device_connected = external_client is not None and external_client in self.connections
            
            await self._send_message(connection_id, {
                "type": "session-created",
                "sourceId": session_id,
                "payload": {
                    "sessionId": session_id,
                    "sessionExisted": session_existed,
                    "deviceConnected": device_connected,
                    "sessionStatus": session_info.get("status") if session_info else "new"
                    # No qrCodeUrl - frontend will show "configure ngrok" message
                },
                "timestamp": int(asyncio.get_event_loop().time() * 1000)
            })
    
    async def _handle_join_session(self, connection_id: str, message: Dict[str, Any]):
        """Handle external device joining a session"""
        session_id = message.get("sourceId")
        payload = message.get("payload", {})
        
        session = self._get_session(session_id)
        if not session_id or not session:
            await self._send_error(connection_id, "Session not found")
            return
        
        # Enhanced debugging for multiple sessions
        logger.info(f"🌐 External device joining session: {session_id}")
        logger.info(f"🌐 Device details: {payload}")
        logger.info(f"🌐 Active sessions: {len(self.external_sessions) + len(self.phone_sessions)}")
        logger.info(f"🌐 Total connections: {len(self.connections)}")
        
        # Check for existing external device connection (Android multi-session issue)
        existing_client = session.get("external_client") or session.get("phone_client")  # Legacy support
        if existing_client and existing_client in self.connections:
            logger.warning(f"⚠️ Session {session_id} already has a device connected: {existing_client}")
            logger.warning(f"⚠️ New device connection: {connection_id}")
            logger.warning(f"⚠️ This might be an Android multi-session conflict")
        
        session["external_client"] = connection_id
        session["phone_client"] = connection_id  # Legacy support
        session["status"] = "device_connected"
        session["device_info"] = {
            "userAgent": payload.get("userAgent", "unknown"),
            "platform": payload.get("platform", "unknown"),
            "webrtcSupported": payload.get("webrtcSupported", False),
            "connected_at": asyncio.get_event_loop().time()
        }
        
        logger.info(f"🌐 External device joined session: {session_id} from {payload.get('platform', 'unknown')}")
        
        # Notify desktop that external device connected
        desktop_client = session.get("desktop_client")
        if desktop_client and desktop_client in self.connections:
            await self._send_message(desktop_client, {
                "type": "external-device-connected",
                "sourceId": session_id,
                "payload": {
                    "sessionId": session_id,
                    "deviceInfo": session["device_info"]
                },
                "timestamp": int(asyncio.get_event_loop().time() * 1000)
            })
        
        # Confirm to external device
        await self._send_message(connection_id, {
            "type": "session-joined",
            "sourceId": session_id,
            "payload": {
                "sessionId": session_id,
                "activeSessions": len(self.external_sessions) + len(self.phone_sessions),
                "totalConnections": len(self.connections)
            },
            "timestamp": int(asyncio.get_event_loop().time() * 1000)
        })
    
    async def _broadcast_camera_list(self):
        """Broadcast updated camera list to all connections"""
        camera_list = []
        for source_id, camera_info in self.camera_sources.items():
            camera_list.append({
                "id": source_id,
                "name": camera_info["name"],
                "type": camera_info["type"],
                "available": camera_info["status"] == "available"
            })
        
        broadcast_message = {
            "type": "camera-list-update",
            "sourceId": "server",
            "payload": {"cameras": camera_list},
            "timestamp": int(asyncio.get_event_loop().time() * 1000)
        }
        
        await self._broadcast_message(broadcast_message)
    
    async def _send_message(self, connection_id: str, message: Dict[str, Any]):
        """Send message to specific connection"""
        if connection_id in self.connections:
            try:
                websocket = self.connections[connection_id]
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"❌ Failed to send message to {connection_id}: {e}")
                # Remove dead connection
                self.disconnect(connection_id)
    
    async def _broadcast_message(self, message: Dict[str, Any], exclude: Optional[str] = None):
        """Broadcast message to all connections except excluded one"""
        dead_connections = []
        
        for connection_id, websocket in self.connections.items():
            if connection_id == exclude:
                continue
                
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"❌ Failed to broadcast to {connection_id}: {e}")
                dead_connections.append(connection_id)
        
        # Clean up dead connections
        for dead_id in dead_connections:
            self.disconnect(dead_id)
    
    async def _send_error(self, connection_id: str, error_message: str):
        """Send error message to connection"""
        error_msg = {
            "type": "error",
            "sourceId": "server",
            "payload": {"error": error_message},
            "timestamp": int(asyncio.get_event_loop().time() * 1000)
        }
        await self._send_message(connection_id, error_msg)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get signaling server statistics"""
        return {
            "total_connections": len(self.connections),
            "total_cameras": len(self.camera_sources),
            "local_cameras": len([c for c in self.camera_sources.values() if c["type"] == "local"]),
            "remote_cameras": len([c for c in self.camera_sources.values() if c["type"] == "remote"]),
            "active_cameras": len([c for c in self.camera_sources.values() if c["status"] == "available"])
        }

# Global signaling server instance
signaling_server = WebRTCSignalingServer()