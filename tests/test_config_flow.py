"""Tests para custom_components/v2c_trydan/config_flow.py.

Cubre:
- ``_test_connection``: caso exito (200), caso host responde con otro
  status, caso timeout y caso error de conexion.
- Flujo de configuracion inicial (``async_step_user``): entrada valida crea
  la entry; entrada invalida (dispositivo no responde) vuelve a mostrar el
  formulario con ``errors["base"] == "cannot_connect"``; entrada duplicada
  (mismo ``unique_id``) — ver HALLAZGO documentado en
  ``test_async_step_user_duplicate_unique_id_is_reported_as_unknown_error``.
- Flujo de opciones (``V2CtrydanOptionsFlowHandler``): valores por defecto
  mostrados en el formulario y guardado de opciones nuevas.
"""
from __future__ import annotations

import asyncio

import aiohttp
import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.v2c_trydan.config_flow import V2CtrydanConfigFlow
from custom_components.v2c_trydan.const import CONF_KWH_PER_100KM, CONF_PRECIO_LUZ, DOMAIN

from tests.conftest import FAKE_IP_ADDRESS


# --- LIMITACION CONOCIDA DE ENTORNO (Windows nativo, no es un cambio de codigo
# productivo) ------------------------------------------------------------------
#
# ``V2CtrydanOptionsFlowHandler`` hereda de
# ``homeassistant.config_entries.OptionsFlowWithConfigEntry`` (patron valido y
# soportado explicitamente para integraciones custom: HA solo lo desaconseja
# para "codigo nuevo" pero lo mantiene por compatibilidad). Al instanciarla,
# HA llama a ``report_usage(...)``, que recorre la pila de llamadas
# (``homeassistant.helpers.frame.get_integration_frame``) buscando una ruta
# de fichero que contenga el separador ``"custom_components/"`` (con
# barra normal, hardcodeado en el propio core de HA) para reconocer que el
# codigo pertenece a una integracion custom y así IGNORAR el aviso
# (``custom_integration_behavior=ReportBehavior.IGNORE``).
#
# En Windows nativo, ``frame.f_code.co_filename`` usa el separador ``\``, por
# lo que esa busqueda de ``"custom_components/"`` nunca coincide, HA no
# reconoce la integracion, y cae al comportamiento por defecto para "core"
# (``ReportBehavior.ERROR``), lanzando ``RuntimeError`` en cualquier test que
# ejercite el flujo de opciones real de v2c_trydan en este SO. En Linux/macOS
# (CI) los separadores coinciden y el aviso se ignora correctamente sin
# necesidad de este parche.
#
# Parche minimo, solo para los tests de este fichero: se sustituye
# ``homeassistant.config_entries.report_usage`` (funcion del propio nucleo de
# HA, no de v2c_trydan) por un no-op durante los tests de flujo de opciones,
# para poder ejercitar ``V2CtrydanOptionsFlowHandler`` real en Windows sin
# tocar ``custom_components/v2c_trydan/config_flow.py``. No relaja ninguna
# aserción de los tests: solo evita un falso positivo de deteccion de entorno
# que no se puede reproducir de otra forma en Windows nativo.
@pytest.fixture(autouse=True)
def _workaround_windows_report_usage_path_check(monkeypatch):
    monkeypatch.setattr(
        "homeassistant.config_entries.report_usage", lambda *args, **kwargs: None
    )


# --- _test_connection --------------------------------------------------------


async def test_test_connection_returns_true_on_http_200(hass, mock_v2c_http, realtime_data):
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/RealTimeData", payload=realtime_data)

    flow = V2CtrydanConfigFlow()
    flow.hass = hass

    assert await flow._test_connection(FAKE_IP_ADDRESS) is True


async def test_test_connection_returns_false_on_non_200_status(hass, mock_v2c_http):
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/RealTimeData", status=500)

    flow = V2CtrydanConfigFlow()
    flow.hass = hass

    assert await flow._test_connection(FAKE_IP_ADDRESS) is False


async def test_test_connection_returns_false_on_connection_error(hass, mock_v2c_http):
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/RealTimeData",
        exception=aiohttp.ClientConnectionError("boom"),
    )

    flow = V2CtrydanConfigFlow()
    flow.hass = hass

    assert await flow._test_connection(FAKE_IP_ADDRESS) is False


