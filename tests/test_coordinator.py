from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed
from wheresthebus import WheresTheBusCoordinator, async_setup_entry
from wheresthebus.api import RiderInfo, StudentScan, WheresTheBusApiError, WheresTheBusAuthError
from wheresthebus.sensor import LastScanSensor

@pytest.mark.asyncio
async def test_bus_fetch_failure_does_not_return_old_data(tmp_path):
    hass=HomeAssistant(str(tmp_path))
    api=SimpleNamespace(riders=[RiderInfo('10','101','Test Student','School')],
                        get_bus_status=AsyncMock(side_effect=WheresTheBusApiError('Connection failed')))
    entry=MagicMock(options={})
    coordinator=WheresTheBusCoordinator(hass,api,entry)
    coordinator._bus_status={'101': 'old'}
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

@pytest.mark.asyncio
async def test_scan_failure_marks_scan_unavailable_without_losing_bus(tmp_path):
    hass=HomeAssistant(str(tmp_path))
    api=SimpleNamespace(riders=[RiderInfo('10','101','Test Student','School')],
                        get_bus_status=AsyncMock(return_value='current'),
                        get_student_scans=AsyncMock(side_effect=WheresTheBusApiError('Connection failed')))
    coordinator=WheresTheBusCoordinator(hass,api,MagicMock(options={}))
    coordinator._student_scans=[StudentScan('Test Student',1,'School','RFID','1')]
    assert await coordinator._async_update_data()=={'101':'current'}
    assert not coordinator.scans_available
    assert coordinator.get_latest_scan('Test Student') is None

@pytest.mark.asyncio
async def test_setup_failure_retries_or_requests_reauth():
    for error,expected in [(WheresTheBusApiError('temporary'),ConfigEntryNotReady),
                           (WheresTheBusAuthError('credentials'),ConfigEntryAuthFailed)]:
        api=MagicMock(authenticate=AsyncMock(side_effect=error))
        entry=MagicMock(data={'email':'test','password':'secret'})
        with patch('wheresthebus.async_get_clientsession'),patch('wheresthebus.WheresTheBusApi',return_value=api):
            with pytest.raises(expected):
                await async_setup_entry(MagicMock(),entry)


@pytest.mark.asyncio
async def test_only_retired_devices_can_be_removed():
    from wheresthebus import async_remove_config_entry_device
    rider=RiderInfo('10','101','Test Student','School')
    entry=SimpleNamespace(entry_id='entry')
    hass=SimpleNamespace(data={'wheresthebus':{'entry':{'coordinator':SimpleNamespace(riders=[rider])}}})
    retired=SimpleNamespace(identifiers={('wheresthebus','entry_test_student')})
    active=SimpleNamespace(identifiers={('wheresthebus','entry_student_101'),('wheresthebus','entry_test__student')})
    assert await async_remove_config_entry_device(hass,entry,retired)
    assert not await async_remove_config_entry_device(hass,entry,active)
    hass.data={}
    assert not await async_remove_config_entry_device(hass,entry,retired)
