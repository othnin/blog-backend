"""
Geocoding service for the locations app.

Wraps the Google Maps Geocoding API behind ``LocationService.geocode_address``
and caches results using Django's cache framework (LocMemCache in dev, Redis in
production — see ``home/settings.py``). Geocoding is invoked only from the
dedicated ``/api/locations/geocode/`` endpoint; model ``save()`` never performs
network I/O.

Uses the standard library ``urllib`` so the project does not need an extra
HTTP-client dependency.
"""
import json
import logging
import re
from decimal import Decimal
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest
from typing import Tuple

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

GEOCODE_CACHE_TTL = 60 * 60 * 24  # 24 hours
GEOCODE_ENDPOINT = 'https://maps.googleapis.com/maps/api/geocode/json'
GEOCODE_TIMEOUT = 5  # seconds


class GeocodingError(Exception):
    """Raised when an address cannot be geocoded, or the upstream API fails."""


class LocationService:
    """Stateless helper for turning an address string into coordinates."""

    @staticmethod
    def _cache_key(address: str) -> str:
        normalized = ' '.join(address.lower().split())
        # Collapse to alphanumerics so the key is valid for any cache backend
        # (memcached rejects commas/spaces in keys; LocMem/Redis tolerate them).
        safe = re.sub(r'[^a-z0-9]+', '_', normalized).strip('_')
        return f'geocode:{safe}'

    @staticmethod
    def geocode_address(address: str) -> Tuple[Decimal, Decimal]:
        """
        Return ``(latitude, longitude)`` for ``address``.

        Results are cached for 24 hours keyed on the normalized address. Raises
        ``GeocodingError`` for a missing/blank address, an empty Google result
        set, a non-OK Google status, a missing API key, or a transport failure.
        """
        address = (address or '').strip()
        if not address:
            raise GeocodingError('Address is required.')

        cache_key = LocationService._cache_key(address)
        cached = cache.get(cache_key)
        if cached is not None:
            return Decimal(cached[0]), Decimal(cached[1])

        api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '') or ''
        if not api_key:
            logger.error('GOOGLE_MAPS_API_KEY is not configured; cannot geocode.')
            raise GeocodingError('Geocoding is not configured. Contact support.')

        query = urlparse.urlencode({'address': address, 'key': api_key})
        url = f'{GEOCODE_ENDPOINT}?{query}'

        try:
            with urlrequest.urlopen(url, timeout=GEOCODE_TIMEOUT) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except (urlerror.URLError, OSError) as exc:
            logger.exception('Geocoding request failed for address %r', address)
            raise GeocodingError('Geocoding service is unavailable. Please try again.') from exc
        except (ValueError, UnicodeDecodeError) as exc:
            logger.exception('Geocoding returned malformed JSON for address %r', address)
            raise GeocodingError('Geocoding service returned an unexpected response.') from exc

        status = payload.get('status')
        if status != 'OK' or not payload.get('results'):
            logger.warning('Geocoding status %r for address %r', status, address)
            raise GeocodingError(
                'Could not find coordinates for this address. '
                'Please try a different address or contact support.'
            )

        location = payload['results'][0]['geometry']['location']
        lat = Decimal(str(location['lat'])).quantize(Decimal('0.000001'))
        lng = Decimal(str(location['lng'])).quantize(Decimal('0.000001'))

        cache.set(cache_key, (str(lat), str(lng)), GEOCODE_CACHE_TTL)
        return lat, lng
