from typing import Dict, Optional, Tuple
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from fastapi import HTTPException, status, UploadFile
from loguru import logger
from io import BytesIO
from app.config import (AWS_ACCESS_KEY_ID, AWS_REGION, AWS_SECRET_ACCESS_KEY,
                        S3_BUCKET_NAME)


class S3Service:
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        self.bucket_name = S3_BUCKET_NAME

    async def upload_file(self, file: UploadFile, filename: str, folder: Optional[str] = None) -> dict:
        """Upload file to S3 bucket and return presigned URL"""
        try:
            # DEBUG: Log all input parameters
            logger.debug(f"upload_file called with: file={file}, filename='{filename}', folder='{folder}'")
            logger.debug(f"File attributes: filename='{getattr(file, 'filename', 'MISSING')}', content_type='{getattr(file, 'content_type', 'MISSING')}', size={getattr(file, 'size', 'MISSING')}")
            
            # Validate input parameters with detailed error messages
            if file is None:
                raise ValueError("File object cannot be None")
            
            if filename is None:
                raise ValueError("Filename cannot be None")
            
            if not isinstance(filename, str):
                raise ValueError(f"Filename must be a string, got {type(filename)}: {filename}")
            
            filename = filename.strip()
            if not filename:
                raise ValueError("Filename cannot be empty or whitespace only")
            
            # DEBUG: Check folder value
            if folder is not None:
                if not isinstance(folder, str):
                    raise ValueError(f"Folder must be a string or None, got {type(folder)}: {folder}")
                folder = folder.strip()
                if not folder:
                    folder = None  # Treat empty string as None
            
            # Read file content first to get actual size and content
            try:
                file_content = await file.read()
                logger.debug(f"Read file content: type={type(file_content)}, length={len(file_content) if file_content else 'EMPTY'}")
                
                if file_content is None:
                    raise ValueError("File content is None after reading")
                
                if len(file_content) == 0:
                    raise ValueError("File is empty (0 bytes)")
                    
            except Exception as read_error:
                logger.error(f"Error reading file content: {read_error}")
                raise ValueError(f"Failed to read file: {read_error}")
            
            finally:
                # Always reset file pointer
                await file.seek(0)
            
            # Generate S3 key safely
            s3_key = filename
            if folder:
                # Clean folder path
                folder = folder.strip('/')
                s3_key = f"{folder}/{filename}"
            
            logger.debug(f"Generated S3 key: '{s3_key}'")
            
            # Get content type safely
            content_type = getattr(file, 'content_type', None)
            if content_type is None or not isinstance(content_type, str) or not content_type.strip():
                content_type = "application/octet-stream"
                logger.debug(f"Using default content type: {content_type}")
            else:
                logger.debug(f"Using file content type: {content_type}")
            
            # DEBUG: Check S3 client and bucket
            logger.debug(f"S3 client: {type(self.s3_client)}, bucket: '{self.bucket_name}'")
            if not self.bucket_name or not isinstance(self.bucket_name, str):
                raise ValueError(f"Invalid bucket name: {self.bucket_name}")
            
            # Upload file using BytesIO
            try:
                logger.debug("Starting S3 upload...")
                self.s3_client.upload_fileobj(
                    BytesIO(file_content),
                    self.bucket_name,
                    s3_key,
                    ExtraArgs={
                        'ContentType': content_type,
                    }
                )
                logger.debug("S3 upload completed successfully")
                
            except Exception as upload_error:
                logger.error(f"S3 upload_fileobj failed: {upload_error}")
                # Re-raise to be caught by outer exception handler
                raise
            
            # Generate presigned URL
            try:
                logger.debug("Generating presigned URL...")
                file_url = self.s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': self.bucket_name, 'Key': s3_key},
                    ExpiresIn=604800  # 7 days
                )
                logger.debug(f"Generated presigned URL: {file_url[:100]}...")
                
            except Exception as url_error:
                logger.error(f"Failed to generate presigned URL: {url_error}")
                # Still return success but without URL
                file_url = f"https://{self.bucket_name}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"
            
            return {
                "success": True,
                "filename": filename,
                "s3_key": s3_key,
                "file_url": file_url,
                "file_size": len(file_content),
                "content_type": content_type,
                "url_expires_in": 604800
            }
            
        except ValueError as e:
            logger.error(f"Validation error in upload_file: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        except NoCredentialsError:
            logger.error("AWS credentials not found")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AWS credentials not configured. Check AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables."
            )
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"AWS ClientError during upload: {error_code} - {error_message}")
            
            if error_code == 'NoSuchBucket':
                detail = f"S3 bucket '{self.bucket_name}' not found or inaccessible"
            elif error_code == 'AccessDenied':
                detail = "Access denied to S3 bucket. Check IAM permissions."
            elif error_code == 'InvalidAccessKeyId':
                detail = "Invalid AWS access key ID"
            elif error_code == 'SignatureDoesNotMatch':
                detail = "AWS secret access key is invalid"
            else:
                detail = f"S3 operation failed: {error_message}"
                
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=detail
            )
        except Exception as e:
            logger.error(f"Unexpected error during upload: {e}", exc_info=True)
            # Add more specific error message
            error_detail = str(e)
            if "NoneType" in error_detail:
                error_detail = "A None value was passed where a string or bytes-like object was expected. Check file content and parameters."
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Upload failed: {error_detail}"
            )

    async def delete_file(self, s3_key: str) -> Tuple[bool, int]:
        """Delete file from S3 bucket"""
        try:
            logger.debug(f"delete_file called with s3_key: '{s3_key}'")
            
            if not s3_key or not isinstance(s3_key, str):
                logger.error(f"Invalid S3 key: {s3_key}")
                return False, status.HTTP_400_BAD_REQUEST
                
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info(f"Successfully deleted file from S3: {s3_key}")
            return True, status.HTTP_200_OK
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchKey':
                logger.warning(f"File not found in S3: {s3_key}")
                return False, status.HTTP_404_NOT_FOUND
            else:
                logger.error(f"Error deleting file from S3 {s3_key}: {e}")
                return False, status.HTTP_500_INTERNAL_SERVER_ERROR
            
        except Exception as e:
            logger.error(f"Unexpected error deleting file from S3 {s3_key}: {e}")
            return False, status.HTTP_500_INTERNAL_SERVER_ERROR
        
    async def generate_presigned_url(
        self, 
        s3_key: str, 
        expiration: int = 3600,
        download: bool = False
    ) -> Tuple[Optional[str], int]:
        """
        Generate pre-signed URL for S3 object
        """
        try:
            logger.debug(f"generate_presigned_url called with s3_key: '{s3_key}', expiration: {expiration}, download: {download}")
            
            if not s3_key or not isinstance(s3_key, str):
                return None, status.HTTP_400_BAD_REQUEST
                
            # Extract filename for content disposition
            filename = s3_key.split('/')[-1] if '/' in s3_key else s3_key
            
            # Determine content disposition
            content_disposition = 'attachment' if download else 'inline'
            
            # Generate presigned URL
            presigned_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': s3_key,
                    'ResponseContentDisposition': f'{content_disposition}; filename="{filename}"'
                },
                ExpiresIn=expiration
            )
            
            logger.info(f"Generated pre-signed URL for {s3_key}, expires in {expiration} seconds")
            return presigned_url, status.HTTP_200_OK
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            logger.error(f"AWS ClientError generating pre-signed URL for {s3_key}: {error_code} - {e}")
            
            if error_code == 'NoSuchKey':
                return None, status.HTTP_404_NOT_FOUND
            elif error_code == 'AccessDenied':
                return None, status.HTTP_403_FORBIDDEN
            else:
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR
                
        except Exception as e:
            logger.error(f"Unexpected error generating pre-signed URL for {s3_key}: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR

    async def get_file_info(self, s3_key: str) -> Tuple[Optional[Dict], int]:
        """Get file metadata from S3"""
        try:
            logger.debug(f"get_file_info called with s3_key: '{s3_key}'")
            
            if not s3_key or not isinstance(s3_key, str):
                return None, status.HTTP_400_BAD_REQUEST
                
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            
            file_info = {
                "content_type": response.get('ContentType', 'application/octet-stream'),
                "content_length": response.get('ContentLength', 0),
                "last_modified": response.get('LastModified'),
                "etag": response.get('ETag'),
                "metadata": response.get('Metadata', {})
            }
            
            return file_info, status.HTTP_200_OK
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchKey':
                logger.warning(f"File not found in S3: {s3_key}")
                return None, status.HTTP_404_NOT_FOUND
            else:
                logger.error(f"Error getting file info for {s3_key}: {e}")
                return None, status.HTTP_500_INTERNAL_SERVER_ERROR
        except Exception as e:
            logger.error(f"Unexpected error getting file info for {s3_key}: {e}")
            return None, status.HTTP_500_INTERNAL_SERVER_ERROR

# Create global S3 service instance
s3_service = S3Service()

