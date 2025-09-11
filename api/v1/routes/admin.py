# 10 sep2025
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.dependencies import require_admin
from database import get_db_context
from schemas import StandardResponse
from services.config_service import config_service
from services.file_history_service import file_history_service

router = APIRouter(tags=["Admin"], prefix="/admin")

@router.get(
    "/config",
    response_model=StandardResponse,
    summary="Get all system configuration"
)
async def get_system_config(
    current_user = Depends(require_admin),
    db: AsyncSession = Depends(get_db_context)
):
    """Get all system configuration (Admin only)"""
    try:
        config, status_code = await config_service.get_all_config(db)
        
        if status_code != status.HTTP_200_OK:
            raise HTTPException(
                status_code=status_code,
                detail="Failed to retrieve configuration"
            )
        
        return StandardResponse(
            success=True,
            message="Configuration retrieved successfully",
            data=config,
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting system config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve system configuration"
        )

@router.put(
    "/config/{config_key}",
    response_model=StandardResponse,
    summary="Update system configuration"
)
async def update_system_config(
    config_key: str,
    config_data: Dict,
    current_user = Depends(require_admin),
    db: AsyncSession = Depends(get_db_context)
):
    """Update system configuration (Admin only)"""
    try:
        if "value" not in config_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Value field is required"
            )
        
        success, status_code = await config_service.update_config(
            config_key, config_data["value"], db
        )
        
        if not success:
            if status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Configuration key not found"
                )
            elif status_code == status.HTTP_403_FORBIDDEN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Configuration is not editable"
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to update configuration"
                )
        
        return StandardResponse(
            success=True,
            message="Configuration updated successfully",
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating system config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update system configuration"
        )

@router.get(
    "/history/stats",
    response_model=StandardResponse,
    summary="Get file history statistics"
)
async def get_history_statistics(
    days: int = 30,
    current_user = Depends(require_admin),
    db: AsyncSession = Depends(get_db_context)
):
    """Get file history statistics (Admin only)"""
    try:
        stats, status_code = await file_history_service.get_history_stats(db, days)
        
        if status_code != status.HTTP_200_OK:
            raise HTTPException(
                status_code=status_code,
                detail="Failed to retrieve history statistics"
            )
        
        return StandardResponse(
            success=True,
            message="History statistics retrieved successfully",
            data=stats,
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting history stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve history statistics"
        )

@router.post(
    "/history/cleanup",
    response_model=StandardResponse,
    summary="Manual history cleanup"
)
async def manual_history_cleanup(
    current_user = Depends(require_admin),
    db: AsyncSession = Depends(get_db_context)
):
    """Manually trigger history cleanup (Admin only)"""
    try:
        deleted_count, status_code = await file_history_service.cleanup_old_history(db)
        
        if status_code != status.HTTP_200_OK:
            raise HTTPException(
                status_code=status_code,
                detail="Failed to cleanup history"
            )
        
        return StandardResponse(
            success=True,
            message=f"Cleaned up {deleted_count} history records",
            data={"deleted_count": deleted_count},
            status_code=status.HTTP_200_OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during manual cleanup: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cleanup history"
        )