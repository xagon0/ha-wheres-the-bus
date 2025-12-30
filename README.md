# Where's the Bus - Home Assistant Integration

<img src="https://raw.githubusercontent.com/xagon0/ha-wheres-the-bus/release/icon.png" alt="Where's the Bus" width="128" align="right">

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration for [Where's the Bus](https://wheresthebus.com) school bus tracking. Track your child's school bus location, ETA, and RFID/tablet scan events directly in Home Assistant.

## Features

- **Real-time bus location tracking** on the Home Assistant map
- **ETA sensors** showing minutes until arrival and estimated arrival time
- **Distance sensor** showing how far away the bus is
- **Status sensor** indicating tracking state (tracking, arriving, not_tracking, suspended, offline)
- **Scan sensor** showing the latest RFID or tablet scan event for your child
- **Smart polling** that adjusts automatically based on time of day to minimize API calls

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu and select "Custom repositories"
3. Add `https://github.com/xagon0/ha-wheres-the-bus` with category "Integration"
4. Click "Install"
5. Restart Home Assistant

### Manual Installation

1. Download the latest release
2. Copy the `wheresthebus` folder to your `custom_components` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "Where's the Bus"
3. Enter your Where's the Bus account credentials:
   - **Email**: Your Where's the Bus login email
   - **Password**: Your Where's the Bus password
   - **Subdomain** (optional): Region code (default: `ca` for Canada)
   - **Shard** (optional): Server shard (default: `sh_04`)

## Entities Created

For each rider/student on your account, the following entities are created:

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.<name>_eta_minutes` | Sensor | Minutes until bus arrival |
| `sensor.<name>_arrival_time` | Sensor | Estimated arrival time |
| `sensor.<name>_distance_away` | Sensor | Distance to your stop (km or mi) |
| `sensor.<name>_status` | Sensor | Bus status (tracking, arriving, not_tracking, etc.) |
| `sensor.<name>_last_scan` | Sensor | Last RFID/tablet scan event |
| `device_tracker.<name>_bus_location` | Device Tracker | GPS location of the bus |

## Polling Intervals

The integration uses smart polling to reduce API calls:

- **Active (15 seconds)**: During morning and afternoon pickup windows
- **Idle (5 minutes)**: During school hours between pickup windows
- **Off (1 hour)**: Overnight and on weekends

Default windows are 7:45-8:45 AM and 1:15-2:15 PM on weekdays.

## Automations

Example automation to notify when the bus is approaching:

```yaml
automation:
  - alias: "Bus Arriving Soon"
    trigger:
      - platform: numeric_state
        entity_id: sensor.child_name_eta_minutes
        below: 5
    condition:
      - condition: state
        entity_id: sensor.child_name_status
        state: "tracking"
    action:
      - service: notify.mobile_app
        data:
          title: "Bus Alert"
          message: "The bus will arrive in {{ states('sensor.child_name_eta_minutes') }} minutes!"
```

## Requirements

- An active Where's the Bus account with registered students
- Home Assistant 2023.1 or newer

## Troubleshooting

- **No riders found**: Verify your credentials work on the Where's the Bus website
- **Status shows "offline"**: The bus may not be actively tracking (outside school hours)
- **Region issues**: Try different subdomain/shard values if you're not in Canada

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE.md](LICENSE.md) file for details.

## Disclaimer

This integration is not affiliated with or endorsed by Where's the Bus. It uses web scraping techniques and may break if the Where's the Bus website changes.
