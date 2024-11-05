from datetime import datetime, timedelta
from typing import Any, Dict, Optional

class Cache:
    def __init__(self, ttl_seconds: int = 300):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl_seconds = ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        if key not in self._cache:
            return None
        
        cache_entry = self._cache[key]
        if datetime.now() > cache_entry['expires']:
            del self._cache[key]
            return None
            
        return cache_entry['data']

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = {
            'data': value,
            'expires': datetime.now() + timedelta(seconds=self._ttl_seconds)
        }

    def clear(self) -> None:
        self._cache.clear()
