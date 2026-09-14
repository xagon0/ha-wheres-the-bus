"""Configuration and reauthentication for Where's the Bus."""
from datetime import time
import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WheresTheBusApi, WheresTheBusAuthError, WheresTheBusApiError
from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD, DEFAULT_AM_WINDOW, DEFAULT_PM_WINDOW

_LOGGER = logging.getLogger(__name__)


class WheresTheBusConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        return await self._login_form("user", user_input)

    async def async_step_reauth(self, entry_data) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> ConfigFlowResult:
        return await self._login_form("reauth_confirm", user_input)

    async def _login_form(self, step, user_input):
        errors = {}
        reauth = step == "reauth_confirm"
        entry = self._get_reauth_entry() if reauth else None
        if user_input is not None:
            email = entry.data[CONF_EMAIL] if reauth else user_input[CONF_EMAIL].strip()
            if not reauth:
                await self.async_set_unique_id(email.lower())
                self._abort_if_unique_id_configured()
            api = WheresTheBusApi(email=email, password=user_input[CONF_PASSWORD],
                                 session=async_get_clientsession(self.hass))
            try:
                await api.authenticate()
            except WheresTheBusAuthError:
                errors["base"] = "invalid_auth"
            except WheresTheBusApiError:
                errors["base"] = "cannot_connect"
            else:
                if reauth:
                    return self.async_update_reload_and_abort(entry, data_updates=user_input)
                return self.async_create_entry(title=f"Where's the Bus ({email})",
                                               data={CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD]})
        schema = {vol.Required(CONF_PASSWORD): str}
        if not reauth:
            schema = {vol.Required(CONF_EMAIL): str, **schema}
        return self.async_show_form(step_id=step, data_schema=vol.Schema(schema), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return WheresTheBusOptionsFlow()


class WheresTheBusOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                for label in ("am", "pm"):
                    if time.fromisoformat(user_input[f"{label}_start"]) >= time.fromisoformat(user_input[f"{label}_end"]):
                        raise ValueError
            except ValueError:
                errors["base"] = "invalid_window"
            else:
                return self.async_create_entry(title="", data=user_input)
        schema = {}
        for label, window in (("am", DEFAULT_AM_WINDOW), ("pm", DEFAULT_PM_WINDOW)):
            for name, hour, minute in (("start", window[0], window[1]), ("end", window[2], window[3])):
                key = f"{label}_{name}"
                schema[vol.Required(key, default=self.config_entry.options.get(key, f"{hour:02}:{minute:02}"))] = str
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema), errors=errors)
