"""API client for Where's the Bus."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

from .const import (
    LOGIN_URL,
    RIDER_API_URL_TEMPLATE,
    RIDER_PAGE_URL_TEMPLATE,
    SESSION_URL_TEMPLATE,
    STUDENT_SCANS_URL_TEMPLATE,
    DEFAULT_SUBDOMAIN,
    DEFAULT_SHARD,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class RiderInfo:
    """Information about a rider/student."""

    child_id: str
    student_id: str
    name: str
    school: str
    am_bus_no: str | None
    am_stop_time: str | None
    am_stop_address: str | None
    am_stop_lat: float | None
    am_stop_lon: float | None
    pm_bus_no: str | None
    pm_stop_time: str | None
    pm_stop_address: str | None
    pm_stop_lat: float | None
    pm_stop_lon: float | None


@dataclass
class StudentScan:
    """A student RFID/tablet scan event."""

    student_name: str
    scan_time: int  # Unix timestamp
    scan_location: str
    scan_method: str  # "RFID" or "Tablet"
    bus: str


@dataclass
class BusStatus:
    """Current bus tracking status."""

    bus_id: str
    bus_number: str
    is_tracking: bool
    latitude: float | None
    longitude: float | None
    eta_minutes: int | None
    eta_time: str | None
    distance_away: float | None
    distance_unit: str | None
    gps_status: str | None
    heading: str | None
    speed: float | None
    last_update: str | None


class WheresTheBusApiError(Exception):
    """Base exception for API errors."""


class WheresTheBusAuthError(WheresTheBusApiError):
    """Authentication error."""


class WheresTheBusApi:
    """API client for Where's the Bus."""

    def __init__(
        self,
        email: str,
        password: str,
        subdomain: str = DEFAULT_SUBDOMAIN,
        shard: str = DEFAULT_SHARD,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the API client."""
        self._email = email
        self._password = password
        self._subdomain = subdomain
        self._shard = shard
        self._session = session
        self._owns_session = session is None

        # Session data
        self._cookies: dict[str, str] = {}
        self._app_id: str | None = None
        self._user_guid: str | None = None
        self._riders: list[RiderInfo] = []
        self._bus_ids: dict[str, str] = {}  # child_id -> bus_id mapping

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the API client."""
        if self._owns_session and self._session:
            await self._session.close()
            self._session = None

    async def authenticate(self) -> bool:
        """Authenticate with Where's the Bus."""
        session = await self._get_session()

        try:
            # Step 1: Get login page to extract CSRF token
            async with session.get(LOGIN_URL) as response:
                if response.status != 200:
                    raise WheresTheBusAuthError(f"Failed to get login page: {response.status}")
                html = await response.text()

            # Extract CSRF token
            soup = BeautifulSoup(html, "html.parser")
            token_input = soup.find("input", {"name": "token"})
            token = token_input.get("value") if token_input else ""

            # Step 2: Submit login form
            login_data = {
                "form_id": "login",
                "success_dest": "https://wheresthebus.com",
                "email": self._email,
                "pw": self._password,
                "stay_logged_in": "stay_logged_in",
                "commit": "Sign in",
                "token": token,
            }

            async with session.post(
                LOGIN_URL,
                data=login_data,
                allow_redirects=False,
            ) as response:
                if response.status != 302:
                    raise WheresTheBusAuthError("Login failed - invalid credentials")

                location = response.headers.get("Location", "")
                if "session.php" not in location:
                    raise WheresTheBusAuthError("Login failed - unexpected redirect")

            # Step 3: Follow redirect to establish session (allow full redirect chain)
            _LOGGER.debug("Following session redirect to: %s", location)
            async with session.get(location, allow_redirects=True) as response:
                _LOGGER.debug("Session response status: %s, URL: %s", response.status, response.url)
                # We should end up at rider.php after all redirects
                html = await response.text()

                # Extract cookies
                for cookie in session.cookie_jar:
                    self._cookies[cookie.key] = cookie.value
                _LOGGER.debug("Cookies after session: %s", list(self._cookies.keys()))

            # Check if we ended up at the rider page
            if "rider.php" in str(response.url) or "s_app_id" in html:
                _LOGGER.debug("Already at rider page from session redirect")
                self._parse_rider_page(html)
            else:
                # Step 4: Get rider page explicitly
                rider_url = RIDER_PAGE_URL_TEMPLATE.format(
                    subdomain=self._subdomain,
                    shard=self._shard,
                )
                _LOGGER.debug("Fetching rider page: %s", rider_url)

                async with session.get(rider_url) as response:
                    if response.status != 200:
                        raise WheresTheBusAuthError(f"Failed to get rider page: {response.status}")
                    html = await response.text()
                    _LOGGER.debug("Rider page response URL: %s", response.url)

                # Parse rider page for configuration
                self._parse_rider_page(html)

            _LOGGER.info("Successfully authenticated with Where's the Bus")
            return True

        except aiohttp.ClientError as err:
            raise WheresTheBusApiError(f"Connection error: {err}") from err

    def _parse_rider_page(self, html: str) -> None:
        """Parse the rider page to extract configuration and rider info."""
        import json

        _LOGGER.debug("Parsing rider page, HTML length: %d", len(html))

        # Check if we got a login page instead
        if "au_login.php" in html or "Sign in" in html:
            _LOGGER.warning("Got login page instead of rider page - authentication may have failed")
            _LOGGER.debug("HTML snippet: %s", html[:500])
            return

        # Extract app_id
        app_id_match = re.search(r's_app_id\s*=\s*["\']([^"\']+)["\']', html)
        if app_id_match:
            self._app_id = app_id_match.group(1)
            _LOGGER.debug("Found app_id: %s", self._app_id)
        else:
            _LOGGER.warning("Could not find app_id in page")

        # Extract user_guid
        guid_match = re.search(r'(?:guid|user_guid)\s*=\s*["\']([^"\']+)["\']', html)
        if guid_match:
            self._user_guid = guid_match.group(1)
            _LOGGER.debug("Found user_guid: %s", self._user_guid)
        else:
            _LOGGER.warning("Could not find user_guid in page")

        # Extract bus_id and child_id from the loadPage call
        load_page_match = re.search(
            r'loadPage\(["\']rider\.php\?bid=([^&]+)&child_id=(\d+)&uid=([^&]+)',
            html,
        )
        if load_page_match:
            bus_id = load_page_match.group(1)
            child_id = load_page_match.group(2)
            self._bus_ids[child_id] = bus_id
            _LOGGER.debug("Found bus mapping from loadPage: child_id=%s -> bus_id=%s", child_id, bus_id)
            if not self._user_guid:
                self._user_guid = load_page_match.group(3)
        else:
            _LOGGER.warning("Could not find loadPage call in HTML")

        # Get child_id from var declaration (this is the ID used for API calls)
        child_id_match = re.search(r"var\s+child_id\s*=\s*['\"](\d+)['\"]", html)
        bus_id_match = re.search(r"var\s+bus_id\s*=\s*['\"]([^'\"]+)['\"]", html)

        api_child_id = child_id_match.group(1) if child_id_match else None
        api_bus_id = bus_id_match.group(1) if bus_id_match else None

        _LOGGER.debug("Var declarations: child_id=%s, bus_id=%s", api_child_id, api_bus_id)

        if api_child_id and api_bus_id:
            self._bus_ids[api_child_id] = api_bus_id
            _LOGGER.debug("Found var bus mapping: child_id=%s -> bus_id=%s", api_child_id, api_bus_id)
        else:
            _LOGGER.warning("Could not find var child_id or bus_id declarations")

        # Extract rider information from the openDeleteRiderDialog JSON
        # The JSON is already valid, just need to extract it properly
        # Match JSON that starts with {"  and ends with }
        rider_json_matches = re.findall(
            r'openDeleteRiderDialog\((\{".+?\})\)',
            html,
        )
        _LOGGER.debug("Found %d openDeleteRiderDialog matches", len(rider_json_matches))

        self._riders = []
        for rider_json_str in rider_json_matches:
            try:
                # The data is already valid JSON from the server
                rider_data = json.loads(rider_json_str)
                _LOGGER.debug("Parsed rider data: %s", rider_data.get("riderName"))

                # Use api_child_id for API calls, studentId is different
                # If we only have one rider, use the api_child_id
                effective_child_id = api_child_id if api_child_id else str(rider_data.get("studentId", ""))

                rider = RiderInfo(
                    child_id=effective_child_id,
                    student_id=str(rider_data.get("studentId", "")),
                    name=rider_data.get("riderName", "Unknown"),
                    school=rider_data.get("schoolName", "Unknown"),
                    am_bus_no=rider_data.get("amBusNo"),
                    am_stop_time=rider_data.get("amStopTime"),
                    am_stop_address=rider_data.get("amStopAddress"),
                    am_stop_lat=rider_data.get("amStopLat"),
                    am_stop_lon=rider_data.get("amStopLon"),
                    pm_bus_no=rider_data.get("pmBusNo"),
                    pm_stop_time=rider_data.get("pmStopTime"),
                    pm_stop_address=rider_data.get("pmStopAddress"),
                    pm_stop_lat=rider_data.get("pmStopLat"),
                    pm_stop_lon=rider_data.get("pmStopLon"),
                )
                self._riders.append(rider)
                _LOGGER.info("Found rider: %s (child_id=%s, student_id=%s)",
                            rider.name, rider.child_id, rider.student_id)
            except json.JSONDecodeError as err:
                _LOGGER.warning("Failed to parse rider JSON: %s - Raw: %s...", err, rider_json_str[:100])
            except KeyError as err:
                _LOGGER.warning("Missing key in rider data: %s", err)

        # Fallback: If no riders found from JSON, create one from the var data
        if not self._riders and api_child_id:
            _LOGGER.info("Creating rider from var data (child_id=%s)", api_child_id)
            # Try to extract rider name from page
            name_match = re.search(r'<h2[^>]*style="margin:\s*0[^"]*"[^>]*>([^<]+)</h2>\s*<h3[^>]*>([^<]+)</h3>', html)
            if not name_match:
                name_match = re.search(r'<h2[^>]*>([^<]+)</h2>\s*<h3[^>]*>([^<]+)</h3>', html)
            rider_name = name_match.group(1).strip() if name_match else "Unknown Rider"
            school_name = name_match.group(2).strip() if name_match else "Unknown School"

            bus_num = api_bus_id.lstrip("S") if api_bus_id and api_bus_id.startswith("S") else api_bus_id

            rider = RiderInfo(
                child_id=api_child_id,
                student_id=api_child_id,
                name=rider_name,
                school=school_name,
                am_bus_no=bus_num,
                am_stop_time=None,
                am_stop_address=None,
                am_stop_lat=None,
                am_stop_lon=None,
                pm_bus_no=bus_num,
                pm_stop_time=None,
                pm_stop_address=None,
                pm_stop_lat=None,
                pm_stop_lon=None,
            )
            self._riders.append(rider)

        _LOGGER.info("Parsed %d riders from page", len(self._riders))

    @property
    def riders(self) -> list[RiderInfo]:
        """Get list of riders."""
        return self._riders

    async def get_bus_status(self, child_id: str, bus_id: str | None = None, _retry: bool = False) -> BusStatus | None:
        """Get current bus status for a rider."""
        session = await self._get_session()

        if bus_id is None:
            bus_id = self._bus_ids.get(child_id)

        if not bus_id or not self._app_id:
            _LOGGER.error("Missing required data for API call: bus_id=%s, app_id=%s",
                         bus_id, self._app_id)
            return None

        api_url = RIDER_API_URL_TEMPLATE.format(
            subdomain=self._subdomain,
            shard=self._shard,
        )

        # The actual API uses sessionId, bid, chdId (not busId, appId, uid)
        payload = {
            "sessionId": self._app_id,
            "bid": bus_id,
            "chdId": int(child_id),
        }

        try:
            async with session.post(api_url, json=payload) as response:
                if response.status != 200:
                    _LOGGER.error("API request failed: %s", response.status)
                    return None

                data = await response.json()
                _LOGGER.debug("API response: resCode=%s, mesgStr=%s",
                             data.get("resCode"), data.get("mesgStr"))

                res_code = data.get("resCode")

                if res_code == 9:
                    # Session expired, need to re-authenticate (but only retry once)
                    if not _retry:
                        _LOGGER.info("Session expired, re-authenticating")
                        await self.authenticate()
                        return await self.get_bus_status(child_id, bus_id, _retry=True)
                    else:
                        _LOGGER.warning("Session still expired after re-auth - this may be normal outside bus hours")
                        # Return a default "not tracking" status instead of None
                        return BusStatus(
                            bus_id=bus_id,
                            bus_number=bus_id.lstrip("S") if bus_id.startswith("S") else bus_id,
                            is_tracking=False,
                            latitude=None,
                            longitude=None,
                            eta_minutes=None,
                            eta_time=None,
                            distance_away=None,
                            distance_unit=None,
                            gps_status="Session unavailable",
                            heading=None,
                            speed=None,
                            last_update=None,
                        )

                if res_code != 0:
                    msg = data.get("mesgStr", "Unknown error")
                    _LOGGER.debug("API returned non-zero code %s: %s", res_code, msg)
                    # Return a "not tracking" status for non-fatal errors
                    return BusStatus(
                        bus_id=bus_id,
                        bus_number=bus_id.lstrip("S") if bus_id.startswith("S") else bus_id,
                        is_tracking=False,
                        latitude=None,
                        longitude=None,
                        eta_minutes=None,
                        eta_time=None,
                        distance_away=None,
                        distance_unit=None,
                        gps_status=msg,
                        heading=None,
                        speed=None,
                        last_update=None,
                    )

                return self._parse_bus_status(data.get("payload", {}), bus_id)

        except aiohttp.ClientError as err:
            _LOGGER.error("API request error: %s", err)
            return None

    def _parse_bus_status(self, payload: dict[str, Any], bus_id: str) -> BusStatus:
        """Parse bus status from API response."""
        # Actual API response format:
        # busLat, busLon - bus coordinates
        # dist - distance in km
        # etaMsg - ETA in minutes (string)
        # stsMsg - status message ("current", etc.)
        # stsClr - status color
        # childBuses - list with routeNo, busNo, etc.

        # Get route number from childBuses if available
        child_buses = payload.get("childBuses", [])
        route_no = None
        if child_buses:
            route_no = child_buses[0].get("routeNo")

        # Parse ETA - it's a string like "13" for 13 minutes
        eta_str = payload.get("etaMsg", "")
        eta_minutes = None
        if eta_str and eta_str.isdigit():
            eta_minutes = int(eta_str)

        # Determine if tracking based on presence of bus coordinates
        bus_lat = payload.get("busLat")
        bus_lon = payload.get("busLon")
        is_tracking = bus_lat is not None and bus_lon is not None

        # Distance unit - isDistKm flag indicates km vs miles
        is_km = payload.get("isDistKm", 1) == 1
        distance_unit = "km" if is_km else "mi"

        # Get last position heading from lst10Min if available
        heading = None
        lst10_min = payload.get("lst10Min", [])
        if lst10_min:
            heading = lst10_min[-1].get("heading")

        return BusStatus(
            bus_id=bus_id,
            bus_number=route_no or bus_id.lstrip("S"),
            is_tracking=is_tracking,
            latitude=bus_lat,
            longitude=bus_lon,
            eta_minutes=eta_minutes,
            eta_time=None,  # Not provided in this format
            distance_away=payload.get("dist"),
            distance_unit=distance_unit,
            gps_status=payload.get("stsMsg"),
            heading=heading,
            speed=None,  # Not provided in this format
            last_update=None,  # Not provided in this format
        )

    async def get_student_scans(self) -> list[StudentScan]:
        """Get student RFID/tablet scan events for today."""
        session = await self._get_session()

        if not self._user_guid:
            _LOGGER.warning("No user_guid available for student scans")
            return []

        scans_url = STUDENT_SCANS_URL_TEMPLATE.format(
            subdomain=self._subdomain,
            shard=self._shard,
        )

        params = {
            "action": "web_rider",
            "uid": self._user_guid,
        }

        import json as json_module

        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }

        try:
            async with session.get(scans_url, params=params, headers=headers) as response:
                if response.status != 200:
                    _LOGGER.error("Student scans request failed: %s", response.status)
                    return []

                # Server returns JSON with text/html content-type, so parse as text
                text = await response.text()

                # Check if it's actually HTML (login page)
                if text.strip().startswith("<!DOCTYPE") or text.strip().startswith("<html"):
                    _LOGGER.warning("Student scans returned HTML page - session may have expired")
                    return []

                try:
                    data = json_module.loads(text)
                except json_module.JSONDecodeError as err:
                    _LOGGER.error("Failed to parse student scans JSON: %s", err)
                    return []

                if data.get("status") != "true":
                    _LOGGER.warning("Student scans returned error")
                    return []

                payload = data.get("data", {}).get("payload", {})
                student_details = payload.get("studentDetails", [])

                scans = []
                for student in student_details:
                    student_name = student.get("studentName", "Unknown")
                    for scan in student.get("studentScans", []):
                        scans.append(StudentScan(
                            student_name=student_name,
                            scan_time=scan.get("scanTime", 0),
                            scan_location=scan.get("scanLocation", "Unknown"),
                            scan_method=scan.get("scanMethod", "Unknown"),
                            bus=scan.get("bus", "Unknown"),
                        ))

                return scans

        except aiohttp.ClientError as err:
            _LOGGER.error("Student scans request error: %s", err)
            return []
