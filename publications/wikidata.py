import os
import logging
import requests
import traceback
import json
from datetime import datetime
from django.conf import settings
from django.db import transaction

from wikibaseintegrator.wbi_exceptions import ModificationFailed
from wikibaseintegrator import WikibaseIntegrator
from wikibaseintegrator.wbi_login import OAuth1
from wikibaseintegrator.wbi_config import config as wbi_config
from wikibaseintegrator.datatypes import (
    MonolingualText,
    Time,
    String,
    ExternalID,
    GlobeCoordinate,
    Item
)
try:
    from wikibaseintegrator.datatypes import Url
except ImportError:
    from wikibaseintegrator.datatypes import URL as Url

logger = logging.getLogger(__name__)

# Configure wikibaseintegrator with our settings
wbi_config['USER_AGENT'] = settings.WIKIBASE_USER_AGENT
wbi_config['MEDIAWIKI_API_URL'] = settings.WIKIBASE_API_URL

# SPARQL endpoint configuration
if "www.wikidata.org/w/api.php" in settings.WIKIBASE_API_URL:
    SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
    WIKIBASE_URL = "https://www.wikidata.org/wiki/"
    IS_WIKIDATA = True
else:
    SPARQL_ENDPOINT = settings.WIKIBASE_API_URL.replace("/w/api.php", "/query/sparql")
    base_url = settings.WIKIBASE_API_URL.replace("/w/api.php", "")
    WIKIBASE_URL = f"{base_url}/wiki/Item:"  # Custom Wikibase uses Item: prefix
    IS_WIKIDATA = False
    # Update wbi_config for non-Wikidata instances
    wbi_config['SPARQL_ENDPOINT_URL'] = SPARQL_ENDPOINT
    wbi_config['WIKIBASE_URL'] = base_url

# Calendar model for all dates
CALENDAR_MODEL = "http://www.wikidata.org/entity/Q1985727"

# Wikidata property IDs (these are the SOURCE property IDs from Wikidata.org)
P_EQUIVALENT_PROPERTY = "P1628"  # equivalent property (URL)
P_TITLE = "P1476"  # title (monolingual text)
P_ABSTRACT = "P1810"  # abstract / name
P_URL = "P856"   # official website / URL
P_PUBLICATION_DATE = "P577"   # publication date
P_PERIOD_START = "P580"   # start time
P_PERIOD_END = "P582"   # end time
P_DOI = "P356"   # DOI as External ID
P_AUTHOR_STRING = "P2093"  # author name string
P_AUTHOR = "P50"  # author (item reference)
P_JOURNAL_NAME = "P1448"  # journal name (monolingual text)
P_JOURNAL = "P1433"  # published in (journal as item)
P_GEOMETRY = "P625"   # coordinate location
P_NORTHERNMOST_POINT = "P1332"  # northernmost point
P_SOUTHERNMOST_POINT = "P1333"  # southernmost point
P_EASTERNMOST_POINT = "P1334"   # easternmost point
P_WESTERNMOST_POINT = "P1335"   # westernmost point
P_INSTANCE_OF = "P31"  # instance of
P_KEYWORDS = "P921"  # main subject / keywords
P_LANGUAGE = "P407"  # language of work
P_LICENSE = "P275"  # copyright license
P_FULL_TEXT_URL = "P953"  # full work available at URL

# Additional properties for OpenAlex data
P_OPENALEX_ID = "P10283"  # OpenAlex ID
P_PMID = "P698"  # PubMed ID
P_PMC = "P932"  # PubMed Central ID
P_ISSN = "P236"  # ISSN
P_ISSN_L = "P7363"  # ISSN-L
P_RETRACTED = "P5824"  # retracted (boolean)

# Wikidata items
Q_SCHOLARLY_ARTICLE = "Q13442814"  # scholarly article
Q_ENGLISH = "Q1860"  # English language


# Cache for available properties in the target Wikibase
_available_properties_cache = None
_available_items_cache = None
_property_creation_attempted = set()

# Cache for property metadata fetched from Wikidata
_property_metadata_cache = {}

# Cache for mapping Wikidata property IDs to local Wikibase property IDs
# e.g., {"P31": "P1", "P577": "P3", "P1628": "P63"}
_property_id_mapping = None


