"""
Presigned URL generation for S3-compatible storage (Tigris) and local filesystem fallback.
"""
from typing import Optional
from django.conf import settings


def get_presigned_url(key: Optional[str], expires_in: int = 86400) -> Optional[str]:
    """
    Presign a storage key (e.g. 'avatars/xxx.jpg', 'blog_images/yyy.png') against Tigris/S3
    when configured, else return a local MEDIA_URL-relative path.
    Returns None if key is falsy.
    Raises on presigning failure — caller decides whether to surface as an HTTP error.
    """
    if not key:
        return None

    if settings.AWS_STORAGE_BUCKET_NAME:
        import boto3
        s3_client = boto3.client(
            's3',
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,
            use_ssl=settings.AWS_S3_USE_SSL,
        )
        return s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': settings.AWS_STORAGE_BUCKET_NAME, 'Key': key},
            ExpiresIn=expires_in,
        )

    return f"{settings.MEDIA_URL}{key}"


def get_presigned_url_or_none(key: Optional[str], expires_in: int = 86400) -> Optional[str]:
    """
    Same as get_presigned_url but swallows errors — for list/detail serializers
    where one bad avatar shouldn't break the whole response.
    """
    try:
        return get_presigned_url(key, expires_in)
    except Exception:
        return None
