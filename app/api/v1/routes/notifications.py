from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_db_session
from app.schemas.base import StandardResponse
from app.services.notification_service import notification_service

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
        
        result, status_code = await notification_service.get_user_notifications(
            current_user.user_id, limit, offset, unread_only, db
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