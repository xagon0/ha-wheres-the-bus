# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Home Assistant custom integration for the "Where's the Bus" school bus tracking service. It provides real-time bus location tracking, ETA sensors, and RFID/tablet scan events for students.

**Domain:** `wheresthebus`
**Platforms:** sensor, device_tracker

## Architecture

### Core Components

- **`__init__.py`**: Entry point with `WheresTheBusCoordinator` - a `DataUpdateCoordinator` that manages polling intervals dynamically based on time of day (active during pickup/dropoff windows, idle during school hours, off overnight/weekends)

- **`api.py`**: `WheresTheBusApi` client that handles authentication via web scraping (no official API), session management, and data fetching. Key data classes: `RiderInfo`, `BusStatus`, `StudentScan`

- **`sensor.py`**: Five sensor types per rider - ETA minutes, arrival time, distance, status, and last scan

- **`device_tracker.py`**: GPS tracker entity for bus location on the map

- **`config_flow.py`**: UI-based configuration flow for credentials and region settings

### Authentication Flow

The API uses web scraping since there's no official API:
1. GET login page to extract CSRF token
2. POST credentials to `au_login.php`
3. Follow redirects to establish session
4. Parse rider page HTML for `s_app_id`, `user_guid`, bus/child IDs, and rider JSON data
5. Use extracted session data for subsequent API calls

### Polling Strategy

Defined in `const.py`, the coordinator adjusts intervals based on schedule:
- **Active (15s)**: During AM/PM pickup windows
- **Idle (5min)**: During school hours between windows
- **Off (1hr)**: Weekends and outside school hours

## Development Notes

### Dependencies

From `manifest.json`: `aiohttp>=3.8.0`, `beautifulsoup4>=4.12.0`

### Region Configuration

- `subdomain`: Region code (default: `ca` for Canada)
- `shard`: Server shard (default: `sh_04`)

These are configurable in the config flow for different Where's the Bus regional deployments.

### Key Patterns

- All entities inherit from `CoordinatorEntity` for coordinated updates
- Rider-specific data accessed via `coordinator.get_bus_status(child_id)`
- Sensors share device grouping using `device_info` with rider-based identifiers
