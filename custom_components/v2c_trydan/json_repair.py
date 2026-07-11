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
    - Inserts the missing comma before ``ReadyState`` only when no separator is
      already present (so it never corrupts already-valid JSON).

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

    # Insert the missing comma before "ReadyState" ONLY when a separator is
    # actually absent. The real firmware concatenates the field with no
    # separator (e.g. `...50"ReadyState":...`), so the char right before the
    # field is the last char of the previous value. We must NOT add a comma
    # when a valid separator already precedes the field -- a comma (possibly
    # followed by whitespace, as json.dumps emits) or an opening brace at the
    # start of the object -- otherwise a valid JSON would be corrupted into
    # `...,,"ReadyState"...` and json.loads would raise.
    json_str_arreglado = re.sub(
        r'([^\s,{])(\s*)"ReadyState":',
        r'\1\2,"ReadyState":',
        cadena,
    )

    return json.loads(json_str_arreglado)
