import requests
from typing import Dict, Any, Optional

class PromClient:
    """
    A client for querying the Prometheus HTTP API.
    """
    def __init__(self, endpoint: str):
        if not endpoint.startswith("http"):
            raise ValueError("Prometheus endpoint must be a valid URL (e.g., 'http://localhost:9090')")
        self.endpoint = endpoint.rstrip('/')
        print(f"[PromClient] Initialized with endpoint: {self.endpoint}")
        
    def query(self, promql_query: str) -> Optional[float]:
        """
        Executes a PromQL query and returns the value of the first result.
        Returns None if the query fails or no results are found.
        """
        api_url = f"{self.endpoint}/api/v1/query"
        params = {'query': promql_query}
        try:
            response = requests.get(api_url, params=params, timeout=10)
            response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
            result = response.json()
            
            if result['status'] == 'success' and result['data']['result']:
                # The value is a tuple: [timestamp, value]. We only need the value.
                value = float(result['data']['result'][0]['value'][1])
                return value
            
            return None
            
        except requests.exceptions.RequestException as e:
            print(f"[PromClient] ERROR: Failed to query Prometheus at {api_url}: {e}")
            return None
        except (KeyError, IndexError, ValueError) as e:
            print(f"[PromClient] ERROR: Unexpected response format from Prometheus: {e}")
            return None
