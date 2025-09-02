import logging

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from fastapi import HTTPException, status

from config import AWS_ACCESS_KEY_ID, AWS_REGION, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME

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

    async def delete_file(self, s3_key: str) -> bool:
        """Delete file from S3 bucket"""
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            return True
            
        except ClientError as e:
            logger.error(f"S3 delete error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete file: {e}"
            )

    async def list_files(self, prefix: str = None) -> list:
        """List all files in S3 bucket"""
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )
            
            files = []
            if 'Contents' in response:
                for obj in response['Contents']:
                    files.append({
                        "key": obj['Key'],
                        "size": obj['Size'],
                        "last_modified": obj['LastModified'].isoformat() if obj['LastModified'] else None,
                        "etag": obj['ETag'],
                        "storage_class": obj.get('StorageClass', 'STANDARD')
                    })
            
            return files
            
        except ClientError as e:
            logger.error(f"S3 list error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list files: {e}"
            )

    async def get_file_url(self, s3_key: str, expires_in: int = 3600) -> str:
        """Generate presigned URL for private files"""
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': s3_key},
                ExpiresIn=expires_in
            )
            return url
        except ClientError as e:
            logger.error(f"S3 presigned URL error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate URL: {e}"
            )

# Create global S3 service instance
s3_service = S3Service()