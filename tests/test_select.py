"""Tests para custom_components/v2c_trydan/select.py.

Cubre ``DynamicPowerModeSelect`` (``CoordinatorEntity``):
- lectura de la opcion actual desde ``coordinator.data``,
- escritura de una nueva opcion (incluyendo el caso "ERROR" que devuelve el
  firmware),
- manejo de timeout y de excepciones genericas al escribir,
- el caso de opcion invalida (no llega a hacer HTTP ni a refrescar).

No se modifica codigo productivo. En particular, esta suite NO corrige el
bug conocido #6 (rango de ``DynamicPowerMode``): lo documenta tal cual se
comporta hoy (ver ``test_current_option_out_of_range_is_bug_6_not_fixed_here``
mas abajo).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from homeassistant.core import HomeAssistant

from custom_components.v2c_trydan.const import DOMAIN
from custom_components.v2c_trydan.select import DynamicPowerModeSelect

from tests.conftest import FAKE_IP_ADDRESS


def test_unique_id_device_info_and_icon(mock_coordinator):
    select = DynamicPowerModeSelect(mock_coordinator)

    assert select.unique_id == "v2c_dynamic_power_mode_select"
    assert select.icon == "mdi:cog"

    info = select.device_info
    assert info["identifiers"] == {(DOMAIN, FAKE_IP_ADDRESS)}
    assert info["configuration_url"] == f"http://{FAKE_IP_ADDRESS}"


# --- current_option ----------------------------------------------------


@pytest.mark.parametrize(
    ("mode_value", "expected_option"),
    [
        (0, "enable_timed_power"),
        (1, "disable_timed_power"),
        (2, "disable_timed_power_exclusive"),
        (3, "disable_timed_power_min"),
        (4, "disable_timed_power_grid_fv"),
        (5, "disable_timed_power_stop"),
    ],
)
def test_current_option_maps_valid_values(mock_coordinator, mode_value, expected_option):
    mock_coordinator.data["DynamicPowerMode"] = mode_value
    select = DynamicPowerModeSelect(mock_coordinator)

    assert select.current_option == expected_option


def test_current_option_none_when_coordinator_data_is_none(mock_coordinator):
    mock_coordinator.data = None
    select = DynamicPowerModeSelect(mock_coordinator)

    assert select.current_option is None


def test_current_option_none_when_dynamic_power_mode_key_missing(mock_coordinator):
    mock_coordinator.data.pop("DynamicPowerMode", None)
    select = DynamicPowerModeSelect(mock_coordinator)

    assert select.current_option is None


def test_current_option_out_of_range_is_bug_6_not_fixed_here(mock_coordinator):
    """HALLAZGO conocido (bug #6, fuera de alcance, NO se corrige aqui).

    Segun el contrato documentado en ``AGENTS.md`` (seccion 8, "Rangos
    validados") y la validacion ``0 <= dynamic_power_mode <= 7`` que aplica
    ``__init__.py::async_set_dynamic_power_mode`` al recibir el servicio
    ``set_dynamic_power_mode``, el firmware admite valores de
    ``DynamicPowerMode`` entre 0 y 7. Sin embargo,
    ``DYNAMIC_POWER_MODE_OPTIONS`` en ``select.py`` solo define 6 opciones
    (indices 0-5) y ``current_option`` solo acepta
    ``0 <= dynamic_power_mode <= 5``. Para un valor de firmware valido segun
    el contrato (6 o 7) esta propiedad devuelve ``None`` en vez de reflejar
    el estado real del dispositivo (solo se registra un ``_LOGGER.warning``).
    Este test documenta el comportamiento ACTUAL, no el deseado.
    """
    mock_coordinator.data["DynamicPowerMode"] = 6
    select = DynamicPowerModeSelect(mock_coordinator)

    assert select.current_option is None

    mock_coordinator.data["DynamicPowerMode"] = 7
    assert select.current_option is None


# --- async_select_option -------------------------------------------------


async def test_async_select_option_valid_writes_and_refreshes(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    mock_coordinator.async_request_refresh = AsyncMock()
    select = DynamicPowerModeSelect(mock_coordinator)
    select.hass = hass
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/DynamicPowerMode=2",
        status=200,
        body="OK",
    )

    await select.async_select_option("disable_timed_power_exclusive")

    mock_coordinator.async_request_refresh.assert_awaited_once()


async def test_async_select_option_invalid_option_skips_http_and_refresh(
    hass: HomeAssistant, mock_coordinator
):
    mock_coordinator.async_request_refresh = AsyncMock()
    select = DynamicPowerModeSelect(mock_coordinator)
    select.hass = hass

    # No se registra ningun mock HTTP: si el codigo intentase escribir,
    # fallaria de forma ruidosa (no hay ruta mockeada), lo que confirmaria
    # que esta prueba SI detectaria una regresion.
    await select.async_select_option("not_a_real_option")

    mock_coordinator.async_request_refresh.assert_not_awaited()


# --- _set_dynamic_power_mode ---------------------------------------------


async def test_set_dynamic_power_mode_success(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    select = DynamicPowerModeSelect(mock_coordinator)
    select.hass = hass
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/DynamicPowerMode=3",
        status=200,
        body="OK",
    )

    await select._set_dynamic_power_mode(3)  # no debe lanzar excepcion


async def test_set_dynamic_power_mode_device_error_raises_value_error(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    select = DynamicPowerModeSelect(mock_coordinator)
    select.hass = hass
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/DynamicPowerMode=4",
        status=200,
        body="ERROR",
    )

    with pytest.raises(ValueError):
        await select._set_dynamic_power_mode(4)


async def test_set_dynamic_power_mode_timeout_propagates(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    select = DynamicPowerModeSelect(mock_coordinator)
    select.hass = hass
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/DynamicPowerMode=5",
        exception=asyncio.TimeoutError(),
    )

    with pytest.raises(asyncio.TimeoutError):
        await select._set_dynamic_power_mode(5)


async def test_set_dynamic_power_mode_http_error_raises_client_error(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    select = DynamicPowerModeSelect(mock_coordinator)
    select.hass = hass
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/DynamicPowerMode=1",
        status=500,
    )

    with pytest.raises(aiohttp.ClientError):
        await select._set_dynamic_power_mode(1)


async def test_set_dynamic_power_mode_generic_exception_propagates(
    hass: HomeAssistant, mock_coordinator
):
    """Cualquier excepcion no prevista al escribir se relanza (rama ``except Exception``)."""
    select = DynamicPowerModeSelect(mock_coordinator)
    select.hass = hass

    fake_session = MagicMock()
    fake_session.get.side_effect = RuntimeError("fallo inesperado")

    with patch(
        "custom_components.v2c_trydan.select.async_get_clientsession",
        return_value=fake_session,
    ):
        with pytest.raises(RuntimeError):
            await select._set_dynamic_power_mode(3)


async def test_set_dynamic_power_mode_without_ip_address_returns_silently(
    hass: HomeAssistant, mock_coordinator
):
    """Sin IP configurada, se registra un error y se sale sin intentar HTTP.

    No se activa ``mock_v2c_http``: si el codigo intentase una llamada de
    red real, el guard de aislamiento de red del entorno de test la
    bloquearia de forma ruidosa, lo que haria fallar esta prueba y
    confirmaria una regresion.
    """
    mock_coordinator.ip_address = None
    select = DynamicPowerModeSelect(mock_coordinator)
    select.hass = hass

    result = await select._set_dynamic_power_mode(3)

    assert result is None
