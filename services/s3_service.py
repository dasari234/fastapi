from typing import Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from fastapi import HTTPException, status
from loguru import logger

from config import (AWS_ACCESS_KEY_ID, AWS_REGION, AWS_SECRET_ACCESS_KEY,
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

    async def upload_file(self, file, filename: str, folder: str = None) -> dict:
        """Upload file to S3 bucket and return presigned URL"""
        try:
            # Ensure filename is a string (fix for the Key type error)
            if not isinstance(filename, str):
                raise ValueError(f"Filename must be a string, got {type(filename)}")
            
            # Generate S3 key
            s3_key = f"{folder}/{filename}" if folder else filename
            
            # Upload file (without ACL)
            self.s3_client.upload_fileobj(
                file.file,
                self.bucket_name,
                s3_key,
                ExtraArgs={
                    'ContentType': file.content_type,
                }
            )
            
            # Generate presigned URL that expires in 7 days
            file_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': s3_key},
                ExpiresIn=604800  # 7 days
            )
            
            return {
                "filename": filename,
                "s3_key": s3_key,
                "file_url": file_url,
                "file_size": file.size,
                "content_type": file.content_type,
                "url_expires_in": 604800
            }
            
        except ValueError as e:
            logger.error(f"Invalid filename type: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        except NoCredentialsError:
            logger.error("AWS credentials not found")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AWS credentials not configured"
            )
        except ClientError as e:
            logger.error(f"S3 upload error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload file: {e}"
            )
        except Exception as e:
            logger.error(f"Unexpected error during upload: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Upload failed: {e}"
            )

    async def delete_file(self, s3_key: str) -> Tuple[bool, int]:
        """Delete file from S3 bucket"""
        try:
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
        expiration: int = 3600,  # 1 hour default
        download: bool = False
    ) -> Tuple[Optional[str], int]:
        """
        Generate pre-signed URL for S3 object
        
        Args:
            s3_key: The S3 object key
            expiration: URL expiration time in seconds (default: 3600 = 1 hour)
            download: If True, forces download; if False, tries to display inline
        
        Returns:
            Tuple of (presigned_url, status_code)
        """
        try:
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
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            
            file_info = {
                "content_type": response.get('ContentType'),
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

