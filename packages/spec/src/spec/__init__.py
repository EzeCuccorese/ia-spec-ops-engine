"""Spec personal agent workflow."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("spec")
except PackageNotFoundError:
    # Imported from a source tree without metadata: pyproject.toml stays the only release number.
    __version__ = "0+unknown"
