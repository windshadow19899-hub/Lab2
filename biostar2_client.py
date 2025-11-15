"""Client utilities for interacting with the Suprema BioStar2 API.

This module provides a small convenience wrapper around the REST endpoints that
are relevant for building an internal attendance dashboard.  Only a subset of
endpoints are implemented (login, attendance events and leave requests), but the
structure makes it easy to add more calls when required.

The official API has a few variations depending on the on-premise server
version.  Whenever possible the client attempts to handle the common response
shapes (session token stored under ``token``, ``session_id`` or ``bs_session``).
If your installation returns the token under a different key you can pass a
custom ``token_path`` argument when instantiating the client.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional

import requests

LOGGER = logging.getLogger(__name__)


class BioStar2Error(RuntimeError):
    """Raised when the BioStar2 server reports an error."""


@dataclass
class BioStar2Client:
    """Small helper around the BioStar2 REST API.

    Parameters
    ----------
    base_url:
        Base URL of the BioStar2 server (``https://example.com``).  The client
        will automatically append endpoint specific paths.
    username / password:
        Credentials used for authenticating against ``/v2/login``.  The client
        stores the issued session token and reuses it until it expires.
    verify_ssl:
        When ``False`` the underlying ``requests`` session will ignore TLS
        certificate verification.  This can be handy for on-premise servers
        using self-signed certificates but should be avoided for production
        systems whenever possible.
    timeout:
        Socket timeout (in seconds) applied to HTTP requests.
    token_path:
        Optional dotted path that indicates where the session token resides in
        the JSON response.  When omitted the client attempts to detect the
        token automatically using the most common field names.
    """

    base_url: str
    username: str
    password: str
    verify_ssl: bool = True
    timeout: int = 30
    token_path: Optional[str] = None
    session: requests.Session = field(default_factory=requests.Session)

    _session_token: Optional[str] = field(default=None, init=False, repr=False)
    _token_expiry_epoch: Optional[float] = field(default=None, init=False, repr=False)

    LOGIN_ENDPOINT: str = "/v2/login"
    ATTENDANCE_EVENTS_ENDPOINT: str = "/v2/attendance/events"
    LEAVES_ENDPOINT: str = "/v2/attendance/leaves"

    def __post_init__(self) -> None:
        self.session.verify = self.verify_ssl

    # ------------------------------------------------------------------
    # Authentication helpers
    def authenticate(self, force: bool = False) -> str:
        """Ensure that a valid session token is available.

        When ``force`` is ``True`` a new login request is performed even if a
        cached token is still considered valid.
        """

        if not force and self._session_token and not self._token_expired:
            return self._session_token

        LOGGER.debug("Authenticating with BioStar2 server at %s", self.base_url)
        try:
            response = self.session.post(
                self._url(self.LOGIN_ENDPOINT),
                json={"user_id": self.username, "login_id": self.username, "password": self.password},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:  # pragma: no cover - network failure safeguard
            raise BioStar2Error(f"Failed to contact BioStar2 server at {self.base_url}: {exc}") from exc

        data = self._json(response)
        if response.status_code >= 400:
            message = data.get("message") if isinstance(data, dict) else response.text
            raise BioStar2Error(
                f"BioStar2 login failed with status {response.status_code}: {message}"
            )

        token = self._extract_token(data)
        if not token:
            raise BioStar2Error(
                "Failed to obtain session token from login response. "
                "Set 'token_path' if your server uses a custom response shape."
            )

        self._session_token = token
        self._token_expiry_epoch = self._detect_expiry(data)
        LOGGER.debug("Authentication succeeded; token expires at %s", self._token_expiry_epoch)
        return token

    # ------------------------------------------------------------------
    # Attendance helpers
    def iter_attendance_events(
        self,
        start_datetime: str,
        end_datetime: str,
        user_ids: Optional[Iterable[str]] = None,
        page_size: int = 100,
    ) -> Iterator[Dict[str, Any]]:
        """Iterate over attendance events within the provided time range.

        Parameters
        ----------
        start_datetime, end_datetime:
            ISO 8601 strings (``YYYY-MM-DDTHH:MM:SS``) describing the time
            window.
        user_ids:
            Optional iterable of BioStar2 user IDs used to filter the response.
        page_size:
            Number of records to request per API call.  The BioStar2 API uses
            the ``limit``/``offset`` pagination scheme.
        """

        params: Dict[str, Any] = {
            "datetime__gte": start_datetime,
            "datetime__lte": end_datetime,
            "limit": page_size,
            "offset": 0,
        }
        if user_ids:
            params["user_id__in"] = ",".join(user_ids)

        while True:
            data = self._request("GET", self.ATTENDANCE_EVENTS_ENDPOINT, params=params)
            records = data.get("records", [])
            if not records:
                break

            for record in records:
                yield record

            params["offset"] += len(records)
            if params["offset"] >= data.get("total", 0):
                break

    def get_attendance_events(
        self,
        start_datetime: str,
        end_datetime: str,
        user_ids: Optional[Iterable[str]] = None,
        page_size: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return attendance events as a list."""

        return list(
            self.iter_attendance_events(
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                user_ids=user_ids,
                page_size=page_size,
            )
        )

    # ------------------------------------------------------------------
    # Leave helpers
    def iter_leaves(
        self,
        start_date: str,
        end_date: str,
        user_ids: Optional[Iterable[str]] = None,
        page_size: int = 100,
    ) -> Iterator[Dict[str, Any]]:
        """Iterate over leave (absence) records within the provided date range."""

        params: Dict[str, Any] = {
            "start_datetime__gte": f"{start_date}T00:00:00",
            "end_datetime__lte": f"{end_date}T23:59:59",
            "limit": page_size,
            "offset": 0,
        }
        if user_ids:
            params["user_id__in"] = ",".join(user_ids)

        while True:
            data = self._request("GET", self.LEAVES_ENDPOINT, params=params)
            records = data.get("records", [])
            if not records:
                break

            for record in records:
                yield record

            params["offset"] += len(records)
            if params["offset"] >= data.get("total", 0):
                break

    def get_leaves(
        self,
        start_date: str,
        end_date: str,
        user_ids: Optional[Iterable[str]] = None,
        page_size: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return leave records as a list."""

        return list(self.iter_leaves(start_date, end_date, user_ids=user_ids, page_size=page_size))

    # ------------------------------------------------------------------
    # Low level helpers
    def _request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        token = self.authenticate()
        headers = kwargs.pop("headers", {})
        headers.setdefault("bs-session-id", token)
        headers.setdefault("Authorization", f"Bearer {token}")

        try:
            response = self.session.request(
                method,
                self._url(path),
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:  # pragma: no cover - network failure safeguard
            raise BioStar2Error(f"Failed to contact BioStar2 server at {self.base_url}: {exc}") from exc
        data = self._json(response)
        if response.status_code >= 400:
            message = data.get("message") if isinstance(data, dict) else response.text
            raise BioStar2Error(f"BioStar2 request failed with status {response.status_code}: {message}")

        return data if isinstance(data, dict) else {"raw": data}

    def _json(self, response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - helpful message only when server misbehaves
            raise BioStar2Error(f"Failed to decode JSON response from {response.url}") from exc

    @property
    def _token_expired(self) -> bool:
        if not self._session_token:
            return True
        if not self._token_expiry_epoch:
            return False
        # Add a 30 second safety margin to avoid racing the expiration time.
        return (self._token_expiry_epoch - 30) <= time.time()

    def _extract_token(self, data: Any) -> Optional[str]:
        if not data:
            return None

        if self.token_path:
            return self._lookup_path(data, self.token_path)

        common_keys = [
            "token",
            "access_token",
            "session_id",
            "sessionId",
            "bs_session_id",
            "session",
        ]

        # direct key lookup
        if isinstance(data, dict):
            for key in common_keys:
                if key in data and data[key]:
                    return str(data[key])

            # some deployments respond with {"data": {"token": "..."}}
            nested = data.get("data")
            if isinstance(nested, dict):
                for key in common_keys:
                    if key in nested and nested[key]:
                        return str(nested[key])

            # swagger examples use {"records": [{"session_id": "..."}]}
            records = data.get("records")
            if isinstance(records, list) and records:
                first = records[0]
                if isinstance(first, dict):
                    for key in common_keys:
                        if key in first and first[key]:
                            return str(first[key])

        return None

    def _detect_expiry(self, data: Any) -> Optional[float]:
        if not data:
            return None

        expiry_fields = [
            "expires_in",
            "expiry",
            "expire",
            "expiration",
            "session_expire",
        ]
        source: Optional[Any] = None
        if isinstance(data, dict):
            source = data
            if "data" in data and isinstance(data["data"], dict):
                source = data["data"]
        if not source:
            return None

        for key in expiry_fields:
            if key in source:
                value = source[key]
                try:
                    seconds = float(value)
                    return time.time() + seconds
                except (TypeError, ValueError):
                    continue
        return None

    def _lookup_path(self, payload: Any, path: str) -> Optional[str]:
        current = payload
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    index = int(part)
                except ValueError:
                    return None
                if index >= len(current):
                    return None
                current = current[index]
            else:
                return None
        if current is None:
            return None
        return str(current)

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url.rstrip('/')}{path}"


__all__ = ["BioStar2Client", "BioStar2Error"]