def build_property_id_mapping():
    """
    Build a mapping from Wikidata property IDs to local Wikibase property IDs
    by querying all properties and checking their P1628 (equivalent property) claims.

    Returns:
        dict: Mapping like {"P31": "P1", "P577": "P3", "P1628": "P63"}
    """
    global _property_id_mapping

    if _property_id_mapping is not None:
        return _property_id_mapping

    _property_id_mapping = {}

    try:
        # First, find the local property ID for "equivalent property" itself
        search_response = requests.get(
            settings.WIKIBASE_API_URL,
            params={
                'action': 'wbsearchentities',
                'search': 'equivalent property',
                'language': 'en',
                'type': 'property',
                'format': 'json'
            },
            headers={'User-Agent': settings.WIKIBASE_USER_AGENT},
            timeout=10
        )
        search_data = search_response.json()

        equivalent_property_id = None
        if 'search' in search_data:
            for result in search_data['search']:
                if result.get('label', '').lower() == 'equivalent property':
                    equivalent_property_id = result['id']
                    # Map P1628 to whatever the local ID is
                    _property_id_mapping['P1628'] = equivalent_property_id
                    logger.debug(f"Found equivalent property: P1628 -> {equivalent_property_id}")
                    break

        if not equivalent_property_id:
            logger.warning("Equivalent property (P1628) not found in Wikibase - property mapping will be limited")
            return _property_id_mapping

        # Query all properties to build the mapping
        response = requests.get(
            settings.WIKIBASE_API_URL,
            params={
                'action': 'wbsearchentities',
                'search': '',  # Empty search to get all
                'language': 'en',
                'type': 'property',
                'limit': 500,  # Get many properties
                'format': 'json'
            },
            headers={'User-Agent': settings.WIKIBASE_USER_AGENT},
            timeout=30
        )
        all_properties_data = response.json()

        if 'search' not in all_properties_data:
            logger.warning("Could not fetch property list from Wikibase")
            return _property_id_mapping

        # Get detailed data for each property to check for P1628 claims
        property_ids = [prop['id'] for prop in all_properties_data['search']]

        if not property_ids:
            return _property_id_mapping

        # Fetch properties in batches
        batch_size = 50
        for i in range(0, len(property_ids), batch_size):
            batch = property_ids[i:i+batch_size]

            entities_response = requests.get(
                settings.WIKIBASE_API_URL,
                params={
                    'action': 'wbgetentities',
                    'ids': '|'.join(batch),
                    'format': 'json'
                },
                headers={'User-Agent': settings.WIKIBASE_USER_AGENT},
                timeout=30
            )
            entities_data = entities_response.json()

            if 'entities' not in entities_data:
                continue

            # Check each property for P1628 claims
            for prop_id, prop_data in entities_data['entities'].items():
                claims = prop_data.get('claims', {})

                # Cache property existence for all local properties we encounter
                # This avoids later API calls in check_property_exists()
                global _available_properties_cache
                if _available_properties_cache is None:
                    _available_properties_cache = {}

                # Check if this property has an equivalent property claim
                if equivalent_property_id in claims:
                    for claim in claims[equivalent_property_id]:
                        # Extract the Wikidata property URL from the claim value
                        datavalue = claim.get('mainsnak', {}).get('datavalue', {})
                        if datavalue.get('type') == 'string':
                            url = datavalue.get('value', '')
                            # URL format: https://www.wikidata.org/entity/P31
                            if 'wikidata.org/entity/P' in url:
                                wikidata_prop_id = url.split('/')[-1]
                                _property_id_mapping[wikidata_prop_id] = prop_id
                                # Cache that this Wikidata property exists in our Wikibase
                                _available_properties_cache[wikidata_prop_id] = True
                                logger.debug(f"Mapped property: {wikidata_prop_id} -> {prop_id}")

        logger.info(f"Built property ID mapping with {len(_property_id_mapping)} properties via equivalent property claims")
        logger.info(f"Cached {len(_available_properties_cache)} property existence checks for faster lookups")

        # Step 2: Fallback to name-based matching for properties without equivalent property claims
        # Fetch metadata for standard Wikidata properties we use
        standard_properties = [
            P_TITLE, P_ABSTRACT, P_URL, P_PUBLICATION_DATE, P_PERIOD_START, P_PERIOD_END,
            P_DOI, P_AUTHOR_STRING, P_AUTHOR, P_JOURNAL_NAME, P_JOURNAL, P_GEOMETRY,
            P_NORTHERNMOST_POINT, P_SOUTHERNMOST_POINT, P_EASTERNMOST_POINT, P_WESTERNMOST_POINT,
            P_INSTANCE_OF, P_KEYWORDS, P_LANGUAGE, P_LICENSE, P_FULL_TEXT_URL,
            P_OPENALEX_ID, P_PMID, P_PMC, P_ISSN, P_ISSN_L, P_RETRACTED
        ]

        for wikidata_prop_id in standard_properties:
            # Skip if already mapped via equivalent property
            if wikidata_prop_id in _property_id_mapping:
                continue

            # Fetch metadata from Wikidata
            wikidata_meta = fetch_property_metadata_from_wikidata(wikidata_prop_id)
            if not wikidata_meta:
                continue

            wikidata_label = wikidata_meta['label'].lower().strip()

            # Search for matching property by label in local Wikibase
            for prop_id in property_ids:
                if prop_id not in entities_data.get('entities', {}):
                    continue

                local_prop = entities_data['entities'][prop_id]
                local_label = local_prop.get('labels', {}).get('en', {}).get('value', '').lower().strip()

                # Exact name match
                if local_label == wikidata_label:
                    _property_id_mapping[wikidata_prop_id] = prop_id
                    logger.debug(f"Mapped property via name matching: {wikidata_prop_id} ({wikidata_label}) -> {prop_id}")

                    # Add equivalent property claim to establish the relationship
                    try:
                        from requests_oauthlib import OAuth1Session

                        # Create OAuth1 session
                        oauth = OAuth1Session(
                            settings.WIKIBASE_CONSUMER_TOKEN,
                            client_secret=settings.WIKIBASE_CONSUMER_SECRET,
                            resource_owner_key=settings.WIKIBASE_ACCESS_TOKEN,
                            resource_owner_secret=settings.WIKIBASE_ACCESS_SECRET
                        )

                        # Check if this property already has an equivalent property claim
                        claims = local_prop.get('claims', {})
                        wikidata_property_url = f'https://www.wikidata.org/entity/{wikidata_prop_id}'

                        has_equivalent_claim = False
                        if equivalent_property_id in claims:
                            for claim in claims[equivalent_property_id]:
                                existing_url = claim.get('mainsnak', {}).get('datavalue', {}).get('value', '')
                                if existing_url == wikidata_property_url:
                                    has_equivalent_claim = True
                                    break

                        if not has_equivalent_claim:
                            # Get CSRF token
                            token_params = {
                                'action': 'query',
                                'meta': 'tokens',
                                'type': 'csrf',
                                'format': 'json'
                            }
                            token_response = oauth.get(settings.WIKIBASE_API_URL, params=token_params)
                            token_data = token_response.json()
                            csrf_token = token_data['query']['tokens']['csrftoken']

                            # Add equivalent property claim
                            claim_params = {
                                'action': 'wbcreateclaim',
                                'entity': prop_id,
                                'property': equivalent_property_id,
                                'snaktype': 'value',
                                'value': json.dumps(wikidata_property_url),
                                'token': csrf_token,
                                'format': 'json',
                                'bot': '1'
                            }

                            claim_response = oauth.post(settings.WIKIBASE_API_URL, data=claim_params)
                            claim_data = claim_response.json()

                            if claim_data.get('success') == 1:
                                logger.info(f"Added equivalent property claim to {prop_id} linking to {wikidata_property_url}")
                            else:
                                logger.warning(f"Could not add equivalent property claim to {prop_id}: {claim_data}")
                    except Exception as e:
                        logger.warning(f"Error adding equivalent property claim to name-matched property {prop_id}: {e}")

                    break

        logger.info(f"Built complete property ID mapping with {len(_property_id_mapping)} properties (equivalent claims + name matching)")
        return _property_id_mapping

    except Exception as e:
        logger.error(f"Error building property ID mapping: {e}")
        logger.debug(traceback.format_exc())
        return _property_id_mapping or {}


def get_local_property_id(wikidata_property_id):
    """
    Get the local Wikibase property ID for a Wikidata property ID.

    Args:
        wikidata_property_id: Wikidata property ID like "P31"

    Returns:
        str: Local property ID like "P1", or the original ID if no mapping exists
    """
    mapping = build_property_id_mapping()
    local_id = mapping.get(wikidata_property_id, wikidata_property_id)
    if local_id != wikidata_property_id:
        logger.debug(f"Using local property {local_id} for Wikidata property {wikidata_property_id}")
    return local_id


