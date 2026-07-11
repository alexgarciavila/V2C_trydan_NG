"""Tests para custom_components/v2c_trydan/json_repair.py.

``json_repair.py`` es un modulo puro (sin dependencias de Home Assistant),
por eso sirve de ejemplo minimo de patron de test simple (AAA, sin fixtures
de ``hass``) para el resto de modulos que se testearan en paralelo.
"""
import json

import pytest

from custom_components.v2c_trydan.json_repair import repair_v2c_json


def test_repair_v2c_json_parses_valid_json_unchanged():
    """Un JSON ya valido (sin el campo ReadyState) se parsea tal cual.

    Nota: se evita deliberadamente incluir ``ReadyState`` en este caso de
    valido "de verdad" porque revela una fragilidad conocida de
    ``repair_v2c_json`` — ver
    ``test_repair_v2c_json_corrupts_already_valid_ready_state_field`` mas
    abajo, reportada como hallazgo y no corregida aqui (test-agent no
    modifica codigo productivo).
    """
    valid_json = json.dumps({"ChargePower": 100, "Intensity": 16})

    result = repair_v2c_json(valid_json)

    assert result == {"ChargePower": 100, "Intensity": 16}


def test_repair_v2c_json_corrupts_already_valid_ready_state_field():
    """HALLAZGO (fragilidad, no corregida por test-agent): ``repair_v2c_json``
    inserta una coma antes de ``"ReadyState":`` de forma INCONDICIONAL,
    incluso si el JSON de entrada ya es valido y ya tiene la coma correcta.
    Esto rompe un JSON perfectamente valido que contenga ``ReadyState``
    despues de otro campo con coma.

    En el flujo real (``coordinator.arreglar_json_invalido``) esto no se
    dispara porque ``repair_v2c_json`` solo se invoca tras un
    ``json.JSONDecodeError`` del parseo inicial; pero la funcion es publica
    y no es idempotente/segura para JSON ya valido, lo cual es fragil de
    cara a llamadas futuras o cambios de firmware. Este test documenta el
    comportamiento ACTUAL (no el deseado) para detectar cualquier cambio de
    comportamiento como regresion, y sirve de evidencia para que
    dev-agent/bugfix-agent decidan si conviene hacer la insercion de coma
    condicional (solo si no hay ya una coma antes de ``"ReadyState":``).
    """
    already_valid = json.dumps({"ChargePower": 100, "ReadyState": 3})

    with pytest.raises(json.JSONDecodeError):
        repair_v2c_json(already_valid)


def test_repair_v2c_json_removes_duplicate_firmware_version():
    """Elimina duplicados de FirmwareVersion y conserva el ultimo valor."""
    malformed = (
        '{"FirmwareVersion":"1.6.12","FirmwareVersion":"1.6.14",'
        '"ChargePower":50}'
    )

    result = repair_v2c_json(malformed)

    assert result["FirmwareVersion"] == "1.6.14"
    assert result["ChargePower"] == 50


def test_repair_v2c_json_quotes_unquoted_1_6_13_version():
    """La version de firmware 1.6.13 llega sin comillas y hay que arreglarla."""
    malformed = '{"FirmwareVersion":1.6.13,"ChargePower":50}'

    result = repair_v2c_json(malformed)

    assert result["FirmwareVersion"] == "1.6.13"
    assert result["ChargePower"] == 50


def test_repair_v2c_json_inserts_missing_comma_before_ready_state():
    """Repara la coma ausente antes del campo ReadyState."""
    malformed = '{"ChargePower":50"ReadyState":3}'

    result = repair_v2c_json(malformed)

    assert result["ChargePower"] == 50
    assert result["ReadyState"] == 3


def test_repair_v2c_json_raises_json_decode_error_when_unrepairable():
    """Si el JSON sigue siendo invalido tras los arreglos, propaga el error
    para que la capa que llama (coordinator) lo convierta en ``UpdateFailed``.
    """
    unrepairable = "{not even close to json"

    with pytest.raises(json.JSONDecodeError):
        repair_v2c_json(unrepairable)
