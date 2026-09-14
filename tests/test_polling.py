from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from wheresthebus.polling import polling_interval

@pytest.mark.parametrize('value,expected', [
    ('2026-09-14T16:10:00',15),
    ('2026-09-14T06:59:50',10),
    ('2026-09-14T12:59:50',10),
    ('2026-09-14T09:30:00',300),
    ('2026-09-14T22:00:00',3600),
    ('2026-09-13T16:10:00',3600),
])
def test_polling_local_hours_and_boundaries(value,expected):
    now=datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('America/Edmonton'))
    assert polling_interval(now)==expected

def test_user_window():
    now=datetime(2026,9,14,17,30,tzinfo=ZoneInfo('America/Edmonton'))
    assert polling_interval(now,{'pm_start':'15:00','pm_end':'18:00'})==15
