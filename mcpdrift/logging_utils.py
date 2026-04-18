"""Lightweight logging helper for the mcpdrift package.

Library code should call :func:`get_logger` to obtain a stdlib
``logging.Logger``. The package's root logger is configured with a
``NullHandler`` so importing the library never produces console output;
applications opt in by configuring their own handlers.
"""

from __future__ import annotations

import logging

_ROOT_NAME = "mcpdrift"

# Attach a NullHandler once so "No handlers could be found" warnings are
# suppressed and no output is emitted unless the host application configures
# logging explicitly.
logging.getLogger(_ROOT_NAME).addHandler(logging.NullHandler())


def get_logger(name: str) -> logging.Logger:
    """Return a logger namespaced under ``mcpdrift``.

    Parameters
    ----------
    name : str
        Either a fully-qualified module name (``mcpdrift.foo.bar``) or a
        bare suffix (``foo.bar``). The result is always anchored under
        the ``mcpdrift`` namespace.
    """
    if name == _ROOT_NAME or name.startswith(_ROOT_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_NAME}.{name}")