def get_wikibase_login():
    """
    Get authenticated login session for Wikibase/Wikidata using OAuth 1.0a.

    Returns:
        OAuth1: OAuth1 login session object

    Raises:
        ValueError: If OAuth 1.0a credentials are not configured
    """
    required_credentials = [
        settings.WIKIBASE_CONSUMER_TOKEN,
        settings.WIKIBASE_CONSUMER_SECRET,
        settings.WIKIBASE_ACCESS_TOKEN,
        settings.WIKIBASE_ACCESS_SECRET,
    ]

    if not all(required_credentials):
        raise ValueError(
            "Wikibase OAuth 1.0a credentials not configured. "
            "Please set WIKIBASE_CONSUMER_TOKEN, WIKIBASE_CONSUMER_SECRET, "
            "WIKIBASE_ACCESS_TOKEN, and WIKIBASE_ACCESS_SECRET environment variables. "
            "See WIKIBASE_OAUTH_SETUP.md for setup instructions."
        )

    logger.debug("Using OAuth 1.0a authentication for Wikibase")
    return OAuth1(
        consumer_token=settings.WIKIBASE_CONSUMER_TOKEN,
        consumer_secret=settings.WIKIBASE_CONSUMER_SECRET,
        access_token=settings.WIKIBASE_ACCESS_TOKEN,
        access_secret=settings.WIKIBASE_ACCESS_SECRET,
        mediawiki_api_url=settings.WIKIBASE_API_URL,
        user_agent=settings.WIKIBASE_USER_AGENT,
    )


def fetch_property_metadata_from_wikidata(property_id):
    """
    Fetch property metadata (label, description, datatype) from Wikidata.org.

    Args:
        property_id: The property ID (e.g., "P31")

    Returns:
        dict: {'label': str, 'description': str, 'datatype': str} or None if fetch fails
    """
    global _property_metadata_cache

    # Check cache first
    if property_id in _property_metadata_cache:
        return _property_metadata_cache[property_id]

    try:
        # Fetch property entity from Wikidata API
        url = "https://www.wikidata.org/w/api.php"
        params = {
            'action': 'wbgetentities',
            'ids': property_id,
            'format': 'json',
            'languages': 'en'
        }
        response = requests.get(url, params=params, headers={'User-Agent': settings.WIKIBASE_USER_AGENT}, timeout=10)
        data = response.json()

        # Check if property exists
        if 'entities' not in data or property_id not in data['entities']:
            logger.warning(f"Property {property_id} not found in Wikidata")
            return None

        entity = data['entities'][property_id]

        if 'missing' in entity:
            logger.warning(f"Property {property_id} is missing in Wikidata")
            return None

        # Extract metadata
        label = entity.get('labels', {}).get('en', {}).get('value', property_id)
        description = entity.get('descriptions', {}).get('en', {}).get('value', '')
        datatype = entity.get('datatype', 'string')

        metadata = {
            'label': label,
            'description': description,
            'datatype': datatype
        }

        # Cache it
        _property_metadata_cache[property_id] = metadata
        logger.debug(f"Fetched metadata for {property_id}: {metadata}")

        return metadata

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch property metadata for {property_id} from Wikidata: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching property metadata for {property_id}: {e}")
        logger.debug(traceback.format_exc())
        return None


def get_property_metadata(property_id):
    """
    Get property metadata, fetching from Wikidata.org if not cached.

    Args:
        property_id: The property ID (e.g., "P31")

    Returns:
        dict: {'label': str, 'description': str, 'datatype': str} or None if unavailable
    """
    return fetch_property_metadata_from_wikidata(property_id)


