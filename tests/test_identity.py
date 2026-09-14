from types import SimpleNamespace
from unittest.mock import MagicMock,patch
from wheresthebus.api import RiderInfo
from wheresthebus.identity import migrate_rider_entities


def test_migrate_active_duplicate_preserves_entity_id_and_device():
    old=SimpleNamespace(unique_id='entry_test_student_status',platform='wheresthebus',disabled_by='device',entity_id='sensor.old',device_id='old')
    active=SimpleNamespace(unique_id='entry_test__student_status',platform='wheresthebus',disabled_by=None,entity_id='sensor.status_2',device_id='active')
    registry,devices=MagicMock(),MagicMock()
    devices.async_get.return_value=SimpleNamespace(identifiers={('wheresthebus','entry_test__student')})
    with patch('wheresthebus.identity.er.async_get',return_value=registry),patch('wheresthebus.identity.dr.async_get',return_value=devices),patch('wheresthebus.identity.er.async_entries_for_config_entry',return_value=[old,active]):
        migrate_rider_entities(None,SimpleNamespace(entry_id='entry'),[RiderInfo('10','101','Test Student','School')])
    registry.async_update_entity.assert_called_once_with('sensor.status_2',new_unique_id='entry_student_101_status')
    assert ('wheresthebus','entry_student_101') in devices.async_update_device.call_args.kwargs['new_identifiers']


def test_already_migrated_entities_do_not_move_again_after_name_change():
    entry=SimpleNamespace(unique_id='entry_student_101_status', platform='wheresthebus')
    registry=MagicMock()
    with patch('wheresthebus.identity.er.async_get',return_value=registry),patch('wheresthebus.identity.dr.async_get'),patch('wheresthebus.identity.er.async_entries_for_config_entry',return_value=[entry]):
        migrate_rider_entities(None,SimpleNamespace(entry_id='entry'),[RiderInfo('10','101','New Name','School')])
    registry.async_update_entity.assert_not_called()
