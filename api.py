"""Client for the Where's the Bus parent app JSON API."""
from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit, urljoin
from uuid import uuid4
from time import monotonic

import aiohttp

from .const import DEFAULT_SHARD, DEFAULT_SUBDOMAIN

_LOGGER = logging.getLogger(__name__)
LOGIN_API_URL = "https://mdt.wheresthebus.com/wtbparentapp/api/v2/login"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


def normalized_name(name: str) -> str:
    """Match display names without treating whitespace as identity."""
    return " ".join(name.casefold().replace("'", "").split())


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


@dataclass
class RiderInfo:
    child_id: str
    student_id: str
    name: str
    school: str
    am_bus_no: str | None = None
    am_stop_time: str | None = None
    am_stop_address: str | None = None
    am_stop_lat: float | None = None
    am_stop_lon: float | None = None
    pm_bus_no: str | None = None
    pm_stop_time: str | None = None
    pm_stop_address: str | None = None
    pm_stop_lat: float | None = None
    pm_stop_lon: float | None = None


@dataclass
class StudentScan:
    student_name: str
    scan_time: int
    scan_location: str
    scan_method: str
    bus: str
    student_id: str | None = None


@dataclass
class BusStatus:
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
    eta_message: str | None = None
    position_age_minutes: float | None = None
    last_poll: str | None = None


class WheresTheBusApiError(Exception):
    """Transport failure or an unexpected provider response."""


class WheresTheBusAuthError(WheresTheBusApiError):
    """The saved credentials are no longer accepted."""


