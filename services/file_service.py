import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db_context
from schemas.files import FileUploadRecord
from schemas.users import User

logger = logging.getLogger(__name__)


class FileService:
    async def create_upload_record(
        self,
        original_filename: str,
        s3_key: str,
        s3_url: str,
        file_size: int,
        content_type: str,
        file_content: str,
        score: float,
        folder_path: Optional[str],
        user_id: str,  # This comes as string '3'
        metadata: Optional[Dict],
        upload_ip: str,
        processing_time_ms: float,
        version_comment: Optional[str] = None,
        db: AsyncSession = None,
    ) -> Tuple[Optional[Dict], int]:
        """Create upload record with versioning support"""

        async def _create_record(session: AsyncSession) -> Tuple[Optional[Dict], int]:
            try:
                # Check if file already exists using FileUploadRecord
                user_id_int = int(user_id) if user_id and user_id.isdigit() else None
                # DEBUG: Check what we're looking for
                logger.info(f"Looking for existing file: filename='{original_filename}', user_id={user_id_int}")
            
                result = await session.execute(
                    select(FileUploadRecord).where(
                        FileUploadRecord.original_filename == original_filename,
                        FileUploadRecord.user_id == user_id_int,
                    )
                )
                existing_files = result.scalars().all()
                logger.info(f"Found {len(existing_files)} existing files with same name and user")

                if existing_files:
                    current_version = max(existing_files, key=lambda x: x.version)
                    logger.info(f"Current version: {current_version.version}, new version will be: {current_version.version + 1}")
                    # File exists, create new version using version service
                    from services.file_version_service import \
                        file_version_service

                    new_file_data = {
                        "original_filename": original_filename,
                        "s3_key": s3_key,
                        "s3_url": s3_url,
                        "file_size": file_size,
                        "content_type": content_type,
                        "file_content": file_content,
                        "score": score,
                        "folder_path": folder_path,
                        "file_metadata": metadata,
                        "upload_ip": upload_ip,
                        "processing_time_ms": processing_time_ms,
                        "upload_status": "success",
                    }

                    (
                        new_version,
                        status_code,
                    ) = await file_version_service.create_new_version(
                        session, new_file_data, user_id, version_comment
                    )
                    
                    logger.info(f"File version service returned: status={status_code}, version={new_version}")
                    if status_code != status.HTTP_201_CREATED:
                        return None, status_code

                    return {
                        "id": new_version["id"],
                        "s3_key": new_version["s3_key"],
                        "version": new_version["version"],
                        "is_new_version": True,
                    }, status.HTTP_201_CREATED
                else:
                    # New file, create first version
                    logger.info("No existing file found, creating first version")
                    file_upload = FileUploadRecord(
                        original_filename=original_filename,
                        s3_key=s3_key,
                        s3_url=s3_url,
                        file_size=file_size,
                        content_type=content_type,
                        file_content=file_content,
                        score=score,
                        folder_path=folder_path,
                        user_id=user_id_int,
                        file_metadata=metadata,
                        upload_ip=upload_ip,
                        processing_time_ms=processing_time_ms,
                        version=1,
                        is_current_version=True,
                        version_comment=version_comment or "Initial version",
                    )

                    session.add(file_upload)
                    await session.commit()
                    await session.refresh(file_upload)

                    return {
                        "id": file_upload.id,
                        "s3_key": file_upload.s3_key,
                        "version": file_upload.version,
                        "is_new_version": False,
                    }, status.HTTP_201_CREATED

            except Exception as e:
                await session.rollback()
                logger.error(f"Error creating upload record: {e}", exc_info=True)
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR

        if db:
            return await _create_record(db)
        else:
            async with get_db_context() as session:
                return await _create_record(session)
            
    async def get_file_versions(
        self, s3_key: str, user_id: Optional[str] = None, db: AsyncSession = None
    ) -> Tuple[Optional[List[Dict[str, Any]]], int]:
        """Get all versions of a file with access control"""

        async def _get_versions(
            session: AsyncSession,
        ) -> Tuple[Optional[List[Dict[str, Any]]], int]:
            try:
                # First get the file records
                query = select(FileUploadRecord).where(
                    FileUploadRecord.s3_key == s3_key
                )

                # Non-admin users can only see their own files
                if user_id:
                    query = query.where(FileUploadRecord.user_id == user_id)

                query = query.order_by(FileUploadRecord.version.desc())

                result = await session.execute(query)
                uploads = result.scalars().all()

                if not uploads:
                    return None, status.HTTP_404_NOT_FOUND

                # Get user details separately
                user_ids = list(
                    set(str(upload.user_id) for upload in uploads if upload.user_id)
                )
                users_dict = {}

                if user_ids:
                    try:
                        int_user_ids = [
                            int(uid) for uid in user_ids if uid and uid.isdigit()
                        ]
                        if int_user_ids:
                            users_query = select(User).where(User.id.in_(int_user_ids))
                            users_result = await session.execute(users_query)
                            users = users_result.scalars().all()
                            users_dict = {str(user.id): user for user in users}
                    except ValueError as e:
                        logger.warning(f"Error converting user IDs to integers: {e}")

                versions_data = []
                for version in uploads:
                    user = users_dict.get(version.user_id) if version.user_id else None

                    versions_data.append(
                        {
                            "id": version.id,
                            "original_filename": version.original_filename,
                            "s3_key": version.s3_key,
                            "s3_url": version.s3_url,
                            "file_size": version.file_size,
                            "content_type": version.content_type,
                            "score": version.score,
                            "processing_time_ms": version.processing_time_ms,
                            "version": version.version,
                            "is_current_version": version.is_current_version,
                            "parent_version_id": version.parent_version_id,
                            "user_id": version.user_id,
                            "user_details": {
                                "first_name": user.first_name if user else "Unknown",
                                "last_name": user.last_name if user else "User",
                                "email": user.email if user else "unknown@example.com",
                            }
                            if user
                            else None,
                            "created_at": version.created_at.isoformat()
                            if version.created_at
                            else None,
                            "upload_status": version.upload_status,
                        }
                    )

                return versions_data, status.HTTP_200_OK

            except Exception as e:
                logger.error(
                    f"Error getting file versions for {s3_key}: {e}", exc_info=True
                )
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR

        if db:
            return await _get_versions(db)
        else:
            async with get_db_context() as session:
                return await _get_versions(session)

    async def get_current_version(
        self, s3_key: str, user_id: Optional[str] = None, db: AsyncSession = None
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Get the current version of a file with access control"""

        async def _get_current_version(
            session: AsyncSession,
        ) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                # Build query for current version
                query = select(FileUploadRecord).where(
                    and_(
                        FileUploadRecord.s3_key == s3_key,
                        FileUploadRecord.is_current_version == True,
                    )
                )

                # Non-admin users can only see their own files
                if user_id:
                    query = query.where(FileUploadRecord.user_id == user_id)

                result = await session.execute(query)
                version = result.scalar_one_or_none()

                if not version:
                    return None, status.HTTP_404_NOT_FOUND

                # Get user details separately
                user = None
                if version.user_id:
                    try:
                        user_id_int = int(version.user_id)
                        user_result = await session.execute(
                            select(User).where(User.id == user_id_int)
                        )
                        user = user_result.scalar_one_or_none()
                    except ValueError:
                        logger.warning(f"Invalid user ID format: {version.user_id}")

                version_data = {
                    "id": version.id,
                    "original_filename": version.original_filename,
                    "s3_key": version.s3_key,
                    "s3_url": version.s3_url,
                    "file_size": version.file_size,
                    "content_type": version.content_type,
                    "file_content": version.file_content,
                    "score": version.score,
                    "folder_path": version.folder_path,
                    "user_id": version.user_id,
                    "user_details": {
                        "first_name": user.first_name if user else "Unknown",
                        "last_name": user.last_name if user else "User",
                        "email": user.email if user else "unknown@example.com",
                    }
                    if user
                    else None,
                    "metadata": version.file_metadata,
                    "upload_ip": version.upload_ip,
                    "upload_status": version.upload_status,
                    "processing_time_ms": version.processing_time_ms,
                    "version": version.version,
                    "is_current_version": version.is_current_version,
                    "parent_version_id": version.parent_version_id,
                    "created_at": version.created_at.isoformat()
                    if version.created_at
                    else None,
                    "updated_at": version.updated_at.isoformat()
                    if version.updated_at
                    else None,
                }

                return version_data, status.HTTP_200_OK

            except Exception as e:
                logger.error(
                    f"Error getting current version for {s3_key}: {e}", exc_info=True
                )
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR

        if db:
            return await _get_current_version(db)
        else:
            async with get_db_context() as session:
                return await _get_current_version(session)

    async def list_current_versions(
        self,
        user_id: Optional[str] = None,
        folder: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: str = "desc",
        limit: int = 100,
        offset: int = 0,
        db: AsyncSession = None,
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """List only current versions of files with filtering, search, sorting and pagination"""

        async def _list_current_versions(
            session: AsyncSession,
        ) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                # Validate and convert limit/offset to ensure they are integers
                try:
                    valid_limit = int(limit) if limit is not None else 100
                    valid_offset = int(offset) if offset is not None else 0
                except (ValueError, TypeError):
                    valid_limit = 100
                    valid_offset = 0
                    logger.warning(f"Invalid limit/offset values: limit={limit}, offset={offset}, using defaults")
                
                # Ensure sort_order has a valid value
                valid_sort_order = str(sort_order).lower() if sort_order else "desc"
                if valid_sort_order not in ["asc", "desc"]:
                    valid_sort_order = "desc"
                    logger.warning(f"Invalid sort_order: {sort_order}, defaulting to 'desc'")

                # Convert sort_by to string and handle None case
                sort_by_str = str(sort_by) if sort_by is not None else None
                
                logger.info(
                    f"list_current_versions received: user_id={user_id}, folder={folder}, search={search}, sort_by={sort_by_str}, sort_order={valid_sort_order}, limit={valid_limit}, offset={valid_offset}"
                )
                
                # First get the file records (current versions only)
                query = select(FileUploadRecord).where(
                    FileUploadRecord.is_current_version == True
                )

                if user_id:
                    user_id_int = int(user_id)
                    query = query.where(FileUploadRecord.user_id == user_id_int)
                    logger.info(
                        f"Filtering by user_id (converted to int): {user_id_int}"
                    )
                if folder:
                    query = query.where(FileUploadRecord.folder_path == folder)
                    logger.info(f"Filtering by folder: {folder}")

                # Add search functionality (file fields only)
                if search:
                    search_filter = or_(
                        FileUploadRecord.original_filename.ilike(f"%{search}%"),
                        FileUploadRecord.s3_key.ilike(f"%{search}%"),
                        FileUploadRecord.content_type.ilike(f"%{search}%"),
                        FileUploadRecord.file_content.ilike(f"%{search}%"),
                    )
                    query = query.where(search_filter)
                    logger.info(f"Applying search: {search}")

                # Apply sorting - safely handle sort_by parameter
                sort_column = None
                join_users = False  # Flag to indicate if we need to join with users table

                if sort_by_str:
                    sort_by_lower = str(sort_by_str).lower()
                    logger.info(f"Attempting to sort by: '{sort_by_lower}'")
                    
                    # Map sort_by parameter to actual column names
                    sort_mapping = {
                        "original_filename": FileUploadRecord.original_filename,
                        "filename": FileUploadRecord.original_filename,
                        "size": FileUploadRecord.file_size,
                        "file_size": FileUploadRecord.file_size,
                        "type": FileUploadRecord.content_type,
                        "content_type": FileUploadRecord.content_type,
                        "score": FileUploadRecord.score,
                        "created": FileUploadRecord.created_at,
                        "created_at": FileUploadRecord.created_at,
                        "updated": FileUploadRecord.updated_at,
                        "updated_at": FileUploadRecord.updated_at,
                        "version": FileUploadRecord.version,
                        # User-related sorting
                        "user_firstname": User.first_name,
                        "first_name": User.first_name,
                        "firstname": User.first_name,
                        "user_lastname": User.last_name,
                        "last_name": User.last_name,
                        "lastname": User.last_name,
                        "user_email": User.email,
                        "email": User.email,
                        "user": User.first_name, 
                    }
                    
                    if sort_by_lower in sort_mapping:
                        sort_column = sort_mapping[sort_by_lower]
                        
                        # Check if we need to join with users table
                        if sort_by_lower in ["user_firstname", "first_name", "firstname", 
                                        "user_lastname", "last_name", "lastname", 
                                        "user_email", "email", "user"]:
                            join_users = True
                            logger.info(f"Will join with users table for sorting by {sort_by_lower}")
                        
                        if valid_sort_order == "asc":
                            query = query.order_by(sort_column.asc())
                            logger.info(f"Sorting by {sort_by_lower} in ASCENDING order")
                        else:
                            query = query.order_by(sort_column.desc())
                            logger.info(f"Sorting by {sort_by_lower} in DESCENDING order")
                    else:
                        logger.warning(f"Invalid sort_by parameter: '{sort_by_lower}'. Valid options: {list(sort_mapping.keys())}")
                
                # Join with users table if needed for sorting
                if join_users:
                    query = query.join(User, FileUploadRecord.user_id == User.id)
                    logger.info("Joined with users table for sorting")
                
                # Default sorting if no sort specified
                if not sort_column:
                    query = query.order_by(FileUploadRecord.created_at.desc())
                    logger.info("Using default sorting by created_at desc")

                # Count total current versions
                count_query = query.with_only_columns(func.count()).order_by(None)
                total_count_result = await session.execute(count_query)
                total_count = total_count_result.scalar() or 0

                logger.info(f"Total records found: {total_count}")

                # Get paginated results - use validated limit/offset
                query = query.offset(valid_offset).limit(valid_limit)
                result = await session.execute(query)
                uploads = result.scalars().all()

                logger.info(f"Retrieved {len(uploads)} records from database")

                # Get user IDs for user details
                user_ids = list(
                    set(
                        upload.user_id
                        for upload in uploads
                        if upload.user_id is not None
                    )
                )
                users_dict = {}

                if user_ids:
                    try:
                        logger.info(f"Fetching user details for user IDs: {user_ids}")
                        # Get users with their details
                        users_query = select(
                            User.id,
                            User.first_name,
                            User.last_name,
                            User.email
                        ).where(User.id.in_(user_ids))
                        users_result = await session.execute(users_query)
                        users = users_result.all()
                        
                        # Create dictionary with user details
                        users_dict = {
                            user_id: {
                                "first_name": first_name,
                                "last_name": last_name,
                                "email": email
                            }
                            for user_id, first_name, last_name, email in users
                        }
                        logger.info(f"Found {len(users_dict)} users")

                    except Exception as e:
                        logger.error(f"Error fetching user details: {e}", exc_info=True)

                records = []
                for upload_record in uploads:
                    user_details = (
                        users_dict.get(upload_record.user_id)
                        if upload_record.user_id
                        else None
                    )

                    # Debug logging
                    if upload_record.user_id and user_details is None:
                        logger.warning(
                            f"User not found for user_id: {upload_record.user_id}"
                        )

                    records.append(
                        {
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
                            "user_details": user_details,
                            "metadata": upload_record.file_metadata,
                            "upload_ip": upload_record.upload_ip,
                            "upload_status": upload_record.upload_status,
                            "processing_time_ms": upload_record.processing_time_ms,
                            "version": upload_record.version,
                            "is_current_version": upload_record.is_current_version,
                            "parent_version_id": upload_record.parent_version_id,
                            "created_at": upload_record.created_at.isoformat()
                            if upload_record.created_at
                            else None,
                            "updated_at": upload_record.updated_at.isoformat()
                            if upload_record.updated_at
                            else None,
                        }
                    )

                return {
                    "records": records,
                    "total_count": total_count,
                    "search_query": search,
                    "sort_by": sort_by_str,
                    "sort_order": valid_sort_order,
                }, status.HTTP_200_OK

            except Exception as e:
                logger.error(f"Error listing current versions: {e}", exc_info=True)
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR

        if db:
            return await _list_current_versions(db)
        else:
            async with get_db_context() as session:
                return await _list_current_versions(session)
        
    async def list_uploads(
        self,
        user_id: Optional[str] = None,
        folder: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        db: AsyncSession = None,
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """List file uploads with filtering, search and pagination (all versions)"""

        async def _list_uploads(
            session: AsyncSession,
        ) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                # First get the file records (all versions)
                query = select(FileUploadRecord)

                if user_id:
                    all_user_ids_result = await session.execute(
                        select(FileUploadRecord.user_id).distinct()
                    )
                    all_user_ids = [
                        str(uid[0]) for uid in all_user_ids_result.all() if uid[0]
                    ]
                    logger.info(f"Available user_ids in file_uploads: {all_user_ids}")

                    query = query.where(FileUploadRecord.user_id == user_id)
                    logger.info(f"Applying user_id filter: {user_id}")

                if folder:
                    query = query.where(FileUploadRecord.folder_path == folder)
                    logger.info(f"Applying folder filter: {folder}")

                # Add search functionality (file fields only)
                if search:
                    search_filter = or_(
                        FileUploadRecord.original_filename.ilike(f"%{search}%"),
                        FileUploadRecord.s3_key.ilike(f"%{search}%"),
                        FileUploadRecord.content_type.ilike(f"%{search}%"),
                        FileUploadRecord.file_content.ilike(f"%{search}%"),
                    )
                    query = query.where(search_filter)
                    logger.info(f"Applying search filter: {search}")

                # Count total (all versions)
                count_query = query.with_only_columns(func.count()).order_by(None)
                total_count_result = await session.execute(count_query)
                total_count = total_count_result.scalar() or 0

                logger.info(f"Total count: {total_count}")

                # Get paginated results
                query = (
                    query.order_by(FileUploadRecord.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
                result = await session.execute(query)
                uploads = result.scalars().all()

                logger.info(f"Found {len(uploads)} upload records")

                # Get user details separately
                user_ids = list(
                    set(str(upload.user_id) for upload in uploads if upload.user_id)
                )
                users_dict = {}

                if user_ids:
                    logger.info(f"Fetching user details for user_ids: {user_ids}")
                    try:
                        # Convert user_ids to integers for the User table
                        int_user_ids = []
                        for uid in user_ids:
                            try:
                                int_user_ids.append(int(uid))
                            except (ValueError, TypeError):
                                logger.warning(f"Skipping invalid user ID: {uid}")

                        if int_user_ids:
                            users_query = select(User).where(User.id.in_(int_user_ids))
                            users_result = await session.execute(users_query)
                            users = users_result.scalars().all()
                            users_dict = {str(user.id): user for user in users}
                            logger.info(f"Found {len(users_dict)} users")
                    except Exception as e:
                        logger.error(f"Error fetching user details: {e}", exc_info=True)

                records = []
                for upload_record in uploads:
                    user = (
                        users_dict.get(upload_record.user_id)
                        if upload_record.user_id
                        else None
                    )

                    records.append(
                        {
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
                            "user_details": {
                                "first_name": user.first_name if user else "Unknown",
                                "last_name": user.last_name if user else "User",
                                "email": user.email if user else "unknown@example.com",
                            }
                            if user
                            else None,
                            "metadata": upload_record.file_metadata,
                            "upload_ip": upload_record.upload_ip,
                            "upload_status": upload_record.upload_status,
                            "processing_time_ms": upload_record.processing_time_ms,
                            "version": upload_record.version,
                            "is_current_version": upload_record.is_current_version,
                            "parent_version_id": upload_record.parent_version_id,
                            "created_at": upload_record.created_at.isoformat()
                            if upload_record.created_at
                            else None,
                            "updated_at": upload_record.updated_at.isoformat()
                            if upload_record.updated_at
                            else None,
                        }
                    )

                logger.info(f"Returning {len(records)} records")

                return {
                    "records": records,
                    "total_count": total_count,
                    "search_query": search,
                }, status.HTTP_200_OK

            except Exception as e:
                logger.error(f"Error listing uploads: {e}", exc_info=True)
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR

        if db:
            return await _list_uploads(db)
        else:
            async with get_db_context() as session:
                return await _list_uploads(session)

    async def get_upload_record(
        self, s3_key: str, db: AsyncSession = None
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Get a specific upload record by S3 key with status codes"""

        async def _get_record(
            session: AsyncSession,
        ) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                result = await session.execute(
                    select(FileUploadRecord).where(FileUploadRecord.s3_key == s3_key)
                )
                record = result.scalar_one_or_none()

                if not record:
                    return None, status.HTTP_404_NOT_FOUND

                record_dict = record.to_dict()
                return record_dict, status.HTTP_200_OK

                # record_data = {
                #     "id": upload.id,
                #     "original_filename": upload.original_filename,
                #     "s3_key": upload.s3_key,
                #     "s3_url": upload.s3_url,
                #     "file_size": upload.file_size,
                #     "content_type": upload.content_type,
                #     "file_content": upload.file_content,
                #     "score": upload.score,
                #     "folder_path": upload.folder_path,
                #     "user_id": upload.user_id,
                #     "metadata": upload.file_metadata,
                #     "upload_ip": upload.upload_ip,
                #     "upload_status": upload.upload_status,
                #     "created_at": upload.created_at.isoformat()
                #     if upload.created_at
                #     else None,
                #     "updated_at": upload.updated_at.isoformat()
                #     if upload.updated_at
                #     else None,
                # }

                # return record_data, status.HTTP_200_OK

            except Exception as e:
                logger.error(
                    f"Error getting upload record {s3_key}: {e}", exc_info=True
                )
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR

        if db:
            return await _get_record(db)
        else:
            async with get_db_context() as session:
                return await _get_record(session)

    async def delete_upload_record(
        self, s3_key: str, db: AsyncSession = None
    ) -> Tuple[bool, int]:
        """Delete an upload record by S3 key with status codes"""

        async def _delete_record(session: AsyncSession) -> Tuple[bool, int]:
            try:
                result = await session.execute(
                    select(FileUploadRecord).where(FileUploadRecord.s3_key == s3_key)
                )
                upload = result.scalar_one_or_none()

                if not upload:
                    return False, status.HTTP_404_NOT_FOUND

                await session.delete(upload)
                await session.commit()
                return True, status.HTTP_200_OK

            except Exception as e:
                await session.rollback()
                logger.error(f"Error deleting upload record {s3_key}: {e}")
                return False, status.HTTP_500_INTERNAL_SERVER_ERROR

        if db:
            return await _delete_record(db)
        else:
            async with get_db_context() as session:
                return await _delete_record(session)

    async def update_upload_record(
        self, s3_key: str, updates: Dict[str, Any], db: AsyncSession = None
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """Update an upload record with status codes"""

        async def _update_record(
            session: AsyncSession,
        ) -> Tuple[Optional[Dict[str, Any]], int]:
            try:
                result = await session.execute(
                    select(FileUploadRecord).where(FileUploadRecord.s3_key == s3_key)
                )
                upload = result.scalar_one_or_none()

                if not upload:
                    return None, status.HTTP_404_NOT_FOUND

                # Apply updates
                for key, value in updates.items():
                    if hasattr(upload, key):
                        setattr(upload, key, value)

                await session.commit()
                await session.refresh(upload)

                record_data = {
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
                    "metadata": upload.file_metadata,
                    "upload_ip": upload.upload_ip,
                    "upload_status": upload.upload_status,
                    "created_at": upload.created_at.isoformat()
                    if upload.created_at
                    else None,
                    "updated_at": upload.updated_at.isoformat()
                    if upload.updated_at
                    else None,
                }

                return record_data, status.HTTP_200_OK

            except Exception as e:
                await session.rollback()
                logger.error(f"Error updating upload record {s3_key}: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR

        if db:
            return await _update_record(db)
        else:
            async with get_db_context() as session:
                return await _update_record(session)


# Create global instance
file_service = FileService()
