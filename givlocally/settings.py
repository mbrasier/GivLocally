"""Persistent file-based settings for GivLocally.

Settings are stored as TOML at:
  Windows:  %APPDATA%\\givlocally\\config.toml
  macOS:    ~/Library/Application Support/givlocally/config.toml
  Linux:    ~/.config/givlocally/config.toml
"""

from __future__ import annotations

import pathlib
from typing import Any

import click

try:
    import tomllib  # stdlib in Python 3.11+
except ImportError:
    import tomli as tomllib  # backport for 3.10


# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "connection": {
        "host": "192.168.0.100",
        "port": 8899,
        "batteries": 1,
        "inv_type": "",
    },
    "solar": {
        "capacity_kwp": 0.0,
        "tilt_deg": 35,
        "azimuth_deg": 180,
        "latitude": 0.0,
        "longitude": 0.0,
        "efficiency": 0.80,
    },
}


# ── Path ─────────────────────────────────────────────────────────────────────

def config_path() -> pathlib.Path:
    return pathlib.Path(click.get_app_dir("givlocally")) / "config.toml"


# ── Load / save ───────────────────────────────────────────────────────────────

def load() -> dict[str, Any]:
    """Load settings from disk, returning an empty dict if the file doesn't exist."""
    path = config_path()
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def save(data: dict[str, Any]) -> pathlib.Path:
    """Write settings to disk as TOML and return the path written to."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for section, values in data.items():
        lines.append(f"[{section}]")
        for key, val in values.items():
            if isinstance(val, str):
                lines.append(f'{key} = "{val}"')
            elif isinstance(val, float):
                lines.append(f"{key} = {val:.4f}")
            elif isinstance(val, bool):
                lines.append(f"{key} = {'true' if val else 'false'}")
            else:
                lines.append(f"{key} = {val}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ── Callable defaults for Click options ───────────────────────────────────────
# Pass these as `default=` to a @click.option. Click calls them at runtime so
# the settings file is read after the process starts, not at import time.

def _conn(key: str):
    fallback = DEFAULTS["connection"][key]
    def _default():
        return load().get("connection", {}).get(key, fallback)
    _default.__name__ = f"default_{key}"
    return _default

default_host      = _conn("host")
default_port      = _conn("port")
default_batteries = _conn("batteries")
default_inv_type  = _conn("inv_type")
