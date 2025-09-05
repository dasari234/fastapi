import logging
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db_context
from models.schemas import FileUploadRecord

logger = logging.getLogger(__name__)

class UploadsService:
    async def create_upload_record(
        self,
        original_filename: str,
        s3_key: str,
        s3_url: str,
        file_size: int,
        content_type: str,
        file_content: Optional[str] = None,
        score: float = 0.0,
        folder_path: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        upload_ip: Optional[str] = None,
        upload_status: str = "success",
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Create a new file upload record"""
        async def _create_record(session: AsyncSession):
            upload_record = FileUploadRecord(
                original_filename=original_filename,
                s3_key=s3_key,
                s3_url=s3_url,
                file_size=file_size,
                content_type=content_type,
                file_content=file_content,
                score=score,
                folder_path=folder_path,
                user_id=user_id,
                file_metadata=metadata,  # Changed from metadata to file_metadata
                upload_ip=upload_ip,
                upload_status=upload_status
            )
            
            session.add(upload_record)
            await session.commit()
            await session.refresh(upload_record)
            
            return {
                "id": upload_record.id,
                "original_filename": upload_record.original_filename,
                "s3_key": upload_record.s3_key,
                "s3_url": upload_record.s3_url,
                "file_size": upload_record.file_size,
                "content_type": upload_record.content_type,
                "file_content": upload_record.file_content,
                "score": upload_record.score,
                "folder_path": upload_record.folder_path,
                "user_id": upload_record.user_id,
                "metadata": upload_record.file_metadata,  # Map back to metadata in response
                "upload_ip": upload_record.upload_ip,
                "upload_status": upload_record.upload_status,
                "created_at": upload_record.created_at.isoformat(),
                "updated_at": upload_record.updated_at.isoformat()
            }
        
        if db:
            return await _create_record(db)
        else:
            async with get_db_context() as session:
                return await _create_record(session)

    async def list_uploads(
        self,
        user_id: Optional[str] = None,
        folder: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        db: AsyncSession = None
    ) -> Dict[str, Any]:
        """List file uploads with filtering and pagination"""
        async def _list_uploads(session: AsyncSession):
            query = select(FileUploadRecord)
            
            if user_id:
                query = query.where(FileUploadRecord.user_id == user_id)
            if folder:
                query = query.where(FileUploadRecord.folder_path == folder)
            
            # Count total
            count_query = query.with_only_columns(func.count()).order_by(None)
            total_count_result = await session.execute(count_query)
            total_count = total_count_result.scalar()
            
            # Get paginated results
            query = query.order_by(FileUploadRecord.created_at.desc()).offset(offset).limit(limit)
            result = await session.execute(query)
            uploads = result.scalars().all()
            
            records = [
                {
                    "id": upload.id,
                    "original_filename": upload.original_filename,
                    "s3_key": upload.s3_key,
                    "s3_url": upload.s3_url,
                    "file_size": upload.file_size,
                    "content_type": upload.content_type,
                    "file_content": upload.file_content,
                    "score": upload.score,
                    "folder_path": upload.folder_path,
                    "user_id": upload.user_id,
                    "metadata": upload.file_metadata,  # Map back to metadata in response
                    "upload_ip": upload.upload_ip,
                    "upload_status": upload.upload_status,
                    "created_at": upload.created_at.isoformat(),
                    "updated_at": upload.updated_at.isoformat()
                } for upload in uploads
            ]
            
            return {
                "records": records,
                "total_count": total_count
            }
        
        if db:
            return await _list_uploads(db)
        else:
            async with get_db_context() as session:
                return await _list_uploads(session)

    async def get_upload_record(self, s3_key: str, db: AsyncSession = None) -> Optional[Dict[str, Any]]:
        """Get a specific upload record by S3 key"""
        async def _get_record(session: AsyncSession):
            result = await session.execute(
                select(FileUploadRecord).where(FileUploadRecord.s3_key == s3_key)
            )
            upload = result.scalar_one_or_none()
            
            if upload:
                return {
                    "id": upload.id,
                    "original_filename": upload.original_filename,
                    "s3_key": upload.s3_key,
                    "s3_url": upload.s3_url,
                    "file_size": upload.file_size,
                    "content_type": upload.content_type,
                    "file_content": upload.file_content,
                    "score": upload.score,
                    "folder_path": upload.folder_path,
                    "user_id": upload.user_id,
                    "metadata": upload.file_metadata,  # Map back to metadata in response
                    "upload_ip": upload.upload_ip,
                    "upload_status": upload.upload_status,
                    "created_at": upload.created_at.isoformat(),
                    "updated_at": upload.updated_at.isoformat()
                }
            return None
        
        if db:
            return await _get_record(db)
        else:
            async with get_db_context() as session:
                return await _get_record(session)

    async def delete_upload_record(self, s3_key: str, db: AsyncSession = None) -> bool:
        """Delete an upload record by S3 key"""
        async def _delete_record(session: AsyncSession):
            result = await session.execute(
                select(FileUploadRecord).where(FileUploadRecord.s3_key == s3_key)
            )
            upload = result.scalar_one_or_none()
            
            if upload:
                await session.delete(upload)
                await session.commit()
                return True
            return False
        
        if db:
            return await _delete_record(db)
        else:
            async with get_db_context() as session:
                return await _delete_record(session)

# Create global instance
uploads_service = UploadsService()