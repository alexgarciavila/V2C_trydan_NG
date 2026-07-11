"""Shared JSON repair helpers for V2C Trydan firmware responses.

The V2C Trydan firmware returns malformed JSON in some versions (duplicate
fields, unquoted version numbers, missing separators). This module centralises
the firmware-specific workarounds so every parsing path (coordinator polling
and the select entity update) applies exactly the same fixes.
"""
import json
import logging
import re

_LOGGER = logging.getLogger(__name__)


def repair_v2c_json(json_str: str) -> dict:
    """Repair malformed JSON returned by V2C Trydan firmware.

    Applies the known firmware-specific workarounds, in order:
    - Removes duplicate ``FirmwareVersion`` fields (keeps the last one).
    - Quotes unquoted version numbers (e.g. ``1.6.13``).
    - Inserts the missing comma before ``ReadyState``.

    Returns the parsed dict. Raises ``json.JSONDecodeError`` if the string
    still cannot be parsed after applying the workarounds, so callers can wrap
    the failure with their own error type (e.g. ``UpdateFailed``).
    """
    # Remove duplicate FirmwareVersion fields (keep the last one)
    firmware_pattern = r'"FirmwareVersion":"[^"]*",'
    matches = list(re.finditer(firmware_pattern, json_str))
    if len(matches) > 1:
        # Remove all but the last occurrence
        for match in matches[:-1]:
            json_str = json_str[:match.start()] + json_str[match.end():]

    # Fix version numbers without quotes
    cadena = json_str.replace("1.6.13", "\"1.6.13\"")
    json_str_arreglado = cadena.replace("\"ReadyState\":", ",\"ReadyState\":")

    return json.loads(json_str_arreglado)
