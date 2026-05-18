"""
WebSocket Connection Manager

Singleton class for managing WebSocket connections across the application.
Supports multiple channels (cint_surveys, cpx_surveys, sync_progress) and
provides broadcast and personal messaging capabilities.

Priority-based broadcasting ensures critical survey updates (CPX/CINT) are
never blocked by high-volume sync progress updates.
"""

from typing import Dict, List, Set, Optional, Any
from fastapi import WebSocket
import asyncio
from asyncio import PriorityQueue
import json
import logging
from datetime import datetime
from enum import IntEnum
from dataclasses import dataclass, field
from time import time

logger = logging.getLogger(__name__)


class BroadcastPriority(IntEnum):
    """
    Priority levels for WebSocket broadcasts.
    Lower numbers = higher priority (processed first).
    """
    SURVEY_UPDATE = 1    # CPX/CINT survey updates - highest priority
    HEARTBEAT = 2        # Keep-alive pings
    SYNC_PROGRESS = 3    # Email sync progress - lowest priority (high volume)


@dataclass(order=True)
class PrioritizedBroadcast:
    """A broadcast message with priority for queue ordering."""
    priority: int
    timestamp: float = field(compare=True)
    channel: str = field(compare=False)
    message: Any = field(compare=False)
    exclude: Set[WebSocket] = field(compare=False, default_factory=set)


# Channel to priority mapping
CHANNEL_PRIORITIES = {
    "cint_surveys": BroadcastPriority.SURVEY_UPDATE,
    "cpx_surveys": BroadcastPriority.SURVEY_UPDATE,
    "sync_progress": BroadcastPriority.SYNC_PROGRESS,
}


