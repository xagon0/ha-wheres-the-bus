"""Config flow for Where's the Bus integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WheresTheBusApi, WheresTheBusAuthError, WheresTheBusApiError
from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SUBDOMAIN,
    CONF_SHARD,
    DEFAULT_SUBDOMAIN,
    DEFAULT_SHARD,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_SUBDOMAIN, default=DEFAULT_SUBDOMAIN): str,
        vol.Optional(CONF_SHARD, default=DEFAULT_SHARD): str,
    }
)


class WheresTheBusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Where's the Bus."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Check if already configured
            await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
            self._abort_if_unique_id_configured()

            # Test credentials
            session = async_get_clientsession(self.hass)
            api = WheresTheBusApi(
                email=user_input[CONF_EMAIL],
                password=user_input[CONF_PASSWORD],
                subdomain=user_input.get(CONF_SUBDOMAIN, DEFAULT_SUBDOMAIN),
                shard=user_input.get(CONF_SHARD, DEFAULT_SHARD),
                session=session,
            )

            try:
                await api.authenticate()

                return self.async_create_entry(
                    title=f"Where's the Bus ({user_input[CONF_EMAIL]})",
                    data=user_input,
                )

            except WheresTheBusAuthError:
                errors["base"] = "invalid_auth"
            except WheresTheBusApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
