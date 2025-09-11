import logging
from typing import Dict, List, Optional, Tuple

from fastapi import status
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from schemas.files import FileUploadRecord
from services.config_service import config_service
from services.file_history_service import file_history_service

logger = logging.getLogger(__name__)

class FileVersionService:
    async def get_file_versions(
        self,
        s3_key: str,
        db: AsyncSession,
        include_content: bool = False
    ) -> Tuple[Optional[List[Dict]], int]:
        """Get all versions of a file with optional content inclusion"""
        try:
            query = select(FileUploadRecord).where(
                FileUploadRecord.s3_key == s3_key
            ).order_by(FileUploadRecord.version.desc())
            
            if not include_content:
                query = query.options(selectinload(FileUploadRecord.parent_version))
            
            result = await db.execute(query)
            versions = result.scalars().all()
            
            version_list = []
            for version in versions:
                version_data = version.to_dict()
                if not include_content:
                    version_data.pop('file_content', None)
                version_list.append(version_data)
            
            return version_list, status.HTTP_200_OK
            
        except Exception as e:
            logger.error(f"Error getting file versions for {s3_key}: {e}", exc_info=True)
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR
    
    async def get_current_version(
        self,
        s3_key: str,
        db: AsyncSession,
        include_content: bool = False
    ) -> Tuple[Optional[Dict], int]:
        """Get the current version of a file"""
        try:
            query = select(FileUploadRecord).where(
                and_(
                    FileUploadRecord.s3_key == s3_key,
                    FileUploadRecord.is_current_version == True
                )
            )
            
            if not include_content:
                query = query.options(selectinload(FileUploadRecord.parent_version))
            
            result = await db.execute(query)
            current_version = result.scalar_one_or_none()
            
            if not current_version:
                return None, status.HTTP_404_NOT_FOUND
            
            version_data = current_version.to_dict()
            if not include_content:
                version_data.pop('file_content', None)
            
            return version_data, status.HTTP_200_OK
            
        except Exception as e:
            logger.error(f"Error getting current version for {s3_key}: {e}", exc_info=True)
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR
    
    async def create_new_version(
        self,
        db: AsyncSession,
        file_data: Dict,
        user_id: str,
        version_comment: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Tuple[Optional[Dict], int]:
        """Create a new version of a file"""
        try:
            s3_key = file_data["s3_key"]
            original_filename = file_data["original_filename"]
            
            logger.info(f"Creating new version for file: {original_filename}, user: {user_id}")

            # Get current version by original filename (not s3_key)
            result = await db.execute(
                select(FileUploadRecord).where(
                    FileUploadRecord.original_filename == original_filename,
                    FileUploadRecord.is_current_version == True
                )
            )
            current_version = result.scalar_one_or_none()
            
            if not current_version:
                logger.error(f"No current version found for file: {original_filename}")
                return None, status.HTTP_404_NOT_FOUND
        
            logger.info(f"Current version found: v{current_version.version}")
            
            # Mark current version as not current
            current_version.is_current_version = False
            current_version.updated_at = func.now()
            db.add(current_version)
        
            # Create new version
            new_version_number = current_version.version + 1
            logger.info(f"Creating new version: v{new_version_number}")
        
            # Convert user_id to integer
            user_id_int = int(user_id) if user_id and user_id.isdigit() else None
            
            # Create new version record
            new_version = FileUploadRecord(
                original_filename=file_data["original_filename"],
                s3_key=file_data["s3_key"],
                s3_url=file_data["s3_url"],
                file_size=file_data["file_size"],
                content_type=file_data["content_type"],
                file_content=file_data["file_content"],
                score=file_data["score"],
                folder_path=file_data["folder_path"],
                user_id=user_id_int,
                file_metadata=file_data["file_metadata"],
                upload_ip=file_data["upload_ip"],
                processing_time_ms=file_data["processing_time_ms"],
                upload_status=file_data["upload_status"],
                version=new_version_number,
                is_current_version=True,
                parent_version_id=current_version.id,
                version_comment=version_comment,
                created_at=current_version.created_at if current_version.version == 1 else current_version.created_at
            )
            
            # Get max versions configuration
            max_versions, _ = await config_service.get_config("max_file_versions", db)
            max_versions = max_versions or 10
            
            # Clean up old versions if exceeding limit
            await self._cleanup_old_versions(db, original_filename, max_versions)
            
            db.add(new_version)
            await db.commit()
            await db.refresh(new_version)
            
            # Log version creation
            await file_history_service.log_file_action(
                db=db,
                file_upload_id=new_version.id,
                s3_key=s3_key,
                action="version_create",
                action_by=user_id_int,
                action_details={
                    "previous_version": current_version.version,
                    "new_version": new_version_number,
                    "version_comment": version_comment
                },
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            logger.info(f"Created new version {new_version_number} for file {original_filename}")
            
            return new_version.to_dict(), status.HTTP_201_CREATED
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Error creating new version for {file_data['original_filename']}: {e}", exc_info=True)
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR
    
    async def _cleanup_old_versions(
        self,
        db: AsyncSession,
        original_filename: str,  # Changed from s3_key
        max_versions: int
    ) -> int:
        """Clean up old versions beyond the limit"""
        try:
            # Get all versions ordered by version descending
            result = await db.execute(
                select(FileUploadRecord.id, FileUploadRecord.version)
                .where(FileUploadRecord.original_filename == original_filename)  # Changed
                .order_by(FileUploadRecord.version.desc())
            )
            all_versions = result.all()
            
            if len(all_versions) >= max_versions:
                # Get IDs of versions to delete (oldest ones beyond the limit)
                versions_to_delete = [v.id for v in all_versions[max_versions:]]
                
                # Delete old versions
                if versions_to_delete:
                    await db.execute(
                        delete(FileUploadRecord)
                        .where(FileUploadRecord.id.in_(versions_to_delete))
                    )
                    logger.info(f"Cleaned up {len(versions_to_delete)} old versions for {original_filename}")
                    return len(versions_to_delete)
            
            return 0
            
        except Exception as e:
            logger.error(f"Error cleaning up old versions for {original_filename}: {e}")
            return 0
    
    async def restore_version(
        self,
        db: AsyncSession,
        version_id: int,
        user_id: str,
        restore_comment: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Tuple[Optional[Dict], int]:
        """Restore a specific version of a file"""
        try:
            # Get the version to restore
            result = await db.execute(
                select(FileUploadRecord).where(FileUploadRecord.id == version_id)
            )
            version_to_restore = result.scalar_one_or_none()
            
            if not version_to_restore:
                return None, status.HTTP_404_NOT_FOUND
            
            # Get current version
            current_version, status_code = await self.get_current_version(version_to_restore.s3_key, db)
            if status_code != status.HTTP_200_OK:
                return None, status.HTTP_404_NOT_FOUND
            
            # Mark current version as not current
            await db.execute(
                update(FileUploadRecord)
                .where(FileUploadRecord.id == current_version["id"])
                .values(is_current_version=False)
            )
            
            # Create a new version that's a copy of the restored version
            new_version_number = current_version["version"] + 1
            
            # Create copy of the restored version data
            restored_version_data = {
                "original_filename": version_to_restore.original_filename,
                "s3_key": version_to_restore.s3_key,
                "s3_url": version_to_restore.s3_url,
                "file_size": version_to_restore.file_size,
                "content_type": version_to_restore.content_type,
                "file_content": version_to_restore.file_content,
                "score": version_to_restore.score,
                "folder_path": version_to_restore.folder_path,
                "file_metadata": version_to_restore.file_metadata,
                "upload_ip": ip_address,
                "processing_time_ms": 0,
                "upload_status": "restored"
            }
            
            restored_version = FileUploadRecord(
                **restored_version_data,
                user_id=user_id,
                version=new_version_number,
                is_current_version=True,
                parent_version_id=version_to_restore.id,
                version_comment=restore_comment or f"Restored from version {version_to_restore.version}"
            )
            
            db.add(restored_version)
            await db.commit()
            await db.refresh(restored_version)
            
            # Log restoration
            await file_history_service.log_file_action(
                db=db,
                file_upload_id=restored_version.id,
                s3_key=version_to_restore.s3_key,
                action="version_restore",
                action_by=int(user_id) if user_id.isdigit() else user_id,
                action_details={
                    "restored_version": version_to_restore.version,
                    "new_version": new_version_number,
                    "restore_comment": restore_comment
                },
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            logger.info(f"Restored version {version_to_restore.version} as new version {new_version_number}")
            
            return restored_version.to_dict(), status.HTTP_201_CREATED
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Error restoring version {version_id}: {e}", exc_info=True)
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR
    
    async def get_version_content(
        self,
        version_id: int,
        db: AsyncSession
    ) -> Tuple[Optional[str], int]:
        """Get file content for a specific version"""
        try:
            result = await db.execute(
                select(FileUploadRecord.file_content)
                .where(FileUploadRecord.id == version_id)
            )
            content = result.scalar_one_or_none()
            
            if not content:
                return None, status.HTTP_404_NOT_FOUND
            
            return content, status.HTTP_200_OK
            
        except Exception as e:
            logger.error(f"Error getting content for version {version_id}: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR

# Create global instance
file_version_service = FileVersionService()
