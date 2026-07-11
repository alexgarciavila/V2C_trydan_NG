"""Tests para custom_components/v2c_trydan/json_repair.py.

``json_repair.py`` es un modulo puro (sin dependencias de Home Assistant),
por eso sirve de ejemplo minimo de patron de test simple (AAA, sin fixtures
de ``hass``) para el resto de modulos que se testearan en paralelo.
"""
import json

import pytest

from custom_components.v2c_trydan.json_repair import repair_v2c_json


def test_repair_v2c_json_parses_valid_json_unchanged():
    """Un JSON ya valido se parsea tal cual."""
    valid_json = json.dumps({"ChargePower": 100, "Intensity": 16})

    result = repair_v2c_json(valid_json)

    assert result == {"ChargePower": 100, "Intensity": 16}


def test_repair_v2c_json_preserves_already_valid_ready_state_field():
    """REGRESION (bug P3-A corregido): un JSON YA VALIDO que contiene
    ``ReadyState`` tras otro campo con su coma correcta NO debe corromperse.

    Antes del fix, ``repair_v2c_json`` insertaba una coma antes de
    ``"ReadyState":`` de forma INCONDICIONAL (``str.replace``), duplicando la
    coma existente (``...,,"ReadyState"...``) y provocando un
    ``json.JSONDecodeError`` sobre un JSON que originalmente era valido.

    La insercion de coma ahora es condicional: solo se aplica cuando el campo
    no tiene separador previo (el patron real del firmware), preservando el
    JSON valido. ``json.dumps`` emite un espacio tras la coma, por lo que este
    caso tambien cubre que la deteccion ignora el whitespace intermedio.
    """
    already_valid = json.dumps({"ChargePower": 100, "ReadyState": 3})

    result = repair_v2c_json(already_valid)

    assert result == {"ChargePower": 100, "ReadyState": 3}


def test_repair_v2c_json_preserves_valid_compact_ready_state_field():
    """Variante compacta sin espacio tras la coma: tampoco debe corromperse."""
    already_valid = '{"ChargePower":100,"ReadyState":3}'

    result = repair_v2c_json(already_valid)

    assert result == {"ChargePower": 100, "ReadyState": 3}


def test_repair_v2c_json_preserves_ready_state_at_object_start():
    """``ReadyState`` como primer campo (precedido de ``{``) es valido sin
    coma y no debe recibir una coma espuria."""
    already_valid = '{"ReadyState":3,"ChargePower":100}'

    result = repair_v2c_json(already_valid)

    assert result == {"ReadyState": 3, "ChargePower": 100}


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
