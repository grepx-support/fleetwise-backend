"""
OneMap API Service

Simple service to get address from postal code for Singapore.
"""

import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_address_from_postal_code(postal_code: str, country: str = "Singapore") -> Optional[str]:
    """
    Get address from postal code and country.

    Args:
        postal_code: Postal code to search
        country: Country name (currently only supports 'Singapore')

    Returns:
        Address string if found, None otherwise
    """
    if country.lower() != 'singapore':
        logger.warning(f"Country '{country}' not supported, only Singapore is supported")
        return None

    url = "https://www.onemap.gov.sg/api/common/elastic/search"

    params = {
        "searchVal": postal_code,
        "returnGeom": "Y",
        "getAddrDetails": "Y",
        "pageNum": 1
    }

    try:
        logger.debug(f"Calling OneMap API for postal code: {postal_code}")
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        result = response.json()

        logger.debug(f"OneMap API response: found={result.get('found', 0)}")

        if result.get('found', 0) > 0 and result.get('results'):
            address = result['results'][0].get('ADDRESS')
            logger.info(f"OneMap API found address for {postal_code}: {address}")
            return address

        logger.warning(f"OneMap API returned no results for postal code: {postal_code}")
        return None

    except Exception as e:
        logger.error(f"OneMap API error for postal code {postal_code}: {str(e)}")
        return None