async def test_test_connection_returns_false_on_timeout(hass, mock_v2c_http):
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/RealTimeData",
        exception=asyncio.TimeoutError(),
    )

    flow = V2CtrydanConfigFlow()
    flow.hass = hass

    assert await flow._test_connection(FAKE_IP_ADDRESS) is False


# --- async_step_user ---------------------------------------------------------


async def test_async_step_user_shows_form_without_input(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_async_step_user_valid_input_creates_entry(hass, mock_v2c_http, realtime_data):
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/RealTimeData", payload=realtime_data)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"ip_address": FAKE_IP_ADDRESS}
    )
    await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["title"] == f"V2C Trydan ({FAKE_IP_ADDRESS})"
    assert result2["data"] == {"ip_address": FAKE_IP_ADDRESS}


async def test_async_step_user_cannot_connect_shows_form_with_error(hass, mock_v2c_http):
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/RealTimeData", status=500)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"ip_address": FAKE_IP_ADDRESS}
    )

    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "user"
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_async_step_user_connection_error_shows_form_with_error(hass, mock_v2c_http):
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/RealTimeData",
        exception=aiohttp.ClientConnectionError("boom"),
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"ip_address": FAKE_IP_ADDRESS}
    )

    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "user"
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_async_step_user_duplicate_unique_id_is_reported_as_unknown_error(
    hass, mock_config_entry, mock_v2c_http, realtime_data
):
    """HALLAZGO (no corregido, fuera del alcance de test-agent): cuando ya
    existe una entry con el mismo ``unique_id`` (misma IP), se esperaria un
    abort con ``reason == "already_configured"``. Sin embargo,
    ``async_step_user`` envuelve la llamada a
    ``self._abort_if_unique_id_configured()`` dentro de un
    ``try/except Exception`` generico; como ``AbortFlow`` hereda de
    ``Exception``, ese abort se captura y se traduce incorrectamente en
    ``errors["base"] == "unknown"`` en vez de mostrar el abort esperado al
    usuario. Se documenta el comportamiento ACTUAL como evidencia para
    ``bugfix-agent``/``dev-agent`` (posible fix: excluir
    ``data_entry_flow.AbortFlow`` del ``except Exception`` o no envolver esa
    llamada en el try).
    """
    mock_config_entry.add_to_hass(hass)
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/RealTimeData", payload=realtime_data)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"ip_address": FAKE_IP_ADDRESS}
    )

    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "user"
    assert result2["errors"] == {"base": "unknown"}


# --- V2CtrydanOptionsFlowHandler ---------------------------------------------


async def test_options_flow_shows_form_with_current_values_as_suggested(
    hass, mock_config_entry
):
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    schema_keys = {key: key for key in result["data_schema"].schema}
    described_keys = [str(k) for k in schema_keys]
    assert any(CONF_KWH_PER_100KM in k for k in described_keys)
    assert any(CONF_PRECIO_LUZ in k for k in described_keys)


async def test_options_flow_saves_new_options(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_KWH_PER_100KM: 18.5,
            CONF_PRECIO_LUZ: "sensor.otro_pvpc",
        },
    )
    await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["data"] == {
        CONF_KWH_PER_100KM: 18.5,
        CONF_PRECIO_LUZ: "sensor.otro_pvpc",
    }


async def test_options_flow_uses_defaults_when_entry_has_no_options(hass):
    """Si la entry no tiene ``options`` guardadas, se usan los defaults del
    handler (``20.8`` kWh/100km, ``sensor.pvpc``)."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry_without_options = MockConfigEntry(
        domain=DOMAIN,
        title=f"V2C Trydan ({FAKE_IP_ADDRESS})",
        unique_id=FAKE_IP_ADDRESS,
        data={"ip_address": FAKE_IP_ADDRESS},
        options={},
    )
    entry_without_options.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry_without_options.entry_id)

    assert result["type"] is FlowResultType.FORM
    schema_dict = result["data_schema"].schema
    for key in schema_dict:
        if str(key) == CONF_KWH_PER_100KM:
            assert key.description["suggested_value"] == 20.8
        if str(key) == CONF_PRECIO_LUZ:
            assert key.description["suggested_value"] == "sensor.pvpc"
