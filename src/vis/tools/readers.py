"""Pluggable reader providers.

The OCR/OCV/barcode *reading* is deliberately behind a provider seam so a
commercial SDK (Cognex, MVTec, a licensed OCV engine, etc.) can be dropped in
without changing the inspection tools, recipes, or HMI. A text provider is a
callable ``(image, config) -> (text, confidence)``; a code provider is
``(image, config) -> DecodedCode | None``.

Selection order (per call): tool config ``reader`` → env ``VIS_TEXT_READER`` /
``VIS_CODE_READER`` → ``"builtin"``.

Integrating a paid library is then just::

    from vis.tools.readers import register_text_reader
    register_text_reader("acme", lambda img, cfg: acme_sdk.read(img))
    # then set VIS_TEXT_READER=acme  (or recipe/tool config reader="acme")
"""

from __future__ import annotations

import os

_TEXT_READERS: dict = {}
_CODE_READERS: dict = {}


def register_text_reader(name: str, fn) -> None:
    _TEXT_READERS[name] = fn


def register_code_reader(name: str, fn) -> None:
    _CODE_READERS[name] = fn


def available_text_readers() -> list[str]:
    return sorted(_TEXT_READERS)


def available_code_readers() -> list[str]:
    return sorted(_CODE_READERS)


def get_text_reader(name: str | None = None):
    name = name or os.environ.get("VIS_TEXT_READER") or "builtin"
    return _TEXT_READERS.get(name) or _TEXT_READERS["builtin"]


def get_code_reader(name: str | None = None):
    name = name or os.environ.get("VIS_CODE_READER") or "builtin"
    return _CODE_READERS.get(name) or _CODE_READERS["builtin"]


def _builtin_text(image, config):
    from .ocr import recognize

    return recognize(image)


def _builtin_code(image, config):
    from .code_verify import decode_first

    return decode_first(image)


register_text_reader("builtin", _builtin_text)
register_code_reader("builtin", _builtin_code)
