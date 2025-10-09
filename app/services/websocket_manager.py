import json
from typing import Dict, Set

from loguru import logger


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, Set] = {}
        self.admin_users: Set[int] = set()
        
    async def connect(self, websocket, user_id: int, is_admin: bool = False):
        """Connect a user to WebSocket"""
        # Make sure the WebSocket is accepted before adding to manager
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        
        self.active_connections[user_id].add(websocket)
        
        if is_admin:
            self.admin_users.add(user_id)
        
        logger.info(f"User {user_id} connected to WebSocket manager. Admin: {is_admin}")
    
    def disconnect(self, websocket, user_id: int):
        """Disconnect a user from WebSocket"""
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
                if user_id in self.admin_users:
                    self.admin_users.discard(user_id)
        
        logger.info(f"User {user_id} disconnected from WebSocket manager")
    
    async def send_personal_message(self, message: dict, user_id: int):
        """Send message to a specific user"""
        if user_id in self.active_connections:
            disconnected = set()
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_text(json.dumps(message))
                    logger.debug(f"Message sent to user {user_id}")
                except Exception as e:
                    logger.error(f"Error sending message to user {user_id}: {e}")
                    disconnected.add(connection)
            
            # Remove disconnected sockets
            for connection in disconnected:
                self.active_connections[user_id].discard(connection)
                logger.debug(f"Removed disconnected WebSocket for user {user_id}")
            
            # Clean up empty user entries
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
                if user_id in self.admin_users:
                    self.admin_users.discard(user_id)
        else:
            logger.warning(f"Attempted to send message to disconnected user {user_id}")
    
    async def broadcast_to_admins(self, message: dict):
        """Broadcast message to all admin users"""
        for admin_id in list(self.admin_users):  # Use list to avoid modification during iteration
            await self.send_personal_message(message, admin_id)
    
    def get_connection_stats(self) -> dict:
        """Get connection statistics"""
        total_connections = sum(len(connections) for connections in self.active_connections.values())
        return {
            "total_users": len(self.active_connections),
            "total_connections": total_connections,
            "admin_users": len(self.admin_users),
            "active_user_ids": list(self.active_connections.keys())
        }


# Global WebSocket manager instance
websocket_manager = ConnectionManager()
