from unittest.mock import AsyncMock
import pytest
from wheresthebus.api import WheresTheBusApi, WheresTheBusApiError, WheresTheBusAuthError, LOGIN_API_URL

LOGIN = {'resCode': 0, 'payload': {'sessionId': 'test-session', 'basePath': 'https://ca.mdt.veonow.com/sh_04/', 'shardId': 'sh_04'}}
ASSIGNMENTS = {'resCode': 0, 'payload': {'childBuses': [{'childId': 9001, 'busNo': 'S77', 'routeNo': '12', 'busTime': '4:12'}]}}
RIDERS = {'resCode': 0, 'payload': {'allRiders': [{'studentId': 101, 'riderName': 'Test  Student', 'schoolName': 'School', 'pmStopLat': '51.1'}]}}

@pytest.mark.asyncio
async def test_login_discovers_region_and_riders_without_html():
    api = WheresTheBusApi('test@example.invalid', 'secret')
    api._post = AsyncMock(side_effect=[LOGIN, RIDERS, ASSIGNMENTS])
    assert await api.authenticate()
    assert api._post.call_args_list[0].args[0] == LOGIN_API_URL
    assert api._post.call_args_list[1].args[0] == 'https://ca.mdt.veonow.com/sh_04/wtbparentapp/api/v2/getAllRiders'
    assert api.riders[0].student_id == '101'
    assert api.riders[0].pm_stop_lat == 51.1

@pytest.mark.asyncio
async def test_invalid_login_is_an_auth_error():
    api = WheresTheBusApi('test', 'secret')
    api._post = AsyncMock(return_value={'resCode': 1, 'mesgStr': 'Invalid credentials'})
    with pytest.raises(WheresTheBusAuthError):
        await api.authenticate()

@pytest.mark.parametrize('payload', [
    {'basePath': 'https://evil.invalid/sh_04/', 'shardId': 'sh_04'},
    {'basePath': 'http://mdt.wheresthebus.com/', 'shardId': 'sh_04'},
    {'basePath': 'https://wheresthebus.com.evil.invalid/', 'shardId': 'sh_04'},
    {'basePath': 'https://mdt.wheresthebus.com/', 'shardId': '../other'},
])
def test_refuse_session_to_untrusted_hosts(payload):
    with pytest.raises(WheresTheBusApiError):
        WheresTheBusApi._api_base(payload)

@pytest.mark.asyncio
async def test_expired_session_reauthenticates_once_and_retries_new_region():
    api = WheresTheBusApi('test', 'secret')
    api._session_id = 'old'
    api._base_url = 'https://mdt.wheresthebus.com/sh_01/wtbparentapp/api/v2/'
    api._post = AsyncMock(side_effect=[{'resCode': 9}, LOGIN, {'resCode': 0, 'payload': {'studentDetails': []}}])
    assert await api.get_student_scans() == []
    calls = api._post.call_args_list
    assert calls[2].args[0].startswith('https://ca.mdt.veonow.com/sh_04/')
    assert calls[2].args[1]['sessionId'] == 'test-session'

@pytest.mark.asyncio
async def test_failed_renewal_is_not_reported_as_bus_offline():
    api = WheresTheBusApi('test', 'secret')
    api._session_id = 'old'
    api._base_url = 'https://mdt.wheresthebus.com/sh_01/wtbparentapp/api/v2/'
    api._post = AsyncMock(side_effect=[{'resCode': 9}, LOGIN, {'resCode': 9}])
    with pytest.raises(WheresTheBusApiError, match='refreshed session'):
        await api.get_student_scans()
    assert api._post.call_count == 3

@pytest.mark.asyncio
async def test_scans_use_new_endpoint_and_normalize_student_names():
    api = WheresTheBusApi('test', 'secret')
    api._request = AsyncMock(return_value={'payload': {
        'studentInfo': [{'stud_id': 101, 'full_name': 'Test Student'}],
        'studentDetails': [{'studentName': 'Test  Student', 'studentScans': [
            {'scanTime': '1789420200', 'scanLocation': 'School', 'scanMethod': 'Tablet', 'bus': '12'}]}],
    }})
    scans = await api.get_student_scans()
    assert scans[0].student_id == '101'
    assert scans[0].scan_time == 1789420200
    api._request.assert_awaited_once_with('getStudentScan')

