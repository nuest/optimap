import optimap
from django.conf import settings

def get_version(request):
    """
    Return package version as listed in `__version__` in `init.py`.
    """
    return {"optimap_version": optimap.__version__}

def gazetteer_settings(request):
    """
    Return gazetteer/geocoding settings for use in templates.
    """
    return {
        "gazetteer_provider": getattr(settings, 'GAZETTEER_PROVIDER', 'nominatim'),
        "gazetteer_placeholder": getattr(settings, 'GAZETTEER_PLACEHOLDER', 'Search for a location...'),
        "gazetteer_api_key": getattr(settings, 'GAZETTEER_API_KEY', ''),
    }
