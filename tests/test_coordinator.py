"""Tests para custom_components/v2c_trydan/coordinator.py.

Cubre la logica de negocio del coordinator (no boilerplate de
``DataUpdateCoordinator``):

- ``_async_update_data``: exito, umbral de 5 fallos consecutivos antes de
  reportar error persistente, y recuperacion tras fallos (reseteo de
  contador + log de recuperacion).
- ``_async_get_json``: 200 OK con JSON valido, JSON malformado reparado via
  ``arreglar_json_invalido``, status HTTP no-200, timeout, y el
  comportamiento de reintentos de ``tenacity`` (agotados y con recuperacion
  en un reintento posterior).
- ``arreglar_json_invalido``: delega en ``json_repair.repair_v2c_json`` y
  envuelve un fallo de parseo persistente como ``UpdateFailed``.

Notas de entorno:
- Los tests de reintentos agotados de ``tenacity`` (``stop_after_attempt(3)``,
  ``wait_fixed(2)``) esperan de verdad ~4s (2 esperas de 2s entre los 3
  intentos): son deliberadamente mas lentos que el resto, no son flakes.
- Se usa ``mock_v2c_http`` (aioresponses) para toda la red HTTP; nunca se
  golpea el dispositivo real ni se mockea manualmente ``ClientSession``.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import client_exceptions
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed
from tenacity import RetryError

from custom_components.v2c_trydan.coordinator import (
    V2CtrydanDataUpdateCoordinator,
    arreglar_json_invalido,
)

from tests.conftest import FAKE_IP_ADDRESS

REALTIME_DATA_URL = f"http://{FAKE_IP_ADDRESS}/RealTimeData"


def _make_coordinator(hass: HomeAssistant) -> V2CtrydanDataUpdateCoordinator:
    """Instancia el coordinator real, sin pasar por ``async_setup_entry``."""
    return V2CtrydanDataUpdateCoordinator(hass, FAKE_IP_ADDRESS)


# ---------------------------------------------------------------------------
# _async_update_data
# ---------------------------------------------------------------------------


async def test_async_update_data_success_returns_parsed_data(
    hass: HomeAssistant, realtime_data: dict
):
    """Caso exito: devuelve los datos tal cual los da ``_async_get_json``."""
    coordinator = _make_coordinator(hass)
    coordinator._async_get_json = AsyncMock(return_value=realtime_data)

    result = await coordinator._async_update_data()

    assert result == realtime_data
    assert coordinator._consecutive_errors == 0
    assert coordinator.error_reportado is False


async def test_async_update_data_failures_below_threshold_do_not_report_persistent_error(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
):
    """Por debajo del umbral de 5 fallos consecutivos, no se marca error
    persistente ni se loggea el mensaje de error accionable, aunque cada
    fallo individual siga propagando ``UpdateFailed``."""
    coordinator = _make_coordinator(hass)
    coordinator._async_get_json = AsyncMock(side_effect=Exception("boom"))

    with caplog.at_level(logging.DEBUG):
        for _ in range(4):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

    assert coordinator._consecutive_errors == 4
    assert coordinator.error_reportado is False
    assert "Persistent errors communicating" not in caplog.text


async def test_async_update_data_reports_persistent_error_at_threshold(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
):
    """Al llegar al 5o fallo consecutivo (``MAX_CONSECUTIVE_ERRORS``), se
    marca ``error_reportado`` y se loggea el error persistente exactamente
    una vez, aunque los fallos posteriores sigan produciendose."""
    coordinator = _make_coordinator(hass)
    coordinator._async_get_json = AsyncMock(side_effect=Exception("boom"))

    with caplog.at_level(logging.ERROR):
        for _ in range(4):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

        assert coordinator.error_reportado is False

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        assert coordinator._consecutive_errors == 5
        assert coordinator.error_reportado is True
        assert (
            f"Persistent errors communicating with {FAKE_IP_ADDRESS} "
            "after 5 attempts" in caplog.text
        )

        # Un 6o fallo no debe volver a loggear el mensaje persistente
        # (el codigo solo loggea si ``not self.error_reportado``).
        persistent_occurrences_before = caplog.text.count(
            "Persistent errors communicating"
        )
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
        persistent_occurrences_after = caplog.text.count(
            "Persistent errors communicating"
        )

        assert persistent_occurrences_after == persistent_occurrences_before
        assert coordinator._consecutive_errors == 6
        assert coordinator.error_reportado is True


async def test_async_update_data_recovers_after_failures(
    hass: HomeAssistant, realtime_data: dict, caplog: pytest.LogCaptureFixture
):
    """Tras fallos consecutivos, una actualizacion exitosa resetea el
    contador y ``error_reportado``, y loggea la recuperacion de conexion."""
    coordinator = _make_coordinator(hass)
    coordinator._async_get_json = AsyncMock(side_effect=Exception("boom"))

    with caplog.at_level(logging.INFO):
        for _ in range(5):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

        assert coordinator.error_reportado is True
        assert coordinator._consecutive_errors == 5

        coordinator._async_get_json = AsyncMock(return_value=realtime_data)
        result = await coordinator._async_update_data()

    assert result == realtime_data
    assert coordinator._consecutive_errors == 0
    assert coordinator.error_reportado is False
    assert f"Connection to {FAKE_IP_ADDRESS} restored" in caplog.text


async def test_async_update_data_wraps_retry_error_as_update_failed(
    hass: HomeAssistant,
):
    """Si ``_async_get_json`` agota los reintentos de ``tenacity`` y
    propaga ``RetryError``, se cuenta como fallo y se envuelve en
    ``UpdateFailed`` con un mensaje que menciona los reintentos."""
    coordinator = _make_coordinator(hass)
    coordinator._async_get_json = AsyncMock(
        side_effect=RetryError(last_attempt=MagicMock())
    )

    with pytest.raises(UpdateFailed, match="after multiple retries"):
        await coordinator._async_update_data()

    assert coordinator._consecutive_errors == 1
    assert coordinator.error_reportado is False


async def test_async_update_data_reports_persistent_error_at_threshold_for_retry_error(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
):
    """El umbral de 5 fallos consecutivos y el log de error persistente
    tambien se aplican cuando el fallo repetido es ``RetryError`` (rama
    separada de la del resto de excepciones en ``_async_update_data``)."""
    coordinator = _make_coordinator(hass)
    coordinator._async_get_json = AsyncMock(
        side_effect=RetryError(last_attempt=MagicMock())
    )

    with caplog.at_level(logging.ERROR):
        for _ in range(5):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

    assert coordinator._consecutive_errors == 5
    assert coordinator.error_reportado is True
    assert (
        f"Persistent connection issues with {FAKE_IP_ADDRESS} after 5 attempts"
        in caplog.text
    )


# ---------------------------------------------------------------------------
# _async_get_json
# ---------------------------------------------------------------------------


async def test_async_get_json_returns_parsed_data_on_200(
    hass: HomeAssistant, mock_v2c_http, realtime_data: dict
):
    """200 OK con JSON valido se parsea directamente, sin reparaciones."""
    mock_v2c_http.get(REALTIME_DATA_URL, payload=realtime_data)
    coordinator = _make_coordinator(hass)
    session = async_get_clientsession(hass)

    result = await coordinator._async_get_json(session, REALTIME_DATA_URL)

    assert result == realtime_data


async def test_async_get_json_repairs_malformed_json(
    hass: HomeAssistant, mock_v2c_http
):
    """JSON con la coma ausente antes de ``ReadyState`` (defecto real y
    conocido del firmware) hace fallar el ``json.loads`` inicial y se
    repara via ``arreglar_json_invalido``.

    Nota: a diferencia de un ``FirmwareVersion`` duplicado (que
    ``json.loads`` acepta sintacticamente, quedandose con el ultimo valor,
    sin necesitar reparacion), este caso SI rompe el parseo inicial y
    ejerce de verdad la rama de reparacion de ``_async_get_json``.
    """
    malformed = '{"ChargePower":50"ReadyState":3}'
    mock_v2c_http.get(
        REALTIME_DATA_URL, body=malformed, content_type="application/json"
    )
    coordinator = _make_coordinator(hass)
    session = async_get_clientsession(hass)

    result = await coordinator._async_get_json(session, REALTIME_DATA_URL)

    assert result["ChargePower"] == 50
    assert result["ReadyState"] == 3


async def test_async_get_json_logs_debug_on_unexpected_content_type(
    hass: HomeAssistant, mock_v2c_http, realtime_data: dict, caplog: pytest.LogCaptureFixture
):
    """El firmware a veces responde con un ``Content-Type`` incorrecto
    (texto en lugar de ``application/json``); se loggea en debug pero se
    sigue parseando el cuerpo como JSON igualmente."""
    mock_v2c_http.get(
        REALTIME_DATA_URL,
        body=json.dumps(realtime_data),
        content_type="text/plain",
    )
    coordinator = _make_coordinator(hass)
    session = async_get_clientsession(hass)

    with caplog.at_level(logging.DEBUG):
        result = await coordinator._async_get_json(session, REALTIME_DATA_URL)

    assert result == realtime_data
    assert "Device returned non-JSON content-type" in caplog.text


async def test_async_get_json_non_200_status_exhausts_retries(
    hass: HomeAssistant, mock_v2c_http
):
    """Un status HTTP no-200 persistente agota los 3 intentos de
    ``tenacity`` y termina propagando ``RetryError``.

    Nota: este test espera de verdad ~4s (2 esperas de ``wait_fixed(2)``
    entre los 3 intentos); es lento a proposito, no es un flake.
    """
    mock_v2c_http.get(REALTIME_DATA_URL, status=500, repeat=True)
    coordinator = _make_coordinator(hass)
    session = async_get_clientsession(hass)

    with pytest.raises(RetryError):
        await coordinator._async_get_json(session, REALTIME_DATA_URL)


async def test_async_get_json_timeout_exhausts_retries(
    hass: HomeAssistant, mock_v2c_http
):
    """Un timeout persistente del dispositivo agota los reintentos de
    ``tenacity`` y termina propagando ``RetryError``.

    Nota: este test espera de verdad ~4s (2 esperas de ``wait_fixed(2)``
    entre los 3 intentos); es lento a proposito, no es un flake.
    """
    mock_v2c_http.get(
        REALTIME_DATA_URL,
        exception=client_exceptions.ServerTimeoutError("timed out"),
        repeat=True,
    )
    coordinator = _make_coordinator(hass)
    session = async_get_clientsession(hass)

    with pytest.raises(RetryError):
        await coordinator._async_get_json(session, REALTIME_DATA_URL)


async def test_async_get_json_non_2xx_status_without_raise_for_status_exhausts_retries(
    hass: HomeAssistant, mock_v2c_http
):
    """Un status distinto de 200 que ``raise_for_status()`` NO considera
    error (p.ej. 204 No Content), como podria darse en una respuesta 2xx/3xx
    atipica, se trata explicitamente como error HTTP (no como ``None``
    implicito) y tambien agota los reintentos de ``tenacity``.

    Nota: este test espera de verdad ~4s (2 esperas de ``wait_fixed(2)``
    entre los 3 intentos); es lento a proposito, no es un flake.
    """
    mock_v2c_http.get(REALTIME_DATA_URL, status=204, repeat=True)
    coordinator = _make_coordinator(hass)
    session = async_get_clientsession(hass)

    with pytest.raises(RetryError):
        await coordinator._async_get_json(session, REALTIME_DATA_URL)


async def test_async_get_json_connector_error_exhausts_retries(
    hass: HomeAssistant, mock_v2c_http
):
    """Un fallo de conexion (``ClientConnectorError``, p.ej. host
    inalcanzable) agota los reintentos de ``tenacity``.

    Nota: este test espera de verdad ~4s (2 esperas de ``wait_fixed(2)``
    entre los 3 intentos); es lento a proposito, no es un flake.
    """
    connection_key = MagicMock()
    connection_key.ssl = False
    mock_v2c_http.get(
        REALTIME_DATA_URL,
        exception=client_exceptions.ClientConnectorError(
            connection_key=connection_key, os_error=OSError("boom")
        ),
        repeat=True,
    )
    coordinator = _make_coordinator(hass)
    session = async_get_clientsession(hass)

    with pytest.raises(RetryError):
        await coordinator._async_get_json(session, REALTIME_DATA_URL)


async def test_async_get_json_unexpected_exception_exhausts_retries(
    hass: HomeAssistant, mock_v2c_http
):
    """Una excepcion inesperada no cubierta por las ramas especificas
    (``ClientConnectorError``/``ServerTimeoutError``/``ClientError``/
    ``JSONDecodeError``) cae en el ``except Exception`` generico y tambien
    se reintenta hasta agotar los intentos de ``tenacity``.

    Nota: este test espera de verdad ~4s (2 esperas de ``wait_fixed(2)``
    entre los 3 intentos); es lento a proposito, no es un flake.
    """
    mock_v2c_http.get(
        REALTIME_DATA_URL, exception=ValueError("unexpected"), repeat=True
    )
    coordinator = _make_coordinator(hass)
    session = async_get_clientsession(hass)

    with pytest.raises(RetryError):
        await coordinator._async_get_json(session, REALTIME_DATA_URL)


async def test_async_get_json_retries_and_recovers_on_second_attempt(
    hass: HomeAssistant, mock_v2c_http, realtime_data: dict
):
    """Un primer intento fallido seguido de un segundo exitoso confirma que
    ``tenacity`` reintenta de verdad (no solo falla al primer intento) y
    que la llamada se recupera sin llegar a agotar los 3 intentos.

    Nota: este test espera de verdad ~2s (1 espera de ``wait_fixed(2)``
    para el reintento); es lento a proposito, no es un flake.
    """
    mock_v2c_http.get(
        REALTIME_DATA_URL,
        exception=client_exceptions.ServerTimeoutError("timed out"),
    )
    mock_v2c_http.get(REALTIME_DATA_URL, payload=realtime_data)
    coordinator = _make_coordinator(hass)
    session = async_get_clientsession(hass)

    result = await coordinator._async_get_json(session, REALTIME_DATA_URL)

    assert result == realtime_data


# ---------------------------------------------------------------------------
# arreglar_json_invalido
# ---------------------------------------------------------------------------


def test_arreglar_json_invalido_delegates_to_repair_v2c_json():
    """Es un wrapper de ``json_repair.repair_v2c_json``: mismo resultado
    para el mismo caso de reparacion ya cubierto en
    ``tests/test_json_repair.py`` (duplicado de ``FirmwareVersion``)."""
    malformed = (
        '{"FirmwareVersion":"1.6.12","FirmwareVersion":"1.6.14",'
        '"ChargePower":50}'
    )

    result = arreglar_json_invalido(malformed)

    assert result["FirmwareVersion"] == "1.6.14"
    assert result["ChargePower"] == 50


def test_arreglar_json_invalido_wraps_unrepairable_json_as_update_failed(
    caplog: pytest.LogCaptureFixture,
):
    """A diferencia de ``repair_v2c_json`` (que propaga
    ``json.JSONDecodeError``), el wrapper del coordinator lo convierte en
    ``UpdateFailed`` y loggea un error accionable, para que
    ``_async_get_json``/``_async_update_data`` lo traten de forma
    consistente con el resto de fallos de conexion."""
    unrepairable = "{not even close to json"

    with caplog.at_level(logging.ERROR):
        with pytest.raises(UpdateFailed):
            arreglar_json_invalido(unrepairable)

    assert "Error al parsear JSON" in caplog.text
