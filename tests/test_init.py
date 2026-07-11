"""Tests para custom_components/v2c_trydan/__init__.py.

Cubre:
- ``async_setup_entry``/``async_unload_entry``: caso exito y caso de fallo
  de conexion inicial (el coordinator agota los reintentos de ``tenacity``
  y ``async_config_entry_first_refresh`` deja la entry en
  ``SETUP_RETRY``).
- Los 7 servicios registrados (``services.yaml``): validacion de rango,
  tipos invalidos (``ValueError``/``KeyError``/``TypeError``) y que NO se
  realiza ninguna llamada HTTP cuando la validacion falla.
- Las funciones de escritura HTTP (``async_set_min_intensity``,
  ``async_set_max_intensity``, ``async_set_intensity``,
  ``async_write_dynamic_power_mode``): caso exito, caso error HTTP y caso
  timeout, usando ``mock_v2c_http`` (nunca red real).

Nota sobre el caso "timeout" de las funciones de escritura: ver el
HALLAZGO documentado junto a
``test_async_set_min_intensity_timeout_propagates_uncaught`` mas abajo.
No se modifica codigo productivo (fuera del alcance de test-agent);
se documenta el comportamiento actual como evidencia para
``bugfix-agent``/``dev-agent``.
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.v2c_trydan import (
    DOMAIN,
    async_set_intensity,
    async_set_max_intensity,
    async_set_min_intensity,
    async_setup,
    async_write_dynamic_power_mode,
)

from tests.conftest import FAKE_IP_ADDRESS

ALL_SERVICES = [
    "set_min_intensity",
    "set_max_intensity",
    "set_dynamic_power_mode",
    "set_intensity",
    "set_min_intensity_slider",
    "set_max_intensity_slider",
    "set_dynamic_power_mode_slider",
]


def _requested_urls(mock_v2c_http) -> list[str]:
    """Devuelve las URLs realmente solicitadas via ``mock_v2c_http``."""
    return [str(url) for (_method, url) in mock_v2c_http.requests.keys()]


def _requested_write_urls(mock_v2c_http) -> list[str]:
    """Devuelve solo las URLs de escritura (``/write/...``) solicitadas.

    ``setup_integration`` deja registrada una llamada real a
    ``/RealTimeData`` (el primer refresco del coordinator); se filtra para
    poder afirmar "no se realizo ninguna escritura" sin que ese polling
    inicial, no relacionado con la validacion del servicio, ensucie la
    comprobacion.
    """
    return [url for url in _requested_urls(mock_v2c_http) if "/write/" in url]


@pytest.fixture
async def setup_integration(hass, mock_config_entry, mock_v2c_http, realtime_data):
    """Entry de v2c_trydan completamente cargada (coordinator + plataformas + servicios)."""
    mock_config_entry.add_to_hass(hass)
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/RealTimeData", payload=realtime_data, repeat=True
    )

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    return mock_config_entry


# --- async_setup (configuration.yaml legacy import) -------------------------


async def test_async_setup_without_yaml_config_returns_true_and_does_not_import(hass):
    """Sin configuracion YAML del dominio, ``async_setup`` no crea ningun flow de import."""
    assert await async_setup(hass, {}) is True
    assert hass.data[DOMAIN] == {}


async def test_async_setup_with_yaml_config_schedules_import_flow(hass, mock_v2c_http, realtime_data):
    """Con configuracion YAML legada del dominio, se programa un flow de import por entrada."""
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/RealTimeData", payload=realtime_data)

    assert await async_setup(hass, {DOMAIN: [{"ip_address": FAKE_IP_ADDRESS}]}) is True
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].data["ip_address"] == FAKE_IP_ADDRESS


# --- async_setup_entry / async_unload_entry ---------------------------------


async def test_async_setup_entry_success_registers_coordinator_device_and_services(
    hass, mock_config_entry, mock_v2c_http, realtime_data
):
    """Caso exito: coordinator, device registry y los 7 servicios quedan registrados."""
    mock_config_entry.add_to_hass(hass)
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/RealTimeData", payload=realtime_data, repeat=True
    )

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED

    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
    assert coordinator.ip_address == FAKE_IP_ADDRESS
    assert coordinator.data == realtime_data

    for service in ALL_SERVICES:
        assert hass.services.has_service(DOMAIN, service), f"falta servicio {service}"


async def test_async_unload_entry_removes_coordinator_from_hass_data(
    hass, setup_integration
):
    """Caso exito de descarga: la entry deja de estar en ``hass.data[DOMAIN]``."""
    entry = setup_integration

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_async_setup_entry_initial_connection_failure_sets_setup_retry(
    hass, mock_config_entry, mock_v2c_http
):
    """Fallo de conexion inicial: el coordinator agota reintentos y la entry
    queda en ``SETUP_RETRY`` en lugar de ``LOADED``.

    Nota: este test tarda unos segundos porque ejercita los reintentos reales
    de ``tenacity`` (``stop_after_attempt(3)`` + ``wait_fixed(2)``) del
    coordinator; no se acorta ese comportamiento porque no se puede tocar
    codigo productivo.
    """
    mock_config_entry.add_to_hass(hass)
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/RealTimeData",
        exception=aiohttp.ClientConnectionError("boom"),
        repeat=True,
    )

    result = await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert result is False
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert DOMAIN not in hass.data or mock_config_entry.entry_id not in hass.data[DOMAIN]


# --- Servicios: validacion de parametros ------------------------------------


async def test_set_min_intensity_service_success_calls_write_endpoint(
    hass, setup_integration, mock_v2c_http
):
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/MinIntensity=10", status=200)

    await hass.services.async_call(
        DOMAIN, "set_min_intensity", {"min_intensity": 10}, blocking=True
    )
    await hass.async_block_till_done()

    assert f"http://{FAKE_IP_ADDRESS}/write/MinIntensity=10" in _requested_urls(mock_v2c_http)


async def test_set_min_intensity_service_out_of_range_does_not_call_http(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(
        DOMAIN, "set_min_intensity", {"min_intensity": 5}, blocking=True
    )
    await hass.async_block_till_done()

    assert "must be between 6 and 32" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_min_intensity_service_missing_param_logs_type_error(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(DOMAIN, "set_min_intensity", {}, blocking=True)
    await hass.async_block_till_done()

    assert "Invalid or missing min_intensity" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_min_intensity_service_non_numeric_logs_value_error(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(
        DOMAIN, "set_min_intensity", {"min_intensity": "not-a-number"}, blocking=True
    )
    await hass.async_block_till_done()

    assert "Invalid or missing min_intensity" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_max_intensity_service_success_calls_write_endpoint(
    hass, setup_integration, mock_v2c_http
):
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/MaxIntensity=32", status=200)

    await hass.services.async_call(
        DOMAIN, "set_max_intensity", {"max_intensity": 32}, blocking=True
    )
    await hass.async_block_till_done()

    assert f"http://{FAKE_IP_ADDRESS}/write/MaxIntensity=32" in _requested_urls(mock_v2c_http)


async def test_set_max_intensity_service_out_of_range_does_not_call_http(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(
        DOMAIN, "set_max_intensity", {"max_intensity": 33}, blocking=True
    )
    await hass.async_block_till_done()

    assert "max_intensity must be between 6" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_max_intensity_service_non_numeric_logs_value_error(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(
        DOMAIN, "set_max_intensity", {"max_intensity": "not-a-number"}, blocking=True
    )
    await hass.async_block_till_done()

    assert "Invalid or missing max_intensity" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_intensity_service_success_calls_write_endpoint(
    hass, setup_integration, mock_v2c_http
):
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/Intensity=16", status=200)

    await hass.services.async_call(
        DOMAIN, "set_intensity", {"intensity": 16}, blocking=True
    )
    await hass.async_block_till_done()

    assert f"http://{FAKE_IP_ADDRESS}/write/Intensity=16" in _requested_urls(mock_v2c_http)


async def test_set_intensity_service_non_numeric_logs_value_error(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(
        DOMAIN, "set_intensity", {"intensity": "abc"}, blocking=True
    )
    await hass.async_block_till_done()

    assert "Invalid or missing intensity" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_intensity_service_out_of_range_does_not_call_http(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(
        DOMAIN, "set_intensity", {"intensity": 40}, blocking=True
    )
    await hass.async_block_till_done()

    assert "intensity must be between 6" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_dynamic_power_mode_service_success_calls_write_endpoint(
    hass, setup_integration, mock_v2c_http
):
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/DynamicPowerMode=3", status=200)

    await hass.services.async_call(
        DOMAIN, "set_dynamic_power_mode", {"DynamicPowerMode": 3}, blocking=True
    )
    await hass.async_block_till_done()

    assert f"http://{FAKE_IP_ADDRESS}/write/DynamicPowerMode=3" in _requested_urls(
        mock_v2c_http
    )


async def test_set_dynamic_power_mode_service_out_of_range_does_not_call_http(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(
        DOMAIN, "set_dynamic_power_mode", {"DynamicPowerMode": 8}, blocking=True
    )
    await hass.async_block_till_done()

    assert "DynamicPowerMode must be between 0 and 7" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_dynamic_power_mode_service_missing_param_logs_type_error(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(DOMAIN, "set_dynamic_power_mode", {}, blocking=True)
    await hass.async_block_till_done()

    assert "Invalid or missing DynamicPowerMode" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_min_intensity_slider_service_success_calls_write_endpoint(
    hass, setup_integration, mock_v2c_http
):
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/MinIntensity=8", status=200)

    await hass.services.async_call(
        DOMAIN, "set_min_intensity_slider", {"v2c_min_intensity": 8}, blocking=True
    )
    await hass.async_block_till_done()

    assert f"http://{FAKE_IP_ADDRESS}/write/MinIntensity=8" in _requested_urls(mock_v2c_http)


async def test_set_min_intensity_slider_service_not_provided_logs_error(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(DOMAIN, "set_min_intensity_slider", {}, blocking=True)
    await hass.async_block_till_done()

    assert "v2c_min_intensity not provided" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_min_intensity_slider_service_out_of_range_does_not_call_http(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(
        DOMAIN, "set_min_intensity_slider", {"v2c_min_intensity": 40}, blocking=True
    )
    await hass.async_block_till_done()

    assert "v2c_min_intensity must be between 6" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_min_intensity_slider_service_non_numeric_logs_value_error(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(
        DOMAIN,
        "set_min_intensity_slider",
        {"v2c_min_intensity": "not-a-number"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert "Invalid or missing v2c_min_intensity" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_max_intensity_slider_service_success_calls_write_endpoint(
    hass, setup_integration, mock_v2c_http
):
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/MaxIntensity=30", status=200)

    await hass.services.async_call(
        DOMAIN, "set_max_intensity_slider", {"v2c_max_intensity": 30}, blocking=True
    )
    await hass.async_block_till_done()

    assert f"http://{FAKE_IP_ADDRESS}/write/MaxIntensity=30" in _requested_urls(
        mock_v2c_http
    )


async def test_set_max_intensity_slider_service_non_numeric_logs_value_error(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(
        DOMAIN,
        "set_max_intensity_slider",
        {"v2c_max_intensity": "not-a-number"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert "Invalid or missing v2c_max_intensity" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_max_intensity_slider_service_not_provided_logs_error(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(DOMAIN, "set_max_intensity_slider", {}, blocking=True)
    await hass.async_block_till_done()

    assert "v2c_max_intensity not provided" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_max_intensity_slider_service_out_of_range_does_not_call_http(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(
        DOMAIN, "set_max_intensity_slider", {"v2c_max_intensity": 40}, blocking=True
    )
    await hass.async_block_till_done()

    assert "v2c_max_intensity must be between 6" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_dynamic_power_mode_slider_service_success_calls_write_endpoint(
    hass, setup_integration, mock_v2c_http
):
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/DynamicPowerMode=1", status=200)

    await hass.services.async_call(
        DOMAIN,
        "set_dynamic_power_mode_slider",
        {"v2c_dynamic_power_mode": 1},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert f"http://{FAKE_IP_ADDRESS}/write/DynamicPowerMode=1" in _requested_urls(
        mock_v2c_http
    )


async def test_set_dynamic_power_mode_slider_service_non_numeric_logs_value_error(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(
        DOMAIN,
        "set_dynamic_power_mode_slider",
        {"v2c_dynamic_power_mode": "not-a-number"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert "Invalid or missing v2c_dynamic_power_mode" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_dynamic_power_mode_slider_service_not_provided_logs_error(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(
        DOMAIN, "set_dynamic_power_mode_slider", {}, blocking=True
    )
    await hass.async_block_till_done()

    assert "v2c_dynamic_power_mode not provided" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


async def test_set_dynamic_power_mode_slider_service_out_of_range_does_not_call_http(
    hass, setup_integration, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)

    await hass.services.async_call(
        DOMAIN,
        "set_dynamic_power_mode_slider",
        {"v2c_dynamic_power_mode": 9},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert "v2c_dynamic_power_mode must be between 0" in caplog.text
    assert _requested_write_urls(mock_v2c_http) == []


# --- Funciones de escritura HTTP: exito / error HTTP / timeout --------------


async def test_async_set_min_intensity_success_logs_debug(hass, mock_v2c_http, caplog):
    caplog.set_level(logging.DEBUG)
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/MinIntensity=10", status=200)

    await async_set_min_intensity(hass, FAKE_IP_ADDRESS, 10)

    assert "Min intensity set to 10" in caplog.text


async def test_async_set_min_intensity_http_error_logs_error(hass, mock_v2c_http, caplog):
    caplog.set_level(logging.ERROR)
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/MinIntensity=10", status=500)

    await async_set_min_intensity(hass, FAKE_IP_ADDRESS, 10)

    assert "Error setting min intensity" in caplog.text


async def test_async_set_min_intensity_timeout_propagates_uncaught(hass, mock_v2c_http):
    """HALLAZGO (no corregido, fuera del alcance de test-agent): las
    funciones de escritura HTTP (``async_set_min_intensity`` y equivalentes)
    solo capturan ``aiohttp.ClientError``. Un timeout total de la peticion
    (``asyncio.TimeoutError``, lanzado por ``aiohttp`` cuando expira
    ``ClientTimeout(total=...)`` y que NO es subclase de
    ``aiohttp.ClientError``) se propaga sin capturar ni loguear.

    Cuando esta funcion se llama desde uno de los servicios registrados en
    ``async_setup_entry`` (p.ej. ``set_min_intensity``), el
    ``except (ValueError, KeyError, TypeError)`` del handler del servicio
    tampoco lo captura, por lo que el timeout se propaga sin control fuera
    del handler de servicio de Home Assistant. Se documenta el
    comportamiento ACTUAL como evidencia para ``bugfix-agent``/``dev-agent``
    (posible fix: capturar tambien ``asyncio.TimeoutError`` en las funciones
    de escritura).
    """
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/MinIntensity=10",
        exception=asyncio.TimeoutError(),
    )

    with pytest.raises(asyncio.TimeoutError):
        await async_set_min_intensity(hass, FAKE_IP_ADDRESS, 10)


async def test_async_set_max_intensity_success_logs_debug(hass, mock_v2c_http, caplog):
    caplog.set_level(logging.DEBUG)
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/MaxIntensity=32", status=200)

    await async_set_max_intensity(hass, FAKE_IP_ADDRESS, 32)

    assert "Max intensity set to 32" in caplog.text


async def test_async_set_max_intensity_http_error_logs_error(hass, mock_v2c_http, caplog):
    caplog.set_level(logging.ERROR)
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/MaxIntensity=32", status=500)

    await async_set_max_intensity(hass, FAKE_IP_ADDRESS, 32)

    assert "Error setting max intensity" in caplog.text


async def test_async_set_max_intensity_timeout_propagates_uncaught(hass, mock_v2c_http):
    """Mismo HALLAZGO que ``test_async_set_min_intensity_timeout_propagates_uncaught``."""
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/MaxIntensity=32",
        exception=asyncio.TimeoutError(),
    )

    with pytest.raises(asyncio.TimeoutError):
        await async_set_max_intensity(hass, FAKE_IP_ADDRESS, 32)


async def test_async_set_intensity_success_logs_debug(hass, mock_v2c_http, caplog):
    caplog.set_level(logging.DEBUG)
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/Intensity=16", status=200)

    await async_set_intensity(hass, FAKE_IP_ADDRESS, 16)

    assert "Intensity set to 16" in caplog.text


async def test_async_set_intensity_http_error_logs_error(hass, mock_v2c_http, caplog):
    caplog.set_level(logging.ERROR)
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/Intensity=16", status=500)

    await async_set_intensity(hass, FAKE_IP_ADDRESS, 16)

    assert "Error setting intensity" in caplog.text


async def test_async_set_intensity_timeout_propagates_uncaught(hass, mock_v2c_http):
    """Mismo HALLAZGO que ``test_async_set_min_intensity_timeout_propagates_uncaught``."""
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/Intensity=16",
        exception=asyncio.TimeoutError(),
    )

    with pytest.raises(asyncio.TimeoutError):
        await async_set_intensity(hass, FAKE_IP_ADDRESS, 16)


async def test_async_write_dynamic_power_mode_success_logs_debug(hass, mock_v2c_http, caplog):
    caplog.set_level(logging.DEBUG)
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/DynamicPowerMode=2", status=200)

    await async_write_dynamic_power_mode(hass, FAKE_IP_ADDRESS, 2)

    assert "Dynamic power mode set to 2" in caplog.text


async def test_async_write_dynamic_power_mode_http_error_logs_error(
    hass, mock_v2c_http, caplog
):
    caplog.set_level(logging.ERROR)
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/DynamicPowerMode=2", status=500)

    await async_write_dynamic_power_mode(hass, FAKE_IP_ADDRESS, 2)

    assert "Error setting dynamic power mode" in caplog.text


async def test_async_write_dynamic_power_mode_timeout_propagates_uncaught(
    hass, mock_v2c_http
):
    """Mismo HALLAZGO que ``test_async_set_min_intensity_timeout_propagates_uncaught``."""
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/DynamicPowerMode=2",
        exception=asyncio.TimeoutError(),
    )

    with pytest.raises(asyncio.TimeoutError):
        await async_write_dynamic_power_mode(hass, FAKE_IP_ADDRESS, 2)