def create_property_in_wikibase(property_id):
    """
    Create a property in the target Wikibase instance if it doesn't exist.
    Fetches property metadata dynamically from Wikidata.org and adds equivalent property claim.
    Uses direct API calls (OAuth1Session) instead of wikibaseintegrator for better compatibility.

    Args:
        property_id: The Wikidata property ID (e.g., "P31")

    Returns:
        str: Local property ID if created/exists (e.g., "P1"), or None if creation failed
    """
    global _property_creation_attempted
    global _property_id_mapping
    global _available_properties_cache

    # Don't try to create the same property twice
    if property_id in _property_creation_attempted:
        return None

    _property_creation_attempted.add(property_id)

    # Fetch metadata from Wikidata
    meta = get_property_metadata(property_id)
    if not meta:
        logger.warning(f"No metadata available for property {property_id} from Wikidata, cannot create it")
        return None

    try:
        from requests_oauthlib import OAuth1Session

        # Create OAuth1 session for direct API calls
        oauth = OAuth1Session(
            settings.WIKIBASE_CONSUMER_TOKEN,
            client_secret=settings.WIKIBASE_CONSUMER_SECRET,
            resource_owner_key=settings.WIKIBASE_ACCESS_TOKEN,
            resource_owner_secret=settings.WIKIBASE_ACCESS_SECRET
        )

        # Step 1: Check if property with same label already exists
        logger.debug(f"Checking if property with label '{meta['label']}' already exists in Wikibase")
        search_params = {
            'action': 'wbsearchentities',
            'search': meta['label'],
            'language': 'en',
            'type': 'property',
            'format': 'json'
        }
        search_response = oauth.get(settings.WIKIBASE_API_URL, params=search_params)
        search_data = search_response.json()

        # Check for exact label match
        if 'search' in search_data:
            for result in search_data['search']:
                if result.get('label', '').lower() == meta['label'].lower():
                    existing_id = result['id']
                    logger.info(f"Property with label '{meta['label']}' already exists as {existing_id} - will use existing property and add equivalent claim if needed")

                    # Update caches
                    if _available_properties_cache is None:
                        _available_properties_cache = {}
                    _available_properties_cache[property_id] = True

                    if _property_id_mapping is None:
                        _property_id_mapping = {}
                    _property_id_mapping[property_id] = existing_id

                    # Try to add equivalent property claim to existing property
                    try:
                        # Get CSRF token for adding claim
                        token_params = {
                            'action': 'query',
                            'meta': 'tokens',
                            'type': 'csrf',
                            'format': 'json'
                        }
                        token_response = oauth.get(settings.WIKIBASE_API_URL, params=token_params)
                        token_data = token_response.json()
                        csrf_token = token_data['query']['tokens']['csrftoken']

                        # Check if equivalent property exists
                        mapping = build_property_id_mapping()
                        equivalent_property_id = mapping.get('P1628')

                        if equivalent_property_id:
                            # Fetch the existing property to check for existing claims
                            get_params = {
                                'action': 'wbgetentities',
                                'ids': existing_id,
                                'format': 'json'
                            }
                            get_response = oauth.get(settings.WIKIBASE_API_URL, params=get_params)
                            get_data = get_response.json()

                            wikidata_property_url = f'https://www.wikidata.org/entity/{property_id}'

                            # Check if claim already exists
                            has_claim = False
                            if existing_id in get_data.get('entities', {}):
                                claims = get_data['entities'][existing_id].get('claims', {})
                                if equivalent_property_id in claims:
                                    for claim in claims[equivalent_property_id]:
                                        existing_url = claim.get('mainsnak', {}).get('datavalue', {}).get('value', '')
                                        if existing_url == wikidata_property_url:
                                            has_claim = True
                                            logger.debug(f"Equivalent property claim already exists on {existing_id}")
                                            break

                            # Add claim if it doesn't exist
                            if not has_claim:
                                claim_params = {
                                    'action': 'wbcreateclaim',
                                    'entity': existing_id,
                                    'property': equivalent_property_id,
                                    'snaktype': 'value',
                                    'value': json.dumps(wikidata_property_url),
                                    'token': csrf_token,
                                    'format': 'json',
                                    'bot': '1'
                                }

                                claim_response = oauth.post(settings.WIKIBASE_API_URL, data=claim_params)
                                claim_data = claim_response.json()

                                if claim_data.get('success') == 1:
                                    logger.info(f"Added equivalent property claim to existing property {existing_id} linking to {wikidata_property_url}")
                                else:
                                    logger.warning(f"Could not add equivalent property claim to {existing_id}: {claim_data}")
                    except Exception as e:
                        logger.warning(f"Error adding equivalent property claim to existing property {existing_id}: {e}")

                    return existing_id

        # Step 2: Get CSRF token for creating new property
        logger.debug("Fetching CSRF token for property creation")
        token_params = {
            'action': 'query',
            'meta': 'tokens',
            'type': 'csrf',
            'format': 'json'
        }
        token_response = oauth.get(settings.WIKIBASE_API_URL, params=token_params)
        token_data = token_response.json()

        if 'query' not in token_data or 'tokens' not in token_data['query']:
            logger.error(f"Failed to get CSRF token: {token_data}")
            return None

        csrf_token = token_data['query']['tokens']['csrftoken']

        # Step 3: Create property data structure (shallow copy)
        property_data = {
            "labels": {
                "en": {
                    "language": "en",
                    "value": meta['label']
                }
            },
            "descriptions": {
                "en": {
                    "language": "en",
                    "value": meta['description']
                }
            },
            "datatype": meta['datatype']
        }

        logger.debug(f"Creating property {property_id} with label '{meta['label']}' and datatype '{meta['datatype']}' (shallow copy, no claims)")

        # Step 4: Create property
        create_params = {
            'action': 'wbeditentity',
            'new': 'property',
            'data': json.dumps(property_data),
            'summary': f'Auto-created property via OPTIMAP export from Wikidata {property_id}',
            'token': csrf_token,
            'format': 'json',
            'bot': '1'
        }

        create_response = oauth.post(settings.WIKIBASE_API_URL, data=create_params)
        create_data = create_response.json()

        if 'success' not in create_data or create_data['success'] != 1:
            error_info = create_data.get('error', {})
            logger.error(f"Failed to create property {property_id}: {error_info}")
            return None

        created_id = create_data['entity']['id']
        logger.info(f"Successfully created property {created_id} ({meta['label']}) in Wikibase for {property_id}")

        # Step 5: Add equivalent property claim to link to Wikidata
        # Find the local ID for "equivalent property"
        mapping = build_property_id_mapping()
        equivalent_property_id = mapping.get('P1628')

        if equivalent_property_id:
            try:
                wikidata_property_url = f'https://www.wikidata.org/entity/{property_id}'

                claim_params = {
                    'action': 'wbcreateclaim',
                    'entity': created_id,
                    'property': equivalent_property_id,
                    'snaktype': 'value',
                    'value': json.dumps(wikidata_property_url),
                    'token': csrf_token,
                    'format': 'json',
                    'bot': '1'
                }

                claim_response = oauth.post(settings.WIKIBASE_API_URL, data=claim_params)
                claim_data = claim_response.json()

                if claim_data.get('success') == 1:
                    logger.debug(f"Added equivalent property claim linking {created_id} to {wikidata_property_url}")
                else:
                    logger.warning(f"Could not add equivalent property claim to {created_id}: {claim_data}")
            except Exception as e:
                logger.warning(f"Error adding equivalent property claim: {e}")
        else:
            logger.debug("Equivalent property not found in Wikibase, skipping claim addition")

        # Update caches
        if _available_properties_cache is None:
            _available_properties_cache = {}
        _available_properties_cache[property_id] = True

        if _property_id_mapping is None:
            _property_id_mapping = {}
        _property_id_mapping[property_id] = created_id

        return created_id

    except Exception as e:
        error_msg = str(e)
        if "The save has failed" in error_msg or "permission" in error_msg.lower():
            logger.error(
                f"Failed to create property {property_id} in Wikibase: {e}. "
                f"The Wikibase account may not have the 'property-create' permission. "
                f"Please ask a Wikibase administrator to either: "
                f"1) Grant property-create rights to this account, or "
                f"2) Manually create property {property_id} ({meta['label']}) "
                f"with datatype '{meta['datatype']}'"
            )
        else:
            logger.error(f"Failed to create property {property_id} in Wikibase: {e}")
        logger.debug(traceback.format_exc())
        return None


def check_property_exists(wikidata_property_id):
    """
    Check if a property exists in the target Wikibase instance (using Wikidata property ID).
    First checks if mapping exists, then creates property if needed.
    Uses caching to avoid repeated API calls.

    Args:
        wikidata_property_id: Wikidata property ID like "P31"

    Returns:
        bool: True if property exists (or was created), False otherwise
    """
    global _available_properties_cache

    if _available_properties_cache is None:
        _available_properties_cache = {}

    if wikidata_property_id in _available_properties_cache:
        return _available_properties_cache[wikidata_property_id]

    try:
        # First, check if we have a mapping from Wikidata ID to local ID
        local_property_id = get_local_property_id(wikidata_property_id)

        # If local ID is different from Wikidata ID, we have a mapping
        if local_property_id != wikidata_property_id:
            logger.debug(f"Found property mapping: {wikidata_property_id} -> {local_property_id}")
            _available_properties_cache[wikidata_property_id] = True
            return True

        # No mapping found - check if property exists directly by ID
        response = requests.get(
            settings.WIKIBASE_API_URL,
            params={
                'action': 'wbgetentities',
                'ids': wikidata_property_id,
                'format': 'json'
            },
            headers={'User-Agent': settings.WIKIBASE_USER_AGENT},
            timeout=10
        )
        data = response.json()

        # Check if property exists (not in 'missing' list)
        exists = wikidata_property_id in data.get('entities', {}) and 'missing' not in data.get('entities', {}).get(wikidata_property_id, {})

        if not exists:
            logger.debug(f"Property {wikidata_property_id} not found in Wikibase instance")

            # Try to create it if enabled
            if settings.WIKIBASE_CREATE_PROPERTIES_IF_MISSING:
                logger.info(f"Attempting to create property {wikidata_property_id} in Wikibase")
                created_local_id = create_property_in_wikibase(wikidata_property_id)
                if created_local_id:
                    exists = True
                    logger.info(f"Successfully created property {created_local_id} for {wikidata_property_id}")
                else:
                    logger.warning(f"Failed to create property {wikidata_property_id}")

        _available_properties_cache[wikidata_property_id] = exists
        return exists

    except Exception as e:
        logger.warning(f"Could not check if property {wikidata_property_id} exists: {e}")
        # Assume it doesn't exist to avoid errors
        _available_properties_cache[wikidata_property_id] = False
        return False


