"""
OPTIMAP gazetteer proxy views.
Provides CORS-safe proxying for geocoding services.
"""

import requests
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

# Geocoding service configurations
GEOCODING_SERVICES = {
    'nominatim': {
        'search_url': 'https://nominatim.openstreetmap.org/search',
        'reverse_url': 'https://nominatim.openstreetmap.org/reverse',
        'requires_key': False,
        'user_agent': 'OPTIMAP/1.0',
    },
    'photon': {
        'search_url': 'https://photon.komoot.io/api/',
        'reverse_url': 'https://photon.komoot.io/reverse',
        'requires_key': False,
    },
}


@require_http_methods(["GET"])
def gazetteer_search(request, provider):
    """
    Proxy geocoding search requests to avoid CORS issues.

    Args:
        request: Django request object
        provider: Geocoding provider name (nominatim, photon, etc.)

    Returns:
        JsonResponse with geocoding results
    """
    # Validate provider
    provider = provider.lower()
    if provider not in GEOCODING_SERVICES:
        return JsonResponse({
            'error': f'Unknown provider: {provider}',
            'available_providers': list(GEOCODING_SERVICES.keys())
        }, status=400)

    service_config = GEOCODING_SERVICES[provider]

    # Check if API key is required
    if service_config.get('requires_key', False):
        api_key = getattr(settings, 'GAZETTEER_API_KEY', '')
        if not api_key:
            return JsonResponse({
                'error': f'Provider {provider} requires an API key'
            }, status=400)

    # Get search query
    query = request.GET.get('q', '').strip()
    if not query:
        return JsonResponse({
            'error': 'Missing search query parameter "q"'
        }, status=400)

    try:
        # Build request parameters based on provider
        if provider == 'nominatim':
            params = {
                'q': query,
                'format': request.GET.get('format', 'json'),
                'limit': request.GET.get('limit', '5'),
                'addressdetails': request.GET.get('addressdetails', '1'),
            }
            headers = {
                'User-Agent': service_config.get('user_agent', 'OPTIMAP/1.0'),
            }

        elif provider == 'photon':
            params = {
                'q': query,
                'limit': request.GET.get('limit', '5'),
                'lang': request.GET.get('lang', 'en'),
            }
            headers = {}

        else:
            # Generic parameter passthrough
            params = dict(request.GET)
            params['q'] = query
            headers = {}

        # Make request to geocoding service
        logger.info(f'Geocoding request: {provider} - {query}')

        response = requests.get(
            service_config['search_url'],
            params=params,
            headers=headers,
            timeout=10
        )

        response.raise_for_status()

        # Return the response as-is
        try:
            data = response.json()
        except ValueError:
            return JsonResponse({
                'error': 'Invalid JSON response from geocoding service'
            }, status=502)

        logger.info(f'Geocoding results: {len(data) if isinstance(data, list) else 1} results')

        return JsonResponse(data, safe=False)

    except requests.exceptions.Timeout:
        logger.error(f'Geocoding timeout: {provider}')
        return JsonResponse({
            'error': 'Geocoding service timeout'
        }, status=504)

    except requests.exceptions.RequestException as e:
        logger.error(f'Geocoding error: {provider} - {str(e)}')
        return JsonResponse({
            'error': f'Geocoding service error: {str(e)}'
        }, status=502)


@require_http_methods(["GET"])
def gazetteer_reverse(request, provider):
    """
    Proxy reverse geocoding requests (coordinates to address).

    Args:
        request: Django request object
        provider: Geocoding provider name

    Returns:
        JsonResponse with reverse geocoding result
    """
    # Validate provider
    provider = provider.lower()
    if provider not in GEOCODING_SERVICES:
        return JsonResponse({
            'error': f'Unknown provider: {provider}',
            'available_providers': list(GEOCODING_SERVICES.keys())
        }, status=400)

    service_config = GEOCODING_SERVICES[provider]

    # Get coordinates
    lat = request.GET.get('lat', '').strip()
    lon = request.GET.get('lon', '').strip()

    if not lat or not lon:
        return JsonResponse({
            'error': 'Missing lat/lon parameters'
        }, status=400)

    try:
        # Validate coordinates
        lat_float = float(lat)
        lon_float = float(lon)

        if not (-90 <= lat_float <= 90):
            return JsonResponse({'error': 'Invalid latitude'}, status=400)
        if not (-180 <= lon_float <= 180):
            return JsonResponse({'error': 'Invalid longitude'}, status=400)

    except ValueError:
        return JsonResponse({'error': 'Invalid coordinate format'}, status=400)

    try:
        # Build request parameters
        if provider == 'nominatim':
            params = {
                'lat': lat,
                'lon': lon,
                'format': request.GET.get('format', 'json'),
            }
            headers = {
                'User-Agent': service_config.get('user_agent', 'OPTIMAP/1.0'),
            }

        elif provider == 'photon':
            params = {
                'lat': lat,
                'lon': lon,
            }
            headers = {}

        else:
            params = dict(request.GET)
            headers = {}

        # Make request
        logger.info(f'Reverse geocoding: {provider} - {lat},{lon}')

        response = requests.get(
            service_config['reverse_url'],
            params=params,
            headers=headers,
            timeout=10
        )

        response.raise_for_status()
        data = response.json()

        return JsonResponse(data, safe=False)

    except requests.exceptions.RequestException as e:
        logger.error(f'Reverse geocoding error: {provider} - {str(e)}')
        return JsonResponse({
            'error': f'Reverse geocoding service error: {str(e)}'
        }, status=502)
