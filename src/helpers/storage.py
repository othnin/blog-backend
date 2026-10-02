"""
Presigned URL generation for S3-compatible storage (Tigris) and local filesystem fallback.
"""
import logging
from typing import Optional
from django.conf import settings

logger = logging.getLogger(__name__)

# Presigned links are bearer tokens: whoever holds one can read the object until
# it expires, and it cannot be revoked short of rotating the bucket keys. These
# objects are blog images and avatars rather than private documents, so a short
# lifetime is the proportionate trade - long enough for a page of images to load
# and stay cached, short enough that a leaked link is quickly worthless.
#
# The two public presign endpoints (/api/auth/avatar-url, /api/blog/image-url)
# must stay unauthenticated: rendered post content resolves image keys
# client-side, so logged-out readers need working URLs on public pages.
DEFAULT_EXPIRES_IN = 3600  # 1 hour


def is_safe_storage_key(key: Optional[str], prefix: str) -> bool:
    """
    Whether a caller-supplied key may be presigned.

    Two checks, both needed:
      - it must live under the expected prefix, so callers cannot reach
        unrelated objects elsewhere in the bucket;
      - it must be a single flat segment below that prefix.

    The prefix test alone is not sufficient: 'blog_images/../avatars/x.jpg'
    starts with 'blog_images/' but is not a blog image. S3 treats keys as flat
    strings so this cannot actually traverse, but rejecting it keeps the
    contract explicit rather than relying on storage-provider behaviour.
    """
    if not key or not isinstance(key, str):
        return False
    if not key.startswith(f"{prefix}/"):
        return False
    remainder = key[len(prefix) + 1:]
    if not remainder:
        return False
    # No traversal, no nested prefixes, no separators that imply a path.
    if ".." in remainder:
        return False
    if "/" in remainder or "\\" in remainder or "\x00" in remainder:
        return False
    return True


def get_presigned_url(
    key: Optional[str], expires_in: int = DEFAULT_EXPIRES_IN
) -> Optional[str]:
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


def get_presigned_url_or_none(
    key: Optional[str], expires_in: int = DEFAULT_EXPIRES_IN
) -> Optional[str]:
    """
    Same as get_presigned_url but swallows errors — for list/detail serializers
    where one bad avatar shouldn't break the whole response.
    """
    try:
        return get_presigned_url(key, expires_in)
    except Exception as e:
        logger.error(f"Failed to generate presigned URL for key {key}: {str(e)}")
        try:
            from blog.security_utils import log_security_event
            log_security_event(
                'storage_failed',
                message=f"Failed to generate presigned URL: {str(e)}",
                details={'key': key},
                severity='warning',
            )
        except Exception:
            pass
        return None