def check_item_exists(item_id):
    """
    Check if an item (Q-ID) exists in the target Wikibase instance.
    Uses caching to avoid repeated API calls.
    """
    global _available_items_cache

    if _available_items_cache is None:
        _available_items_cache = {}

    if item_id in _available_items_cache:
        return _available_items_cache[item_id]

    try:
        response = requests.get(
            settings.WIKIBASE_API_URL,
            params={
                'action': 'wbgetentities',
                'ids': item_id,
                'format': 'json'
            },
            headers={'User-Agent': settings.WIKIBASE_USER_AGENT},
            timeout=10
        )
        data = response.json()

        exists = item_id in data.get('entities', {}) and 'missing' not in data.get('entities', {}).get(item_id, {})
        _available_items_cache[item_id] = exists

        if not exists:
            logger.debug(f"Item {item_id} not found in Wikibase instance")

        return exists
    except Exception as e:
        logger.warning(f"Could not check if item {item_id} exists: {e}")
        _available_items_cache[item_id] = False
        return False


def normalize_date_and_precision(date_str, is_end_date=False):
    """
    Convert date string to ISO format with appropriate precision.

    Args:
        date_str: Date string in format YYYY, YYYY-MM, or YYYY-MM-DD
        is_end_date: If True, use last day of year/month instead of first day

    Returns: tuple (iso_date_string, precision)
      - precision 9 = year
      - precision 10 = month
      - precision 11 = day
    """
    import calendar

    parts = date_str.split("-")
    if len(parts) == 1 and parts[0].isdigit():
        # "YYYY"
        year = parts[0]
        if is_end_date:
            return f"{year}-12-31", 9
        else:
            return f"{year}-01-01", 9
    if len(parts) == 2 and all(p.isdigit() for p in parts):
        # "YYYY-MM"
        year, month = parts[0], parts[1]
        if is_end_date:
            # Get last day of the month
            last_day = calendar.monthrange(int(year), int(month))[1]
            return f"{year}-{month}-{last_day:02d}", 10
        else:
            return f"{year}-{month}-01", 10
    # assume full "YYYY-MM-DD"
    return date_str, 11


def add_time_claims(dates, prop_nr, statements, is_end_date=False):
    """Add time-based claims for a list of date strings."""
    for ds in dates:
        iso, prec = normalize_date_and_precision(ds, is_end_date=is_end_date)
        timestamp = f"+{iso}T00:00:00Z"
        statements.append(Time(
            prop_nr=prop_nr,
            time=timestamp,
            timezone=0,
            before=0,
            after=0,
            precision=prec,
            calendarmodel=CALENDAR_MODEL
        ))


def find_local_item_by_doi(doi):
    """
    Return the Q-ID of an existing item in our Wikibase instance for the given DOI,
    or None if no match is found.
    """
    # Get the local property ID for DOI
    local_doi_property = get_local_property_id(P_DOI)

    sparql_query = f'''
    SELECT ?item WHERE {{
      ?item wdt:{local_doi_property} "{doi}" .
    }} LIMIT 1
    '''
    try:
        response = requests.get(
            SPARQL_ENDPOINT,
            params={"query": sparql_query, "format": "json"},
            headers={"Accept": "application/json"},
            timeout=30
        )
        response.raise_for_status()

        data = response.json()
        bindings = data.get("results", {}).get("bindings", [])
        if not bindings:
            return None

        item_uri = bindings[0]["item"]["value"]
        return item_uri.rsplit("/", 1)[-1]
    except Exception as e:
        logger.error(f"Error querying SPARQL for DOI {doi}: {e}")
        return None


def find_local_item_by_openalex_id(openalex_id):
    """
    Return the Q-ID of an existing item in our Wikibase instance for the given OpenAlex ID,
    or None if no match is found.

    Args:
        openalex_id: OpenAlex ID, either full URL (https://openalex.org/W1234567890) or just the ID (W1234567890)

    Returns:
        str: QID of the item, or None if not found
    """
    # Extract just the ID part if a full URL was provided
    if openalex_id and '/' in openalex_id:
        openalex_id = openalex_id.rsplit('/', 1)[-1]

    if not openalex_id:
        return None

    # Get the local property ID for OpenAlex ID
    local_openalex_property = get_local_property_id(P_OPENALEX_ID)

    # Try with full URL first
    sparql_query = f'''
    SELECT ?item WHERE {{
      {{ ?item wdt:{local_openalex_property} "https://openalex.org/{openalex_id}" . }}
      UNION
      {{ ?item wdt:{local_openalex_property} "{openalex_id}" . }}
    }} LIMIT 1
    '''
    try:
        response = requests.get(
            SPARQL_ENDPOINT,
            params={"query": sparql_query, "format": "json"},
            headers={"Accept": "application/json"},
            timeout=30
        )
        response.raise_for_status()

        data = response.json()
        bindings = data.get("results", {}).get("bindings", [])
        if not bindings:
            return None

        item_uri = bindings[0]["item"]["value"]
        qid = item_uri.rsplit("/", 1)[-1]
        logger.debug(f"Found existing item {qid} for OpenAlex ID {openalex_id}")
        return qid
    except Exception as e:
        logger.error(f"Error querying SPARQL for OpenAlex ID {openalex_id}: {e}")
        return None


