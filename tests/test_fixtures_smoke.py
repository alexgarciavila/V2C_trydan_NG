"""Prueba de humo de la fundacion de tests (tests/conftest.py).

No valida logica de negocio de v2c_trydan: solo confirma que el plugin
``pytest-homeassistant-custom-component`` esta correctamente instalado y que
las fixtures compartidas (``hass``, ``mock_config_entry``, ``mock_coordinator``,
``realtime_data``, ``mock_v2c_http``) funcionan en este repo, para que los
siguientes test-agent puedan apoyarse en ellas sin re-verificar la fundacion.
"""
from homeassistant.core import HomeAssistant

from tests.conftest import FAKE_IP_ADDRESS


async def test_hass_fixture_is_usable(hass: HomeAssistant):
    """La fixture ``hass`` (provista por el plugin) arranca correctamente."""
    assert hass.is_running


def test_mock_config_entry_has_expected_data(mock_config_entry):
    """``mock_config_entry`` refleja el contrato de config_flow.py/const.py."""
    assert mock_config_entry.data["ip_address"] == FAKE_IP_ADDRESS
    assert mock_config_entry.options["kwh_per_100km"] == 20.8
    assert mock_config_entry.options["precio_luz"] == "sensor.pvpc"


def test_mock_coordinator_exposes_realtime_data(mock_coordinator, realtime_data):
    """``mock_coordinator.data`` contiene una copia independiente de los datos."""
    assert mock_coordinator.data == realtime_data
    assert mock_coordinator.data is not realtime_data
    assert mock_coordinator.ip_address == FAKE_IP_ADDRESS


async def test_mock_v2c_http_intercepts_realtime_data_request(
    hass: HomeAssistant, mock_v2c_http, realtime_data
):
    """``mock_v2c_http`` mockea una llamada real via aiohttp sin red."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/RealTimeData", payload=realtime_data
    )

    session = async_get_clientsession(hass)
    async with session.get(f"http://{FAKE_IP_ADDRESS}/RealTimeData") as response:
        body = await response.json(content_type=None)

    assert body == realtime_data
