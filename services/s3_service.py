import logging
from typing import Tuple

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from fastapi import HTTPException, status

from config import (AWS_ACCESS_KEY_ID, AWS_REGION, AWS_SECRET_ACCESS_KEY,
                    S3_BUCKET_NAME)

logger = logging.getLogger(__name__)

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
        
# Create global S3 service instance
s3_service = S3Service()