def build_statements(publication):
    """
    Build comprehensive list of Wikidata statements from publication data.

    Returns:
        tuple: (statements_list, exported_fields_list)

    Raises:
        ValueError: If required properties cannot be created in the Wikibase instance
    """
    statements = []
    exported_fields = []
    missing_properties = []

    # Instance of scholarly article
    if not check_property_exists(P_INSTANCE_OF):
        missing_properties.append(f"{P_INSTANCE_OF} (instance of)")
    elif check_item_exists(Q_SCHOLARLY_ARTICLE):
        statements.append(Item(prop_nr=get_local_property_id(P_INSTANCE_OF), value=Q_SCHOLARLY_ARTICLE))
        exported_fields.append('instance_of')

    # Title (required)
    if publication.title:
        if not check_property_exists(P_TITLE):
            missing_properties.append(f"{P_TITLE} (title)")
        else:
            statements.append(MonolingualText(prop_nr=get_local_property_id(P_TITLE), text=publication.title, language="en"))
            exported_fields.append('title')

    # Publication date (required)
    if publication.publicationDate:
        if not check_property_exists(P_PUBLICATION_DATE):
            missing_properties.append(f"{P_PUBLICATION_DATE} (publication date)")
        else:
            iso_date = publication.publicationDate.isoformat()
            publication_timestamp = f"+{iso_date}T00:00:00Z"
            statements.append(Time(
                prop_nr=get_local_property_id(P_PUBLICATION_DATE),
                time=publication_timestamp,
                timezone=0,
                before=0,
                after=0,
                precision=11,
                calendarmodel=CALENDAR_MODEL
            ))
            exported_fields.append('publication_date')

    # Abort if any required properties are missing
    if missing_properties:
        error_msg = f"Cannot create item: Required properties missing in Wikibase: {', '.join(missing_properties)}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Abstract
    if publication.abstract and check_property_exists(P_ABSTRACT):
        # Truncate if too long (Wikidata has limits)
        abstract_text = publication.abstract[:5000] if len(publication.abstract) > 5000 else publication.abstract
        statements.append(String(prop_nr=get_local_property_id(P_ABSTRACT), value=abstract_text))
        exported_fields.append('abstract')

    # DOI
    if publication.doi and check_property_exists(P_DOI):
        statements.append(ExternalID(prop_nr=get_local_property_id(P_DOI), value=publication.doi))
        exported_fields.append('doi')

    # URL
    if publication.url and check_property_exists(P_URL):
        statements.append(Url(prop_nr=get_local_property_id(P_URL), value=publication.url))
        exported_fields.append('url')

    # Authors
    if check_property_exists(P_AUTHOR_STRING):
        if publication.authors:
            for author in publication.authors:
                if author and author.strip():
                    statements.append(String(prop_nr=get_local_property_id(P_AUTHOR_STRING), value=author.strip()))
            exported_fields.append('authors')
        # Fallback to creator username if no authors
        elif publication.created_by:
            statements.append(String(prop_nr=get_local_property_id(P_AUTHOR_STRING), value=publication.created_by.username))
            exported_fields.append('created_by_as_author')

    # Keywords
    if check_property_exists(P_KEYWORDS):
        if publication.keywords:
            for keyword in publication.keywords:
                if keyword and keyword.strip():
                    statements.append(String(prop_nr=get_local_property_id(P_KEYWORDS), value=keyword.strip()))
            exported_fields.append('keywords')

        # Topics (from OpenAlex)
        if publication.topics:
            for topic in publication.topics:
                if topic and topic.strip():
                    statements.append(String(prop_nr=get_local_property_id(P_KEYWORDS), value=f"Topic: {topic.strip()}"))
            exported_fields.append('topics')

    # Time period - start date
    if publication.timeperiod_startdate and check_property_exists(P_PERIOD_START):
        add_time_claims(publication.timeperiod_startdate, get_local_property_id(P_PERIOD_START), statements, is_end_date=False)
        exported_fields.append('timeperiod_start')

    # Time period - end date
    if publication.timeperiod_enddate and check_property_exists(P_PERIOD_END):
        add_time_claims(publication.timeperiod_enddate, get_local_property_id(P_PERIOD_END), statements, is_end_date=True)
        exported_fields.append('timeperiod_end')

    # Source/Journal
    if publication.source:
        # Export as monolingual text name
        if check_property_exists(P_JOURNAL_NAME):
            statements.append(MonolingualText(prop_nr=get_local_property_id(P_JOURNAL_NAME), text=publication.source.name, language="en"))
            exported_fields.append('source_name')

        # If source has ISSN-L
        if publication.source.issn_l and check_property_exists(P_ISSN_L):
            statements.append(ExternalID(prop_nr=get_local_property_id(P_ISSN_L), value=publication.source.issn_l))
            exported_fields.append('source_issn_l')

    # OpenAlex ID
    if publication.openalex_id and check_property_exists(P_OPENALEX_ID):
        # Clean the ID (remove URL prefix if present)
        openalex_clean = publication.openalex_id.replace('https://openalex.org/', '')
        statements.append(ExternalID(prop_nr=get_local_property_id(P_OPENALEX_ID), value=openalex_clean))
        exported_fields.append('openalex_id')

    # OpenAlex IDs (PMID, PMC, etc.)
    if publication.openalex_ids and isinstance(publication.openalex_ids, dict):
        if publication.openalex_ids.get('pmid') and check_property_exists(P_PMID):
            pmid = str(publication.openalex_ids['pmid']).replace('https://pubmed.ncbi.nlm.nih.gov/', '')
            statements.append(ExternalID(prop_nr=get_local_property_id(P_PMID), value=pmid))
            exported_fields.append('pmid')

        if publication.openalex_ids.get('pmcid') and check_property_exists(P_PMC):
            pmcid = str(publication.openalex_ids['pmcid']).replace('https://www.ncbi.nlm.nih.gov/pmc/articles/', '')
            statements.append(ExternalID(prop_nr=get_local_property_id(P_PMC), value=pmcid))
            exported_fields.append('pmcid')

    # OpenAlex retracted status
    if publication.openalex_is_retracted and check_property_exists(P_RETRACTED):
        if check_item_exists("Q7594826"):  # retracted paper item
            statements.append(Item(prop_nr=get_local_property_id(P_RETRACTED), value="Q7594826"))
            exported_fields.append('is_retracted')

    # Geometry - center coordinate of bounding box and extreme points
    if publication.geometry:
        try:
            # Add center coordinate
            if check_property_exists(P_GEOMETRY):
                center = publication.get_center_coordinate()
                if center:
                    lon, lat = center
                    statements.append(GlobeCoordinate(
                        prop_nr=get_local_property_id(P_GEOMETRY),
                        latitude=lat,
                        longitude=lon,
                        precision=0.0001,
                        globe='http://www.wikidata.org/entity/Q2'  # Earth
                    ))
                    exported_fields.append('geometry_center')
                    logger.debug(f"Added center coordinate for publication {publication.id}: ({lon}, {lat})")
                else:
                    logger.warning(f"Could not calculate center coordinate for publication {publication.id}")

            # Add extreme points (northernmost, southernmost, easternmost, westernmost)
            extreme_points = publication.get_extreme_points()
            if extreme_points:
                # Northernmost point
                if extreme_points['north'] and check_property_exists(P_NORTHERNMOST_POINT):
                    lon, lat = extreme_points['north']
                    statements.append(GlobeCoordinate(
                        prop_nr=get_local_property_id(P_NORTHERNMOST_POINT),
                        latitude=lat,
                        longitude=lon,
                        precision=0.0001,
                        globe='http://www.wikidata.org/entity/Q2'
                    ))
                    exported_fields.append('geometry_north')
                    logger.debug(f"Added northernmost point for publication {publication.id}: ({lon}, {lat})")

                # Southernmost point
                if extreme_points['south'] and check_property_exists(P_SOUTHERNMOST_POINT):
                    lon, lat = extreme_points['south']
                    statements.append(GlobeCoordinate(
                        prop_nr=get_local_property_id(P_SOUTHERNMOST_POINT),
                        latitude=lat,
                        longitude=lon,
                        precision=0.0001,
                        globe='http://www.wikidata.org/entity/Q2'
                    ))
                    exported_fields.append('geometry_south')
                    logger.debug(f"Added southernmost point for publication {publication.id}: ({lon}, {lat})")

                # Easternmost point
                if extreme_points['east'] and check_property_exists(P_EASTERNMOST_POINT):
                    lon, lat = extreme_points['east']
                    statements.append(GlobeCoordinate(
                        prop_nr=get_local_property_id(P_EASTERNMOST_POINT),
                        latitude=lat,
                        longitude=lon,
                        precision=0.0001,
                        globe='http://www.wikidata.org/entity/Q2'
                    ))
                    exported_fields.append('geometry_east')
                    logger.debug(f"Added easternmost point for publication {publication.id}: ({lon}, {lat})")

                # Westernmost point
                if extreme_points['west'] and check_property_exists(P_WESTERNMOST_POINT):
                    lon, lat = extreme_points['west']
                    statements.append(GlobeCoordinate(
                        prop_nr=get_local_property_id(P_WESTERNMOST_POINT),
                        latitude=lat,
                        longitude=lon,
                        precision=0.0001,
                        globe='http://www.wikidata.org/entity/Q2'
                    ))
                    exported_fields.append('geometry_west')
                    logger.debug(f"Added westernmost point for publication {publication.id}: ({lon}, {lat})")

        except Exception as e:
            logger.warning(f"Error processing geometry for publication {publication.id}: {e}")

    # Log how many fields were checked vs exported
    logger.info(f"Built {len(statements)} statements from {len(exported_fields)} fields for publication {publication.id}")

    return statements, exported_fields


