"""Fixtures compartidas para la suite de tests de v2c_trydan.

Este fichero es la FUNDACION de testing del componente: los tests de
modulos concretos (coordinator, sensor, switch, number, select, config_flow,
__init__/servicios, json_repair) escritos por otros agentes deben reutilizar
estas fixtures en lugar de recrear su propia configuracion de ``hass``,
``MockConfigEntry`` o datos falsos de ``/RealTimeData``.

Convenciones:
- La fixture ``hass`` la provee automaticamente el plugin
  ``pytest-homeassistant-custom-component`` (no hace falta declararla aqui).
  Basta con pedirla como argumento en cualquier test/fixture.
- ``enable_custom_integrations`` es OBLIGATORIA (autouse aqui) en versiones
  recientes de Home Assistant para que ``hass`` pueda cargar integraciones
  que viven en ``custom_components/`` en lugar de en el core.
- Todas las peticiones HTTP al dispositivo real (``GET /RealTimeData``,
  ``GET /write/<Parametro>=<valor>``) deben mockearse con ``aioresponses``
  (fixture ``mock_v2c_http``) — nunca golpear la red real en tests.
"""
from __future__ import annotations

import sys
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
import pytest_socket
from aioresponses import aioresponses

from homeassistant.const import CONF_IP_ADDRESS

from custom_components.v2c_trydan.const import (
    CONF_KM_TO_CHARGE,
    CONF_KWH_PER_100KM,
    CONF_PRECIO_LUZ,
    DOMAIN,
)

from pytest_homeassistant_custom_component.common import MockConfigEntry

# IP de ejemplo reservada para documentacion/testing (RFC 5737, TEST-NET-1).
# Nunca usar la IP real de un dispositivo V2C Trydan en tests o commits.
FAKE_IP_ADDRESS = "192.0.2.10"