@pytest.mark.parametrize('lat,lon,tracking', [('51.1','-114.2',True),('',None,False),(0,0,False),('NaN',1,False),(91,1,False)])
def test_numeric_coordinates_are_validated(lat,lon,tracking):
    api = WheresTheBusApi('test','secret')
    status = api._parse_bus_status({'busLat':lat,'busLon':lon,'etaMsg':4,'dist':'2.3'},'S1')
    assert status.is_tracking is tracking
    assert status.eta_minutes == (4 if tracking else None)
    assert status.distance_away == 2.3


@pytest.mark.asyncio
async def test_bus_requests_use_tracking_id_not_student_id():
    api = WheresTheBusApi('test', 'secret')
    api._post = AsyncMock(side_effect=[LOGIN, RIDERS, ASSIGNMENTS, {'resCode': 0, 'payload': {'busLat': 51, 'busLon': -114}}])
    await api.authenticate()
    await api.get_bus_status('101')
    data = api._post.call_args.args[1]
    assert data['chdId'] == 9001
    assert data['bid'] == 'S77'

@pytest.mark.asyncio
async def test_tracking_ids_are_refreshed_after_expired_session():
    api = WheresTheBusApi('test','secret')
    new = {'resCode':0,'payload':{'childBuses':[{'childId':9002,'busNo':'S88','routeNo':'12'}]}}
    api._post = AsyncMock(side_effect=[LOGIN,RIDERS,ASSIGNMENTS,{'resCode':9},LOGIN,new,{'resCode':0,'payload':{'busLat':51,'busLon':-114}}])
    await api.authenticate()
    await api.get_bus_status('101')
    assert api._post.call_args.args[1]['chdId'] == 9002
    assert api._post.call_args.args[1]['bid'] == 'S88'

def test_old_position_is_explicitly_stale_but_retains_last_location():
    status=WheresTheBusApi('test','secret')._parse_bus_status({'busLat':51,'busLon':-114,'stsMsg':'13 min. ago','etaMsg':'past stop'},'S77',1789425500)
    assert not status.is_tracking
    assert status.position_age_minutes==13
    assert status.latitude==51
    assert status.eta_message=='past stop'
    assert status.last_update is None
    assert status.last_poll is not None

@pytest.mark.asyncio
async def test_regional_login_redirect_preserves_post_payload():
    from unittest.mock import MagicMock
    redirect=MagicMock(status=307,headers={'Location':'https://ca.mdt.wheresthebus.com/sh_04/wtbparentapp/api/v2/login'})
    response=MagicMock(status=200,json=AsyncMock(return_value=LOGIN))
    contexts=[]
    for item in (redirect,response):
        cm=MagicMock()
        cm.__aenter__=AsyncMock(return_value=item)
        cm.__aexit__=AsyncMock(return_value=False)
        contexts.append(cm)
    session=MagicMock(post=MagicMock(side_effect=contexts))
    api=WheresTheBusApi('test','secret',session=session)
    await api._login()
    assert session.post.call_count==2
    assert session.post.call_args.kwargs['json']['password']=='secret'

@pytest.mark.asyncio
async def test_login_redirect_never_sends_credentials_to_untrusted_host():
    from unittest.mock import MagicMock
    redirect=MagicMock(status=307,headers={'Location':'https://evil.invalid/login'})
    cm=MagicMock(__aenter__=AsyncMock(return_value=redirect),__aexit__=AsyncMock(return_value=False))
    session=MagicMock(post=MagicMock(return_value=cm))
    api=WheresTheBusApi('test','secret',session=session)
    with pytest.raises(WheresTheBusApiError,match='untrusted'):
        await api._login()
    assert session.post.call_count==1
