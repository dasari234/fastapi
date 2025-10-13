import json
from datetime import datetime
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_db_session
from app.api.v1.websocket_dependencies import get_current_user_websocket
from app.models.notification import Notification
from app.schemas.base import StandardResponse
from app.services.notification_service import notification_service
from app.services.websocket_manager import websocket_manager

router = APIRouter(tags=["Notifications"], prefix="/notifications")


@router.get(
    "",
    response_model=StandardResponse,
    summary="Get user notifications",
    responses={
        200: {"description": "Notifications retrieved successfully"},
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def get_notifications(
    limit: int = Query(50, ge=1, le=100, description="Number of notifications to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    unread_only: bool = Query(False, description="Return only unread notifications"),
    current_user_result: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get notifications for the current user"""
    try:
        current_user, auth_status = current_user_result
        if auth_status != status.HTTP_200_OK or not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )
        
        # Pass current user role to the service
        result, status_code = await notification_service.get_user_notifications(
            current_user.user_id, 
            limit, 
            offset, 
            unread_only, 
            db,
            current_user_role=getattr(current_user, 'role', 'user')  # Pass user role
        )
        
        if status_code != status.HTTP_200_OK:
            raise HTTPException(
                status_code=status_code,
                detail="Failed to retrieve notifications"
            )
        
        return StandardResponse(
            success=True,
            message="Notifications retrieved successfully",
            data=result,
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve notifications"
        )
        
@router.get(
    "/admin/all",
    response_model=StandardResponse,
    summary="Get all notifications (Admin only)",
    responses={
        200: {"description": "All notifications retrieved successfully"},
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden - Admin access required"},
        500: {"description": "Internal server error"},
    },
)
async def get_all_notifications(
    limit: int = Query(50, ge=1, le=100, description="Number of notifications to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    unread_only: bool = Query(False, description="Return only unread notifications"),
    current_user_result: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get all notifications (Admin only)"""
    try:
        current_user, auth_status = current_user_result
        if auth_status != status.HTTP_200_OK or not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )
        
        # Check if user is admin
        if getattr(current_user, 'role', 'user') != 'admin':
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        
        async def _get_all_notifications(session: AsyncSession):
            try:
                # Build query for all notifications
                query = select(Notification)
                
                if user_id:
                    query = query.where(Notification.user_id == user_id)
                
                if unread_only:
                    query = query.where(Notification.is_read == False)
                
                query = query.order_by(Notification.created_at.desc())
                
                # Count total
                count_query = query.with_only_columns(func.count()).order_by(None)
                total_count_result = await session.execute(count_query)
                total_count = total_count_result.scalar() or 0
                
                # Get paginated results
                query = query.offset(offset).limit(limit)
                result = await session.execute(query)
                notifications = result.scalars().all()
                
                # Get user details for all notifications
                user_ids = list(set(notification.user_id for notification in notifications))
                user_details_map = {}
                
                if user_ids:
                    from app.models.user import User
                    users_query = select(User).where(User.id.in_(user_ids))
                    users_result = await session.execute(users_query)
                    users = users_result.scalars().all()
                    
                    user_details_map = {
                        user.id: {
                            "id": user.id,
                            "email": user.email,
                            "first_name": user.first_name,
                            "last_name": user.last_name,
                            "role": user.role,
                            "is_active": user.is_active
                        }
                        for user in users
                    }
                
                notifications_data = []
                for notification in notifications:
                    notification_dict = {
                        "id": notification.id,
                        "user_id": notification.user_id,
                        "title": notification.title,
                        "message": notification.message,
                        "type": notification.notification_type,
                        "action_type": notification.action_type,
                        "action_data": notification.action_data or {},
                        "is_read": notification.is_read,
                        "read_at": notification.read_at.isoformat() if notification.read_at else None,
                        "created_at": notification.created_at.isoformat() if notification.created_at else None,
                    }
                    
                    # Add user details
                    if notification.user_id in user_details_map:
                        notification_dict["user_details"] = user_details_map[notification.user_id]
                    
                    notifications_data.append(notification_dict)
                
                return {
                    "notifications": notifications_data,
                    "total_count": total_count,
                    "filters": {
                        "user_id": user_id,
                        "unread_only": unread_only
                    }
                }, status.HTTP_200_OK
                
            except Exception as e:
                logger.error(f"Error getting all notifications: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        
        result, status_code = await _get_all_notifications(db)
        
        if status_code != status.HTTP_200_OK:
            raise HTTPException(
                status_code=status_code,
                detail="Failed to retrieve notifications"
            )
        
        return StandardResponse(
            success=True,
            message="All notifications retrieved successfully",
            data=result,
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting all notifications: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve notifications"
        )


@router.put(
    "/{notification_id}/read",
    response_model=StandardResponse,
    summary="Mark notification as read",
    responses={
        200: {"description": "Notification marked as read"},
        401: {"description": "Unauthorized"},
        404: {"description": "Notification not found"},
        500: {"description": "Internal server error"},
    },
)
async def mark_notification_as_read(
    notification_id: int,
    current_user_result: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Mark a notification as read"""
    try:
        current_user, auth_status = current_user_result
        if auth_status != status.HTTP_200_OK or not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )
        
        success, status_code = await notification_service.mark_as_read(
            notification_id, current_user.user_id, db
        )
        
        if not success:
            if status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Notification not found"
                )
            else:
                raise HTTPException(
                    status_code=status_code,
                    detail="Failed to mark notification as read"
                )
        
        return StandardResponse(
            success=True,
            message="Notification marked as read",
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking notification as read: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark notification as read"
        )


@router.put(
    "/read-all",
    response_model=StandardResponse,
    summary="Mark all notifications as read",
    responses={
        200: {"description": "All notifications marked as read"},
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def mark_all_notifications_as_read(
    current_user_result: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Mark all notifications as read for the current user"""
    try:
        current_user, auth_status = current_user_result
        if auth_status != status.HTTP_200_OK or not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )
        
        success, status_code = await notification_service.mark_all_as_read(
            current_user.user_id, db
        )
        
        if not success:
            raise HTTPException(
                status_code=status_code,
                detail="Failed to mark all notifications as read"
            )
        
        return StandardResponse(
            success=True,
            message="All notifications marked as read",
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking all notifications as read: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark all notifications as read"
        )


@router.get(
    "/preferences",
    response_model=StandardResponse,
    summary="Get notification preferences",
    responses={
        200: {"description": "Preferences retrieved successfully"},
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def get_notification_preferences(
    current_user_result: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get notification preferences for the current user"""
    try:
        current_user, auth_status = current_user_result
        if auth_status != status.HTTP_200_OK or not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )
        
        result, status_code = await notification_service.get_notification_preferences(
            current_user.user_id, db
        )
        
        if status_code != status.HTTP_200_OK:
            raise HTTPException(
                status_code=status_code,
                detail="Failed to retrieve notification preferences"
            )
        
        return StandardResponse(
            success=True,
            message="Notification preferences retrieved successfully",
            data=result,
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting notification preferences: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve notification preferences"
        )


@router.put(
    "/preferences",
    response_model=StandardResponse,
    summary="Update notification preferences",
    responses={
        200: {"description": "Preferences updated successfully"},
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def update_notification_preferences(
    preferences: dict,
    current_user_result: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Update notification preferences for the current user"""
    try:
        current_user, auth_status = current_user_result
        if auth_status != status.HTTP_200_OK or not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )
        
        result, status_code = await notification_service.update_notification_preferences(
            current_user.user_id, preferences, db
        )
        
        if status_code != status.HTTP_200_OK:
            raise HTTPException(
                status_code=status_code,
                detail="Failed to update notification preferences"
            )
        
        return StandardResponse(
            success=True,
            message="Notification preferences updated successfully",
            data=result,
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating notification preferences: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update notification preferences"
        )


@router.get(
    "/stream",
    summary="Stream real-time notifications",
    responses={
        200: {"description": "Real-time notification stream"},
        401: {"description": "Unauthorized"},
    },
)
async def stream_notifications(
    current_user_result: tuple = Depends(get_current_user),
):
    """Stream real-time notifications for the current user (SSE)"""
    try:
        current_user, auth_status = current_user_result
        if auth_status != status.HTTP_200_OK or not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )
        
        import json

        from fastapi.responses import StreamingResponse

        from app.services.redis_service import redis_service
        
        async def event_generator():
            try:
                async for message in redis_service.subscribe_to_notifications(current_user.user_id):
                    yield f"data: {json.dumps(message)}\n\n"
            except Exception as e:
                logger.error(f"Error in notification stream: {e}")
        
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating notification stream: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create notification stream"
        )
        
@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT token for authentication")
):
    """WebSocket endpoint for real-time notifications"""
    logger.info("New WebSocket connection attempt")
    
    current_user = None
    connection_accepted = False
    
    try:
        # Authenticate user BEFORE accepting the connection
        logger.debug("Starting authentication...")
        current_user = await get_current_user_websocket(token)
        
        if not current_user:
            logger.warning("WebSocket authentication failed - no user returned")
            # Don't accept the connection if authentication fails
            await websocket.close(code=1008, reason="Authentication failed")
            return

        # Safely get user_id from the user object
        user_id = getattr(current_user, 'user_id', None) or getattr(current_user, 'id', None)
        if not user_id:
            logger.error("No user_id found in user object")
            await websocket.close(code=1008, reason="Invalid user data")
            return

        logger.debug(f"User authenticated: {user_id}")

        # Determine if user is admin
        is_admin = (
            getattr(current_user, 'is_admin', False) or 
            getattr(current_user, 'role', 'user') == 'admin'
        )

        logger.info(f"User {user_id} authenticated, Admin: {is_admin}")

        # ACCEPT THE CONNECTION ONLY ONCE, after authentication
        await websocket.accept()
        connection_accepted = True
        logger.info("WebSocket connection accepted")

        # Connect to WebSocket manager
        await websocket_manager.connect(websocket, user_id, is_admin)
        
        # Send connection confirmation
        connection_message = {
            "type": "connection_established",
            "message": "WebSocket connection established successfully",
            "user_id": user_id,
            "is_admin": is_admin,
            "timestamp": datetime.now().isoformat()
        }
        await websocket.send_text(json.dumps(connection_message))
        logger.debug("Connection confirmation sent")

        # Keep connection alive and handle messages
        while True:
            try:
                # Use receive_text() for text messages or receive() for any type
                data = await websocket.receive_text()
                logger.debug(f"Received WebSocket message from user {user_id}: {data[:100]}...")
                await handle_websocket_message(data, current_user, websocket)
                
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected normally for user {user_id}")
                break
            except Exception as e:
                logger.error(f"Error processing WebSocket message for user {user_id}: {e}")
                # Send error message to client
                try:
                    error_message = {
                        "type": "error",
                        "message": "Error processing message",
                        "timestamp": datetime.now().isoformat()
                    }
                    await websocket.send_text(json.dumps(error_message))
                except Exception:
                    logger.warning(f"Could not send error message to user {user_id}, connection may be broken")
                    break

    except WebSocketDisconnect:
        user_id = getattr(current_user, 'user_id', None) if current_user else 'Unknown'
        logger.info(f"WebSocket disconnected during setup for user {user_id}")
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
        # Only try to close if connection was accepted
        if connection_accepted:
            try:
                await websocket.close(code=1011, reason="Internal server error")
            except Exception as close_error:
                logger.debug(f"Error closing WebSocket: {close_error}")
    finally:
        # Cleanup - only if connection was established
        if current_user and connection_accepted:
            user_id = getattr(current_user, 'user_id', None) or getattr(current_user, 'id', None)
            if user_id:
                logger.info(f"Cleaning up WebSocket for user {user_id}")
                try:
                    websocket_manager.disconnect(websocket, user_id)
                except Exception as cleanup_error:
                    logger.error(f"Error during WebSocket cleanup for user {user_id}: {cleanup_error}")

async def handle_websocket_message(message_data: str, current_user, websocket):
    """Handle incoming WebSocket messages from client"""
    try:
        data = json.loads(message_data)
        message_type = data.get("type")
        
        if message_type == "ping":
            # Respond to ping messages (keep-alive)
            pong_message = {
                "type": "pong",
                "timestamp": datetime.now().isoformat()
            }
            await websocket.send_text(json.dumps(pong_message))
        
        elif message_type == "mark_as_read":
            # Mark notification as read in real-time
            notification_id = data.get("notification_id")
            if notification_id:
                from app.database import get_db_context
                
                async with get_db_context() as db:
                    success, status_code = await notification_service.mark_as_read(
                        notification_id, current_user.user_id, db
                    )
                    
                    response_message = {
                        "type": "read_status",
                        "notification_id": notification_id,
                        "success": success,
                        "timestamp": datetime.now().isoformat()
                    }
                    await websocket.send_text(json.dumps(response_message))
        
        elif message_type == "get_stats":
            # Return connection statistics (admin only)
            if current_user.is_admin:
                stats = websocket_manager.get_connection_stats()
                stats_message = {
                    "type": "connection_stats",
                    "data": stats,
                    "timestamp": datetime.now().isoformat()
                }
                await websocket.send_text(json.dumps(stats_message))
            else:
                error_message = {
                    "type": "error",
                    "message": "Admin access required",
                    "timestamp": datetime.now().isoformat()
                }
                await websocket.send_text(json.dumps(error_message))
        
        elif message_type == "subscribe":
            # Handle subscription to specific notification types
            channels = data.get("channels", [])
            logger.info(f"User {current_user.user_id} subscribed to channels: {channels}")
            
            subscription_message = {
                "type": "subscription_confirmed",
                "channels": channels,
                "timestamp": datetime.now().isoformat()
            }
            await websocket.send_text(json.dumps(subscription_message))
        
        else:
            error_message = {
                "type": "error", 
                "message": f"Unknown message type: {message_type}",
                "timestamp": datetime.now().isoformat()
            }
            await websocket.send_text(json.dumps(error_message))
            
    except json.JSONDecodeError:
        error_message = {
            "type": "error",
            "message": "Invalid JSON format",
            "timestamp": datetime.now().isoformat()
        }
        await websocket.send_text(json.dumps(error_message))
    except Exception as e:
        logger.error(f"Error handling WebSocket message: {e}")
        error_message = {
            "type": "error",
            "message": "Internal server error",
            "timestamp": datetime.now().isoformat()
        }
        await websocket.send_text(json.dumps(error_message))


@router.get(
    "/websocket/stats",
    response_model=StandardResponse,
    summary="Get WebSocket connection statistics",
    responses={
        200: {"description": "Statistics retrieved successfully"},
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden - Admin access required"},
        500: {"description": "Internal server error"},
    },
)
async def get_websocket_stats(
    current_user_result: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get WebSocket connection statistics (Admin only)"""
    try:
        current_user, auth_status = current_user_result
        if auth_status != status.HTTP_200_OK or not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )
        
        # Check if user is admin
        is_admin = getattr(current_user, 'is_admin', False) or getattr(current_user, 'role', 'user') == 'admin'
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        
        stats = websocket_manager.get_connection_stats()
        return StandardResponse(
            success=True,
            message="WebSocket statistics retrieved",
            data=stats,
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting WebSocket stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve WebSocket statistics"
        )
        
@router.put(
    "/admin/{notification_id}/read",
    response_model=StandardResponse,
    summary="Admin: Mark any notification as read",
    responses={
        200: {"description": "Notification marked as read"},
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden - Admin access required"},
        404: {"description": "Notification not found"},
        500: {"description": "Internal server error"},
    },
)
async def admin_mark_notification_as_read(
    notification_id: int,
    current_user_result: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin: Mark any user's notification as read"""
    try:
        current_user, auth_status = current_user_result
        if auth_status != status.HTTP_200_OK or not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )
        
        # Check if user is admin
        if getattr(current_user, 'role', 'user') != 'admin':
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        
        success, status_code = await notification_service.mark_notification_as_read_admin(
            notification_id, current_user.user_id, db
        )
        
        if not success:
            if status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Notification not found"
                )
            else:
                raise HTTPException(
                    status_code=status_code,
                    detail="Failed to mark notification as read"
                )
        
        return StandardResponse(
            success=True,
            message="Notification marked as read by admin",
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking notification as read (admin): {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark notification as read"
        )


@router.put(
    "/admin/read-all",
    response_model=StandardResponse,
    summary="Admin: Mark all notifications as read",
    responses={
        200: {"description": "All notifications marked as read"},
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden - Admin access required"},
        500: {"description": "Internal server error"},
    },
)
async def admin_mark_all_notifications_as_read(
    target_user_id: Optional[int] = Query(None, description="Specific user ID to mark all as read (optional)"),
    current_user_result: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin: Mark all notifications as read for a specific user or all users"""
    try:
        current_user, auth_status = current_user_result
        if auth_status != status.HTTP_200_OK or not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )
        
        # Check if user is admin
        if getattr(current_user, 'role', 'user') != 'admin':
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        
        success, status_code = await notification_service.mark_all_as_read_admin(
            target_user_id=target_user_id,
            admin_user_id=current_user.user_id,
            db=db
        )
        
        if not success:
            raise HTTPException(
                status_code=status_code,
                detail="Failed to mark all notifications as read"
            )
        
        message = "All notifications marked as read"
        if target_user_id:
            message = f"All notifications for user {target_user_id} marked as read"
        
        return StandardResponse(
            success=True,
            message=message,
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking all notifications as read (admin): {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark all notifications as read"
        )
        
               
        