import time
import random
import requests
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from src.utils.logger import get_logger

logger = get_logger(__name__)

class BaseService(ABC):
    """
    Base class for each service provider.
    Handles HTTP requests, retry logic, and API rate limiting.
    """

    def __init__(self, name: str):
        self.name = name
        self.session = requests.Session()

    def make_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        max_retries: int = 10
    ) -> Dict[str, Any]:
        """
        Generic request sender with built-in retry logic.
        """
        # Small randomized delay to avoid overwhelming APIs when parallelized
        time.sleep(random.uniform(0.1, 1.0))

        for attempt in range(max_retries):
            try:
                if method.upper() == "POST":
                    response = self.session.post(url, headers=headers, json=json_data, timeout=(15, 30))
                else:
                    response = self.session.get(url, headers=headers, timeout=(15, 30))

                if response.status_code == 429:
                    sleep_time = (1.5 ** attempt) + random.uniform(1.0, 3.0)
                    logger.warning(
                        "[%s] Rate limit (429) / Server busy. Retrying in %.1fs... (Attempt %d/%d)",
                        self.name, sleep_time, attempt + 1, max_retries
                    )
                    time.sleep(sleep_time)
                    continue

                if response.status_code == 404:
                    return {"error": "Not Found (404)"}
                if response.status_code == 400:
                    return {"error": "Bad Request (400) - Check payload/entity format"}

                response.raise_for_status()
                return response.json()

            except requests.exceptions.ReadTimeout:
                sleep_time = 3.0 + attempt
                logger.warning(
                    "[%s] Timeout. Retrying in %.1fs... (Attempt %d/%d)",
                    self.name, sleep_time, attempt + 1, max_retries
                )
                time.sleep(sleep_time)

            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    return {"error": f"Network error: {str(e)[:50]}"}
                time.sleep(2.0 + (attempt * 1.5))

        return {"error": f"Max retries ({max_retries}) exceeded"}

    @abstractmethod
    def fetch_data(self, entity_id: str, reference_id: str = "") -> Dict[str, Any]:
        """Send API request to the service provider for the given entity."""
        raise NotImplementedError

    @abstractmethod
    def parse_response(self, raw_data: Dict[str, Any], target_location: str = "") -> Dict[str, Any]:
        """Extract required fields from raw provider JSON response."""
        raise NotImplementedError