class ConnectionManager:
    """
    Singleton WebSocket connection manager.
    
    Manages WebSocket connections organized by channels.
    Supports broadcasting to all clients on a channel or sending
    personal messages to specific connections.
    
    Features:
    - Priority-based broadcasting (survey updates > sync progress)
    - Connection limits per channel to prevent resource exhaustion
    - Async broadcast queue for non-blocking operation
    """
    
    _instance: Optional['ConnectionManager'] = None
    _lock = asyncio.Lock()
    
    # Connection limits per channel
    MAX_CONNECTIONS_PER_CHANNEL = {
        "cint_surveys": 100,
        "cpx_surveys": 100,
        "sync_progress": 50,  # Lower limit for high-volume channel
    }
    DEFAULT_MAX_CONNECTIONS = 100
    
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
        
        # Priority broadcast queue
        self._broadcast_queue: PriorityQueue = PriorityQueue()
        self._queue_processor_task: Optional[asyncio.Task] = None
        
        # Sync progress throttling: mailbox_id -> last_broadcast_time
        self._sync_throttle: Dict[str, float] = {}
        self.SYNC_THROTTLE_SECONDS = 2.0  # Minimum seconds between sync updates per mailbox
        
        # Supported channels
        self.CHANNELS = {
            "cint_surveys": "CINT survey updates",
            "cpx_surveys": "CPX survey updates", 
            "sync_progress": "Email sync progress updates",
            "lead_generation": "AI lead generation agent progress",
        }
        
        # Heartbeat interval in seconds
        self.HEARTBEAT_INTERVAL = 30
        
        self._initialized = True
        logger.info("WebSocket ConnectionManager initialized with priority broadcasting")
    
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
        
        # Check connection limits per channel
        max_conns = self.MAX_CONNECTIONS_PER_CHANNEL.get(channel, self.DEFAULT_MAX_CONNECTIONS)
        current_conns = len(self._connections.get(channel, set()))
        if current_conns >= max_conns:
            logger.warning(f"Channel '{channel}' at capacity ({current_conns}/{max_conns}), rejecting connection")
            try:
                await websocket.close(code=1013, reason="Channel at capacity")
            except:
                pass
            return False
        
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
    
    def _should_throttle_sync(self, message: Any) -> bool:
        """
        Check if a sync progress message should be throttled.
        Allows updates through if:
        - It's been > SYNC_THROTTLE_SECONDS since last update for this mailbox
        - Status changed to completed/error/cancelled
        - It's a percentage milestone (every 5%)
        """
        if not isinstance(message, dict):
            return False
        
        mailbox_id = message.get("mailbox_id") or message.get("email")
        if not mailbox_id:
            return False
        
        now = time()
        last_broadcast = self._sync_throttle.get(mailbox_id, 0)
        
        # Always allow status change messages
        status = message.get("status", "")
        if status in ("completed", "error", "cancelled", "connecting", "counting"):
            self._sync_throttle[mailbox_id] = now
            # Clean up throttle entry on completion
            if status in ("completed", "error", "cancelled"):
                self._sync_throttle.pop(mailbox_id, None)
            return False
        
        # Allow milestone percentages (every 5%)
        percentage = message.get("percentage", 0)
        if percentage > 0 and percentage % 5 == 0:
            self._sync_throttle[mailbox_id] = now
            return False
        
        # Throttle if too soon
        if now - last_broadcast < self.SYNC_THROTTLE_SECONDS:
            return True
        
        self._sync_throttle[mailbox_id] = now
        return False
    
    async def broadcast(
        self, 
        channel: str, 
        message: Any,
        exclude: Optional[Set[WebSocket]] = None,
        priority: Optional[BroadcastPriority] = None
    ) -> int:
        """
        Broadcast a message to all connections on a channel.
        
        For sync_progress channel, messages are automatically throttled
        to prevent flooding (max 1 update per mailbox every 2 seconds,
        unless it's a status change or milestone).
        
        Args:
            channel: Channel to broadcast to
            message: Message to send (will be JSON encoded if dict/list)
            exclude: Optional set of WebSockets to exclude from broadcast
            priority: Optional broadcast priority (defaults based on channel)
            
        Returns:
            Number of clients that received the message
        """
        if channel not in self._connections:
            return 0
        
        # Apply throttling for sync_progress channel
        if channel == "sync_progress" and self._should_throttle_sync(message):
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
    
    async def broadcast_with_priority(
        self,
        channel: str,
        message: Any,
        priority: Optional[BroadcastPriority] = None,
        exclude: Optional[Set[WebSocket]] = None
    ) -> None:
        """
        Queue a broadcast with priority. Higher priority messages (lower numbers)
        are processed first, ensuring CPX/CINT updates are never blocked by sync progress.
        
        Args:
            channel: Channel to broadcast to
            message: Message to send
            priority: Broadcast priority (defaults based on channel)
            exclude: Optional set of WebSockets to exclude
        """
        if priority is None:
            priority = CHANNEL_PRIORITIES.get(channel, BroadcastPriority.SYNC_PROGRESS)
        
        broadcast = PrioritizedBroadcast(
            priority=priority,
            timestamp=time(),
            channel=channel,
            message=message,
            exclude=exclude or set()
        )
        
        await self._broadcast_queue.put(broadcast)
        
        # Start queue processor if not running
        if self._queue_processor_task is None or self._queue_processor_task.done():
            self._queue_processor_task = asyncio.create_task(self._process_broadcast_queue())
    
    async def _process_broadcast_queue(self):
        """Process queued broadcasts in priority order."""
        while not self._broadcast_queue.empty():
            try:
                broadcast: PrioritizedBroadcast = await asyncio.wait_for(
                    self._broadcast_queue.get(), timeout=0.1
                )
                await self.broadcast(
                    channel=broadcast.channel,
                    message=broadcast.message,
                    exclude=broadcast.exclude,
                    priority=BroadcastPriority(broadcast.priority)
                )
            except asyncio.TimeoutError:
                break
            except Exception as e:
                logger.error(f"Error processing broadcast queue: {e}")
    
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