class WheresTheBusApi:
    def __init__(
        self, email: str, password: str,
        subdomain: str = DEFAULT_SUBDOMAIN, shard: str = DEFAULT_SHARD,
        session: aiohttp.ClientSession | None = None,
        device_id: str | None = None,
    ) -> None:
        self._email = email
        self._password = password
        self._session = session
        self._owns_session = session is None
        self._device_id = device_id or f"HomeAssistant_{uuid4()}"
        # Region and shard are discovered during login; retain constructor
        # compatibility with existing config entries.
        self._base_url: str | None = None
        self._session_id: str | None = None
        self._auth_lock = asyncio.Lock()
        self._riders: list[RiderInfo] = []
        self._assignments: dict[str, tuple[str, str]] = {}
        self._assignments_session: str | None = None
        self._assignments_updated = 0.0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session:
            await self._session.close()
            self._session = None

    @staticmethod
    def _trusted_url(url: str) -> bool:
        try:
            parsed = urlsplit(url)
            host = parsed.hostname or ""
            return (parsed.scheme == "https" and not parsed.username and not parsed.password
                    and parsed.port in (None, 443)
                    and any(host == domain or host.endswith("." + domain)
                            for domain in ("wheresthebus.com", "veonow.com")))
        except ValueError:
            return False

    async def _post(self, url: str, data: dict[str, Any]) -> dict[str, Any]:
        session = await self._get_session()
        try:
            for _ in range(4):
                if not self._trusted_url(url):
                    raise WheresTheBusApiError("Provider returned an untrusted API redirect")
                async with session.post(
                    url, json=data, timeout=REQUEST_TIMEOUT, allow_redirects=False,
                ) as response:
                    if response.status in (307, 308):
                        destination = urljoin(url, response.headers.get("Location", ""))
                        if urlsplit(destination).path.rsplit("/", 1)[-1] != urlsplit(url).path.rsplit("/", 1)[-1]:
                            raise WheresTheBusApiError("Provider redirected to a different API endpoint")
                        url = destination
                        continue
                    if response.status != 200:
                        raise WheresTheBusApiError(f"Provider returned HTTP {response.status}")
                    result = await response.json(content_type=None)
                    break
            else:
                raise WheresTheBusApiError("Too many provider redirects")
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            # Never log response bodies, passwords, session IDs or login URLs.
            raise WheresTheBusApiError("Unable to read the provider API response") from err
        if not isinstance(result, dict) or "resCode" not in result:
            raise WheresTheBusApiError("Provider returned an invalid API response")
        return result

    @staticmethod
    def _api_base(payload: dict[str, Any]) -> str:
        """Use the server's region, limited to HTTPS provider hosts."""
        parsed = urlsplit(str(payload.get("basePath", "")))
        host = parsed.hostname or ""
        if not WheresTheBusApi._trusted_url(str(payload.get("basePath", ""))):
            raise WheresTheBusApiError("Provider returned an invalid regional API host")
        shard = str(payload.get("shardId", ""))
        if not re.fullmatch(r"sh_\d+", shard):
            raise WheresTheBusApiError("Provider returned an invalid shard")
        return f"https://{host}/{shard}/wtbparentapp/api/v2/"

    async def _login(self) -> None:
        result = await self._post(LOGIN_API_URL, {
            "emailId": self._email, "password": self._password,
            "imeiNo": self._device_id, "deviceType": "FlutterWeb",
            "sso": 0, "deviceOS": "Web_HomeAssistant",
        })
        code = str(result["resCode"])
        if code in ("1", "2", "9"):
            self._session_id = None
            raise WheresTheBusAuthError("Where's the Bus rejected the saved login")
        if code != "0":
            raise WheresTheBusApiError(f"Login failed (provider code {code})")
        payload = result.get("payload")
        if not isinstance(payload, dict) or not payload.get("sessionId"):
            raise WheresTheBusApiError("Login returned no session")
        base_url = self._api_base(payload)
        self._base_url = base_url
        self._session_id = str(payload["sessionId"])

    async def _request(self, endpoint: str, data: dict[str, Any] | Callable[[], dict[str, Any]] | None = None) -> dict[str, Any]:
        if not self._session_id:
            async with self._auth_lock:
                if not self._session_id:
                    await self._login()
        for attempt in range(2):
            session_id = self._session_id
            result = await self._post(self._base_url + endpoint, {
                **(data() if callable(data) else data or {}), "sessionId": session_id,
            })
            code = str(result["resCode"])
            if code == "0":
                payload = result.get("payload")
                if not isinstance(payload, dict):
                    raise WheresTheBusApiError(f"{endpoint} returned no data")
                return result
            if code != "9":
                raise WheresTheBusApiError(f"{endpoint} failed (provider code {code})")
            if attempt:
                raise WheresTheBusApiError("Provider rejected the refreshed session")
            async with self._auth_lock:
                if self._session_id == session_id:
                    await self._login()
            if endpoint == "getRiderInfoEx":
                await self.refresh_assignments()
        raise WheresTheBusApiError("Unable to refresh session")

    async def authenticate(self) -> bool:
        async with self._auth_lock:
            await self._login()
        await self.refresh_riders()
        await self.refresh_assignments()
        if not self._riders:
            raise WheresTheBusApiError("No riders are registered on this account")
        _LOGGER.info("Authenticated with Where's the Bus; found %d rider(s)", len(self._riders))
        return True

    @property
    def riders(self) -> list[RiderInfo]:
        return self._riders

    async def refresh_riders(self) -> None:
        result = await self._request("getAllRiders")
        rows = result["payload"].get("allRiders")
        if not isinstance(rows, list):
            raise WheresTheBusApiError("Provider returned an invalid rider list")
        riders = []
        for row in rows:
            student_id = str(row.get("studentId") or "")
            if not student_id:
                raise WheresTheBusApiError("Provider returned a rider without an ID")
            riders.append(RiderInfo(
                child_id=student_id, student_id=student_id,
                name=row.get("riderName") or "Unknown Rider",
                school=row.get("schoolName") or "Unknown School",
                **{f"{period}_{field}": row.get(f"{period}{key}")
                   for period in ("am", "pm")
                   for field, key in (("bus_no", "BusNo"), ("stop_time", "StopTime"),
                                      ("stop_address", "StopAddress"))},
                **{f"{period}_stop_{coord}": _number(row.get(f"{period}Stop{coord.title()}"))
                   for period in ("am", "pm") for coord in ("lat", "lon")},
            ))
        self._riders = riders

    async def refresh_assignments(self) -> None:
        result = await self._request("getUserInfo", {
            "imeiNo": self._device_id, "versionInstalled": "5.2.0",
            "deviceType": "FlutterWeb", "deviceOS": "Web_HomeAssistant",
        })
        buses = result["payload"].get("childBuses")
        if not isinstance(buses, list):
            raise WheresTheBusApiError("Provider returned no bus assignments")
        assignments = {}
        for rider in self._riders:
            routes = {str(r) for r in (rider.am_bus_no, rider.pm_bus_no) if r}
            matches = [b for b in buses if str(b.get("routeNo")) in routes]
            if len(matches) > 1:
                # The parent API exposes the stop time, not the student's name.
                times = {re.sub(r"[^0-9:]", "", t) for t in (rider.am_stop_time, rider.pm_stop_time) if t}
                matches = [b for b in matches if re.sub(r"[^0-9:]", "", str(b.get("busTime", ""))) in times]
            if not matches and len(self._riders) == 1 and len(buses) == 1:
                matches = buses
            choices = {(str(b["childId"]), str(b["busNo"])) for b in matches
                       if b.get("childId") is not None and b.get("busNo")}
            if len(choices) != 1:
                raise WheresTheBusApiError("Unable to uniquely match a rider to a bus assignment")
            assignment = choices.pop()
            if not assignment[0].isdigit():
                raise WheresTheBusApiError("Provider returned an invalid tracking ID")
            assignments[rider.student_id] = assignment
        self._assignments = assignments
        self._assignments_session = self._session_id
        self._assignments_updated = monotonic()

    async def get_bus_status(self, student_id: str) -> BusStatus:
        if (self._assignments_session != self._session_id
                or monotonic() - self._assignments_updated >= 300
                or student_id not in self._assignments):
            await self.refresh_assignments()

        def request_data():
            child_id, bus_id = self._assignments[student_id]
            return {"bid": bus_id, "chdId": int(child_id), "lastServerTime": 0}

        result = await self._request("getRiderInfoEx", request_data)
        return self._parse_bus_status(result["payload"], self._assignments[student_id][1], result.get("serverTime"))

    def _parse_bus_status(self, payload: dict[str, Any], bus_id: str, server_time: Any = None) -> BusStatus:
        bus_lat, bus_lon = _number(payload.get("busLat")), _number(payload.get("busLon"))
        tracking = (bus_lat is not None and bus_lon is not None
                    and -90 <= bus_lat <= 90 and -180 <= bus_lon <= 180
                    and (bus_lat, bus_lon) != (0, 0))
        gps_status = str(payload.get("stsMsg") or "")
        age_match = re.search(r"(\d+(?:\.\d+)?)\s*(min|hour|hr|day)", gps_status, re.I)
        age = None
        if age_match:
            age = float(age_match[1]) * {"min": 1, "hour": 60, "hr": 60, "day": 1440}[age_match[2].lower()]
        has_position = tracking
        tracking = tracking and (age is None or age < 5) and not any(
            term in gps_status.lower() for term in ("unavailable", "resumes", "offline"))
        eta_raw = payload.get("etaMsg")
        eta = str(eta_raw).strip() if eta_raw is not None else ""
        eta_minutes = int(eta) if eta.isdigit() else None
        buses = payload.get("childBuses") or []
        bus = next((b for b in buses if str(b.get("busNo")) == bus_id), {})
        if not bus and len(buses) == 1:
            bus = buses[0]
        history = payload.get("lst10Min") or []
        timestamp = _number(server_time)
        updated = None
        arrival = None
        if timestamp:
            try:
                updated = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
                if tracking and eta_minutes is not None:
                    arrival = datetime.fromtimestamp(timestamp + eta_minutes * 60, timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                pass
        return BusStatus(
            bus_id=str(bus.get("busNo") or bus_id),
            bus_number=str(bus.get("routeNo") or bus.get("busNo") or bus_id),
            is_tracking=tracking, latitude=bus_lat if has_position else None,
            longitude=bus_lon if has_position else None, eta_minutes=eta_minutes if tracking else None,
            eta_time=arrival, distance_away=_number(payload.get("dist")),
            distance_unit="km" if str(payload.get("isDistKm", 1)) == "1" else "mi",
            gps_status=gps_status,
            heading=history[-1].get("heading") if history else None,
            speed=None, last_update=None, last_poll=updated,
            eta_message=eta or None, position_age_minutes=age,
        )

    async def get_student_scans(self) -> list[StudentScan]:
        result = await self._request("getStudentScan")
        payload = result["payload"]
        student_ids = {normalized_name(s.get("full_name", "")): str(s["stud_id"])
                       for s in payload.get("studentInfo", []) if s.get("stud_id") is not None}
        scans = []
        for student in payload.get("studentDetails", []):
            name = student.get("studentName") or "Unknown"
            for scan in student.get("studentScans", []):
                timestamp = _number(scan.get("scanTime"))
                if timestamp is None or timestamp <= 0:
                    continue
                scans.append(StudentScan(
                    student_name=name, student_id=student_ids.get(normalized_name(name)),
                    scan_time=int(timestamp), scan_location=scan.get("scanLocation") or "Unknown",
                    scan_method=scan.get("scanMethod") or "Unknown", bus=str(scan.get("bus") or "Unknown"),
                ))
        return scans
