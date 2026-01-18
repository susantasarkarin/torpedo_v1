"""
WebSocket Connection Manager

Singleton class for managing WebSocket connections across the application.
Supports multiple channels (cint_surveys, cpx_surveys, sync_progress) and
provides broadcast and personal messaging capabilities.
"""

from typing import Dict, List, Set, Optional, Any
from fastapi import WebSocket
import asyncio
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Singleton WebSocket connection manager.
    
    Manages WebSocket connections organized by channels.
    Supports broadcasting to all clients on a channel or sending
    personal messages to specific connections.
    """
    
    _instance: Optional['ConnectionManager'] = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # Channel -> Set of WebSocket connections
        self._connections: Dict[str, Set[WebSocket]] = {}
        
        # WebSocket -> metadata (user_id, connected_at, etc.)
        self._metadata: Dict[WebSocket, Dict[str, Any]] = {}
        
        # Supported channels
        self.CHANNELS = {
            "cint_surveys": "CINT survey updates",
            "cpx_surveys": "CPX survey updates", 
            "sync_progress": "Email sync progress updates",
        }
        
        # Heartbeat interval in seconds
        self.HEARTBEAT_INTERVAL = 30
        
        self._initialized = True
        logger.info("WebSocket ConnectionManager initialized")
    
    async def connect(
        self, 
        websocket: WebSocket, 
        channel: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Accept a WebSocket connection and register it to a channel.
        
        Args:
            websocket: The WebSocket connection
            channel: Channel name to subscribe to
            user_id: Optional user identifier
            metadata: Optional additional metadata
            
        Returns:
            True if connection was successful, False otherwise
        """
        if channel not in self.CHANNELS:
            logger.warning(f"Attempted connection to unknown channel: {channel}")
            # Still allow connection for flexibility
        
        try:
            await websocket.accept()
            
            # Initialize channel if needed
            if channel not in self._connections:
                self._connections[channel] = set()
            
            self._connections[channel].add(websocket)
            
            # Store metadata
            self._metadata[websocket] = {
                "channel": channel,
                "user_id": user_id,
                "connected_at": datetime.utcnow().isoformat(),
                **(metadata or {})
            }
            
            logger.info(f"WebSocket connected to channel '{channel}'. Total on channel: {len(self._connections[channel])}")
            
            # Send welcome message
            await self.send_personal(websocket, {
                "type": "connected",
                "channel": channel,
                "message": f"Connected to {channel}",
                "timestamp": datetime.utcnow().isoformat()
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Error accepting WebSocket connection: {e}")
            return False
    
    def disconnect(self, websocket: WebSocket, channel: Optional[str] = None) -> None:
        """
        Remove a WebSocket connection from a channel.
        
        Args:
            websocket: The WebSocket connection to remove
            channel: Optional channel name. If not provided, removes from all channels.
        """
        try:
            if channel:
                if channel in self._connections:
                    self._connections[channel].discard(websocket)
                    logger.info(f"WebSocket disconnected from channel '{channel}'. Remaining: {len(self._connections[channel])}")
            else:
                # Remove from all channels
                for ch in self._connections.values():
                    ch.discard(websocket)
            
            # Clean up metadata
            if websocket in self._metadata:
                del self._metadata[websocket]
                
        except Exception as e:
            logger.error(f"Error disconnecting WebSocket: {e}")
    
    async def send_personal(self, websocket: WebSocket, message: Any) -> bool:
        """
        Send a message to a specific WebSocket connection.
        
        Args:
            websocket: Target WebSocket connection
            message: Message to send (will be JSON encoded if dict/list)
            
        Returns:
            True if message was sent, False otherwise
        """
        try:
            if isinstance(message, (dict, list)):
                await websocket.send_json(message)
            else:
                await websocket.send_text(str(message))
            return True
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")
            return False
    
    async def broadcast(
        self, 
        channel: str, 
        message: Any,
        exclude: Optional[Set[WebSocket]] = None
    ) -> int:
        """
        Broadcast a message to all connections on a channel.
        
        Args:
            channel: Channel to broadcast to
            message: Message to send (will be JSON encoded if dict/list)
            exclude: Optional set of WebSockets to exclude from broadcast
            
        Returns:
            Number of clients that received the message
        """
        if channel not in self._connections:
            return 0
        
        exclude = exclude or set()
        sent_count = 0
        failed_connections = []
        
        # Prepare message
        if isinstance(message, (dict, list)):
            # Add metadata to dict messages
            if isinstance(message, dict):
                message = {
                    **message,
                    "timestamp": datetime.utcnow().isoformat(),
                    "channel": channel
                }
        
        for websocket in self._connections[channel]:
            if websocket in exclude:
                continue
                
            try:
                if isinstance(message, (dict, list)):
                    await websocket.send_json(message)
                else:
                    await websocket.send_text(str(message))
                sent_count += 1
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                failed_connections.append(websocket)
        
        # Clean up failed connections
        for ws in failed_connections:
            self.disconnect(ws, channel)
        
        if sent_count > 0:
            logger.debug(f"Broadcast to {sent_count} clients on channel '{channel}'")
        
        return sent_count
    
    async def broadcast_to_user(
        self, 
        user_id: str, 
        message: Any,
        channel: Optional[str] = None
    ) -> int:
        """
        Broadcast a message to all connections belonging to a specific user.
        
        Args:
            user_id: User identifier to send to
            message: Message to send
            channel: Optional channel filter
            
        Returns:
            Number of clients that received the message
        """
        sent_count = 0
        
        for websocket, meta in self._metadata.items():
            if meta.get("user_id") != user_id:
                continue
            if channel and meta.get("channel") != channel:
                continue
                
            if await self.send_personal(websocket, message):
                sent_count += 1
        
        return sent_count
    
    def get_connection_count(self, channel: Optional[str] = None) -> int:
        """
        Get the number of active connections.
        
        Args:
            channel: Optional channel to count. If None, counts all.
            
        Returns:
            Number of active connections
        """
        if channel:
            return len(self._connections.get(channel, set()))
        return sum(len(conns) for conns in self._connections.values())
    
    def get_channel_stats(self) -> Dict[str, int]:
        """
        Get connection counts for all channels.
        
        Returns:
            Dict mapping channel names to connection counts
        """
        return {
            channel: len(connections)
            for channel, connections in self._connections.items()
        }
    
    async def send_heartbeat(self, channel: Optional[str] = None) -> int:
        """
        Send heartbeat ping to all connections on a channel.
        
        Args:
            channel: Optional channel. If None, pings all channels.
            
        Returns:
            Number of successful pings
        """
        ping_message = {
            "type": "heartbeat",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if channel:
            return await self.broadcast(channel, ping_message)
        
        total = 0
        for ch in self._connections.keys():
            total += await self.broadcast(ch, ping_message)
        return total


# Global singleton instance
connection_manager = ConnectionManager()


async def heartbeat_task():
    """
    Background task that sends heartbeat pings to all WebSocket connections.
    Should be started when the application starts.
    """
    manager = connection_manager
    
    while True:
        try:
            await asyncio.sleep(manager.HEARTBEAT_INTERVAL)
            count = await manager.send_heartbeat()
            if count > 0:
                logger.debug(f"Sent heartbeat to {count} WebSocket clients")
        except asyncio.CancelledError:
            logger.info("Heartbeat task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in heartbeat task: {e}")