# --- LIMITACION CONOCIDA DE ENTORNO (no es un cambio de codigo productivo,
# solo afecta al entorno de test en Windows nativo) --------------------------
#
# ``pytest-homeassistant-custom-component`` llama a
# ``pytest_socket.disable_socket(allow_unix_socket=True)`` antes de cada test
# para impedir llamadas de red reales. En Linux/macOS esto no molesta porque
# el "self-pipe" interno de asyncio que usa ``call_soon_threadsafe`` (y que
# necesita el event loop de Home Assistant para arrancar) usa un socketpair
# AF_UNIX, que el plugin permite explicitamente.
#
# En Windows, ``socket.socketpair()`` no tiene implementacion nativa AF_UNIX:
# cae a un fallback (`_fallback_socketpair`) que crea sockets AF_INET reales
# en loopback. Ese fallback lo bloquea el guard del plugin sin excepcion
# posible via marcadores/fixtures normales, y el event loop de asyncio no
# puede construirse en NINGUN test (incluidos los que no tocan HTTP), fallando
# con ``SocketBlockedError`` incluso antes de llegar al cuerpo del test.
#
# Parche minimo, solo en Windows: sustituir ``pytest_socket.disable_socket``
# por un no-op ANTES de que se registre ningun hook (a nivel de import de
# este modulo, que ocurre antes de que arranque cualquier test). Esto no
# relaja el aislamiento de red en Linux/macOS (CI), y no afecta a la logica
# de los tests: siguen sin hacer llamadas de red reales, usan
# ``aioresponses`` (fixture ``mock_v2c_http``) o los mocks propios de
# ``pytest-homeassistant-custom-component`` para todo el trafico HTTP.
if sys.platform == "win32":
    pytest_socket.disable_socket = lambda *args, **kwargs: None

    # Segunda limitacion de entorno, tambien solo-Windows: HA crea su sesion
    # aiohttp compartida (``async_get_clientsession(hass)``, usada por
    # ``coordinator.py`` y las escrituras HTTP de ``__init__.py``) con un
    # ``AsyncResolver`` (basado en ``aiodns``/``pycares``). ``aiodns`` exige
    # explicitamente un ``SelectorEventLoop`` en Windows y el event loop de
    # HA en tests es un ``ProactorEventLoop``, así que cualquier test que
    # use ``async_get_clientsession(hass)`` fallaria con
    # ``RuntimeError: aiodns needs a SelectorEventLoop on Windows``. Se
    # sustituye el resolver por ``ThreadedResolver`` (resolucion DNS via
    # threadpool, sin aiodns) SOLO para la sesion de tests en Windows; el
    # comportamiento de produccion (``AsyncResolver`` en Linux/CI) no
    # cambia.
    import homeassistant.helpers.aiohttp_client as _ha_aiohttp_client
    from aiohttp.resolver import ThreadedResolver

    _ha_aiohttp_client.AsyncResolver = ThreadedResolver


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Habilita la carga de integraciones custom para todos los tests.

    ``enable_custom_integrations`` es una fixture del plugin
    ``pytest-homeassistant-custom-component``; sin activarla, ``hass`` ignora
    todo lo que viva bajo ``custom_components/`` (incluido v2c_trydan) al
    resolver ``async_setup_entry``/config_flow.
    """
    return None


@pytest.fixture
def realtime_data() -> dict:
    """Ejemplo realista de la respuesta ``GET /RealTimeData`` del firmware.

    Claves y valores tomados de los usos reales en ``coordinator.py``,
    ``sensor.py``, ``switch.py``, ``number.py`` y ``select.py`` (no
    inventados). Los tests que necesiten variar un campo concreto deben
    copiar este dict y sobreescribir solo esa clave, para no tener que
    reconstruir el payload entero cada vez.

    Nota: valores booleanos "logicos" (Locked, Paused, Dynamic,
    PauseDynamic) llegan del firmware como enteros 0/1, tal y como los
    consumen ``switch.py``/``number.py`` (``bool(data.get(key, False))``).
    """
    return {
        "ChargePower": 3450.0,
        "ChargeEnergy": 12.5,
        "ChargeTime": 3600,
        "ChargeState": "1",
        "HousePower": 5200.0,
        "FVPower": 0.0,
        "BatteryPower": 0.0,
        "Intensity": 16,
        "MinIntensity": 6,
        "MaxIntensity": 32,
        "ContractedPower": 5750.0,
        "VoltageInstallation": 230,
        "ReadyState": 3,
        "Timer": 0,
        "Dynamic": 0,
        "DynamicPowerMode": 0,
        "Locked": 0,
        "Paused": 0,
        "PauseDynamic": 0,
        "SlaveError": "NO_ERROR",
        "FirmwareVersion": "1.6.13",
        "IP": FAKE_IP_ADDRESS,
        "SignalStatus": "Excelente",
        "SSID": "TEST-WIFI",
        "ID": "TEST-DEVICE-ID",
    }


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """``MockConfigEntry`` con los datos/opciones minimos que espera la integracion.

    ``data`` refleja lo que guarda ``config_flow.py`` (``async_step_user``):
    solo ``CONF_IP_ADDRESS``. ``options`` refleja los valores por defecto que
    lee ``V2CtrydanOptionsFlowHandler`` (``kwh_per_100km``, ``precio_luz``).

    Uso tipico en un test de otro modulo::

        async def test_algo(hass, mock_config_entry, mock_v2c_http, realtime_data):
            mock_config_entry.add_to_hass(hass)
            mock_v2c_http.get(
                f"http://{FAKE_IP_ADDRESS}/RealTimeData", payload=realtime_data
            )
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    """
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"V2C Trydan ({FAKE_IP_ADDRESS})",
        unique_id=FAKE_IP_ADDRESS,
        data={
            CONF_IP_ADDRESS: FAKE_IP_ADDRESS,
        },
        options={
            CONF_KWH_PER_100KM: 20.8,
            CONF_KM_TO_CHARGE: 100,
            CONF_PRECIO_LUZ: "sensor.pvpc",
        },
    )


@pytest.fixture
def mock_coordinator(realtime_data: dict) -> MagicMock:
    """``V2CtrydanDataUpdateCoordinator`` falso, listo para inyectar en entidades.

    Util para tests unitarios/de integracion ligera de plataformas
    (sensor/switch/number/select) que solo necesitan un coordinator con
    ``.data`` poblado y no quieren levantar todo el ciclo de
    ``async_setup_entry`` + polling HTTP real.

    ``mock_coordinator.data`` es una COPIA de ``realtime_data`` (dict nuevo),
    así que cada test puede mutarlo libremente sin afectar a otros tests.
    """
    coordinator = MagicMock()
    coordinator.data = dict(realtime_data)
    coordinator.ip_address = FAKE_IP_ADDRESS
    coordinator.last_update_success = True
    return coordinator


@pytest.fixture
def mock_v2c_http() -> Generator[aioresponses, None, None]:
    """Mock de las respuestas HTTP del dispositivo V2C Trydan via ``aioresponses``.

    Intercepta cualquier llamada ``aiohttp`` (las que hace
    ``async_get_clientsession(hass)`` internamente) a
    ``http://<ip>/RealTimeData`` o ``http://<ip>/write/...`` sin necesidad de
    un dispositivo real ni de mockear manualmente ``ClientSession``.

    Uso tipico::

        def test_algo(mock_v2c_http, realtime_data):
            mock_v2c_http.get(
                f"http://{FAKE_IP_ADDRESS}/RealTimeData",
                payload=realtime_data,
                repeat=True,  # permite varias llamadas (p.ej. polling)
            )
            mock_v2c_http.get(
                f"http://{FAKE_IP_ADDRESS}/write/MinIntensity=10",
                status=200,
            )
    """
    with aioresponses() as mocked:
        yield mocked