def create_export_log(publication, action, qid=None, exported_fields=None, error_message=None, summary=None, endpoint=None):
    """
    Create a WikidataExportLog entry for this export.
    """
    from publications.models import WikidataExportLog

    wikidata_url = None
    if qid:
        wikidata_url = f"{WIKIBASE_URL}{qid}"

    log_entry = WikidataExportLog.objects.create(
        publication=publication,
        action=action,
        wikidata_qid=qid,
        wikidata_url=wikidata_url,
        exported_fields=exported_fields or [],
        error_message=error_message,
        export_summary=summary,
        wikibase_endpoint=endpoint or settings.WIKIBASE_API_URL
    )

    return log_entry


def upsert_publication(publication, wikibase_integrator, dryrun=False):
    """
    Create or update a single Publication on Wikibase with comprehensive logging.

    Args:
        publication: Publication object to export
        wikibase_integrator: WikibaseIntegrator client instance
        dryrun: If True, simulate the export without writing to Wikibase

    Returns a tuple (action, qid, log_entry):
      - action is "created", "updated", "skipped", or "error"
      - qid is the Wikibase item ID (or None if error/skipped)
      - log_entry is the WikidataExportLog instance (or None if dryrun)
    """
    try:
        # Build statements
        statements, exported_fields = build_statements(publication)

        # Check for existing item by DOI first, then fall back to OpenAlex ID
        existing_qid = None
        if publication.doi:
            existing_qid = find_local_item_by_doi(publication.doi)
            if existing_qid:
                logger.debug(f"Found existing item {existing_qid} by DOI {publication.doi}")

        # Fallback to OpenAlex ID if DOI didn't find a match
        if not existing_qid and publication.openalex_id:
            existing_qid = find_local_item_by_openalex_id(publication.openalex_id)
            if existing_qid:
                logger.info(f"Found existing item {existing_qid} by OpenAlex ID {publication.openalex_id} (DOI lookup failed or no DOI)")

        if dryrun:
            # Dry-run mode: simulate the export without writing
            if existing_qid:
                action = "updated"
                summary = f"[DRY-RUN] Would update {len(exported_fields)} fields: {', '.join(exported_fields)}"
                logger.info(f"[DRY-RUN] Would update Wikidata item {existing_qid} for publication {publication.id}")
            else:
                action = "created"
                summary = f"[DRY-RUN] Would create with {len(exported_fields)} fields: {', '.join(exported_fields)}"
                logger.info(f"[DRY-RUN] Would create new Wikidata item for publication {publication.id}")

            # Return action without creating log entry in dryrun mode
            return action, existing_qid, None

        if existing_qid:
            # Update existing item
            try:
                entity = wikibase_integrator.item.get(entity_id=existing_qid)

                # Check which properties already exist on the item
                existing_properties = set(entity.claims.keys())
                logger.debug(f"Existing item {existing_qid} has properties: {sorted(existing_properties)}")

                # Filter statements to only include properties that don't exist yet
                new_statements = []
                added_fields = []
                skipped_fields = []

                for i, statement in enumerate(statements):
                    prop_id = statement.mainsnak.property_number
                    field_name = exported_fields[i] if i < len(exported_fields) else 'unknown'

                    if prop_id not in existing_properties:
                        new_statements.append(statement)
                        added_fields.append(field_name)
                        logger.debug(f"Will add property {prop_id} ({field_name}) to item {existing_qid}")
                    else:
                        skipped_fields.append(field_name)
                        logger.debug(f"Skipping property {prop_id} ({field_name}) - already exists on item {existing_qid}")

                # Only write if there are new statements to add
                if new_statements:
                    # Add claims to the entity
                    entity.claims.add(new_statements)

                    # Use WikibaseIntegrator's get_json() to get the data dict, then remove labels/descriptions
                    # This is the most reliable way to prevent label conflicts
                    try:
                        # Get the JSON representation
                        json_data = entity.get_json()

                        # Only manipulate JSON if it's a dict (not a Mock or other type)
                        if isinstance(json_data, dict):
                            # Remove labels, descriptions, and aliases from the JSON
                            # to ensure they're not sent to the API
                            json_data.pop('labels', None)
                            json_data.pop('descriptions', None)
                            json_data.pop('aliases', None)

                            # Manually call the write with the modified JSON
                            from wikibaseintegrator.wbi_helpers import edit_entity

                            result = edit_entity(
                                data=json_data,
                                id=existing_qid,
                                type='item',
                                summary=f"Add {len(new_statements)} missing properties via OptimapBot",
                                clear=False,
                                is_bot=False,
                                allow_anonymous=False,
                                login=wikibase_integrator.login
                            )

                            logger.debug(f"Successfully added {len(new_statements)} properties to {existing_qid}")
                        else:
                            # Fallback to regular write if get_json doesn't work (e.g., in tests)
                            logger.warning(f"get_json() didn't return a dict, using fallback write method")
                            entity.write(summary=f"Add {len(new_statements)} missing properties via OptimapBot", clear=False)

                    except ModificationFailed as e:
                        if "already has label" in str(e):
                            # This shouldn't happen now, but log it if it does
                            logger.error(f"Label conflict persists for {existing_qid} even with labels removed: {e}")
                            # Mark as skipped
                            return "skipped", existing_qid, create_export_log(
                                publication=publication,
                                action='skipped',
                                qid=existing_qid,
                                exported_fields=added_fields,
                                summary=f"Skipped due to label conflict: {str(e)}"
                            )
                        else:
                            raise

                    summary = f"Added {len(added_fields)} new fields: {', '.join(added_fields)}"
                    if skipped_fields:
                        summary += f" (skipped {len(skipped_fields)} existing: {', '.join(skipped_fields)})"

                    logger.info(f"Updated Wikidata item {existing_qid} for publication {publication.id} - added {len(added_fields)} properties")
                else:
                    summary = f"No new properties to add (all {len(exported_fields)} fields already exist)"
                    logger.info(f"Wikidata item {existing_qid} for publication {publication.id} already has all properties - no update needed")

                log_entry = create_export_log(
                    publication=publication,
                    action='updated',
                    qid=existing_qid,
                    exported_fields=added_fields if new_statements else exported_fields,
                    summary=summary
                )

                return "updated", existing_qid, log_entry

            except ModificationFailed as e:
                if "already has label" in str(e):
                    log_entry = create_export_log(
                        publication=publication,
                        action='skipped',
                        qid=existing_qid,
                        exported_fields=exported_fields,
                        summary="Skipped: label already exists"
                    )
                    return "skipped", existing_qid, log_entry
                raise
        else:
            # Create new item
            try:
                entity = wikibase_integrator.item.new()
                entity.labels.set("en", publication.title[:250])  # Wikidata label limit
                entity.descriptions.set("en", "Publication imported from OPTIMAP")
                entity.claims.add(statements)

                entity_result = entity.write(summary="Create publication via OptimapBot - comprehensive metadata")
                created_qid = entity_result.id  # ItemEntity has an .id attribute after write()

                summary = f"Created with {len(exported_fields)} fields: {', '.join(exported_fields)}"
                log_entry = create_export_log(
                    publication=publication,
                    action='created',
                    qid=created_qid,
                    exported_fields=exported_fields,
                    summary=summary
                )

                logger.info(f"Created Wikidata item {created_qid} for publication {publication.id}")
                return "created", created_qid, log_entry

            except ModificationFailed as e:
                if "already has label" in str(e):
                    log_entry = create_export_log(
                        publication=publication,
                        action='skipped',
                        exported_fields=exported_fields,
                        error_message=str(e),
                        summary="Skipped: label already exists"
                    )
                    return "skipped", None, log_entry
                raise

    except Exception as err:
        # Get detailed error information
        error_type = type(err).__name__
        error_msg = str(err)
        error_traceback = traceback.format_exc()

        # Combine short and detailed error info
        short_error = f"{error_type}: {error_msg}"
        detailed_error = f"{short_error}\n\nFull traceback:\n{error_traceback}"

        log_entry = create_export_log(
            publication=publication,
            action='error',
            error_message=detailed_error,
            summary=f"Export failed: {error_type}"
        )
        logger.error(f"Error exporting publication {publication.id} to Wikidata: {short_error}")
        logger.debug(f"Full traceback for publication {publication.id}:\n{error_traceback}")
        return "error", None, log_entry


