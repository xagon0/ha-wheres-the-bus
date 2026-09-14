"""Constants for the Where's the Bus integration."""

DOMAIN = "wheresthebus"

# Default values (for Canada)
DEFAULT_SUBDOMAIN = "ca"
DEFAULT_SHARD = "sh_04"

# Config keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_SUBDOMAIN = "subdomain"
CONF_SHARD = "shard"

# Scan intervals (seconds)
SCAN_INTERVAL_ACTIVE = 15      # When bus is likely running (during pickup/dropoff windows)
SCAN_INTERVAL_IDLE = 300       # Outside windows but during school days (5 min)
SCAN_INTERVAL_OFF = 3600       # Overnight/weekends - just check occasionally (1 hour)

# Default time windows (24h format), configurable in integration options
# Format: (start_hour, start_min, end_hour, end_min)
DEFAULT_AM_WINDOW = (7, 0, 9, 0)     # 7:00 AM - 9:00 AM
DEFAULT_PM_WINDOW = (13, 0, 17, 0)   # 1:00 PM - 5:00 PM

# Days to poll (0=Monday, 6=Sunday)
SCHOOL_DAYS = [0, 1, 2, 3, 4]  # Monday-Friday

# Bus status codes
BUS_STATUS_TRACKING = "tracking"
BUS_STATUS_NOT_TRACKING = "not_tracking"
BUS_STATUS_ARRIVED = "arrived"
BUS_STATUS_UNKNOWN = "unknown"