def _export_publications_to_wikidata_internal(publications, progress_callback=None, dryrun=False):
    """
    Internal function to export multiple publications to Wikidata with comprehensive logging.

    Args:
        publications: QuerySet or list of Publication objects
        progress_callback: Optional function(current, total, publication) for progress updates
        dryrun: If True, simulate the export without writing to Wikibase

    Returns:
        dict with statistics: {
            'created': int,
            'updated': int,
            'skipped': int,
            'errors': int,
            'total': int,
            'log_entries': list of WikidataExportLog objects
        }
    """
    # Initialize login and Wikibase client using OAuth1 (even for dryrun to validate credentials)
    login_session = get_wikibase_login()
    wikibase_client = WikibaseIntegrator(login=login_session)

    stats = {
        'created': 0,
        'updated': 0,
        'skipped': 0,
        'errors': 0,
        'total': 0,
        'log_entries': []
    }

    publications_list = list(publications)
    total = len(publications_list)

    mode_label = "[DRY-RUN] " if dryrun else ""
    logger.info(f"{mode_label}Starting Wikibase export for {total} publication(s) to {settings.WIKIBASE_API_URL}")

    for idx, publication in enumerate(publications_list, 1):
        stats['total'] += 1

        logger.debug(f"{mode_label}Processing publication {idx}/{total}: ID={publication.id}, Title='{publication.title[:50]}...'")

        # Skip if missing required fields
        if not publication.publicationDate:
            logger.info(f"{mode_label}Skipping publication {publication.id} ('{publication.title[:50]}...') - missing publication date")
            if not dryrun:
                log_entry = create_export_log(
                    publication=publication,
                    action='error',
                    error_message="Missing required field: publicationDate",
                    summary="Export skipped due to missing publication date"
                )
                stats['log_entries'].append(log_entry)
            stats['errors'] += 1

            if progress_callback:
                progress_callback(idx, total, publication)
            continue

        # Attempt export
        logger.debug(f"{mode_label}Calling upsert_publication for publication {publication.id}")
        action, qid, log_entry = upsert_publication(publication, wikibase_client, dryrun=dryrun)
        logger.info(f"{mode_label}Publication {publication.id} - Action: {action}, QID: {qid}")

        # Update statistics
        if action == "created":
            stats['created'] += 1
            logger.info(f"{mode_label}Created new item {qid} for publication {publication.id}")
        elif action == "updated":
            stats['updated'] += 1
            logger.info(f"{mode_label}Updated existing item {qid} for publication {publication.id}")
        elif action == "skipped":
            stats['skipped'] += 1
            logger.debug(f"{mode_label}Skipped publication {publication.id} (QID: {qid})")
        elif action == "error":
            stats['errors'] += 1
            logger.warning(f"{mode_label}Error exporting publication {publication.id}: {log_entry.error_message[:100] if log_entry and log_entry.error_message else 'Unknown error'}")

        if log_entry:
            stats['log_entries'].append(log_entry)

        # Progress callback
        if progress_callback:
            progress_callback(idx, total, publication)

    logger.info(f"{mode_label}Wikibase export complete: Created={stats['created']}, Updated={stats['updated']}, Skipped={stats['skipped']}, Errors={stats['errors']}, Total={stats['total']}")

    return stats


def export_publications_to_wikidata(publications, progress_callback=None):
    """
    Export multiple publications to Wikidata/Wikibase (actual write operation).

    Args:
        publications: QuerySet or list of Publication objects
        progress_callback: Optional function(current, total, publication) for progress updates

    Returns:
        dict with statistics
    """
    return _export_publications_to_wikidata_internal(publications, progress_callback, dryrun=False)


def export_publications_to_wikidata_dryrun(publications, progress_callback=None):
    """
    Simulate export of publications to Wikidata/Wikibase without writing (dry-run mode).

    Args:
        publications: QuerySet or list of Publication objects
        progress_callback: Optional function(current, total, publication) for progress updates

    Returns:
        dict with statistics (no log entries created)
    """
    return _export_publications_to_wikidata_internal(publications, progress_callback, dryrun=True)
