"""Compatibility launcher for the dashboard now branded as ReEDS-Proxy."""

from pathlib import Path


_APP = Path(__file__).with_name("reeds_proxy.py")
exec(compile(_APP.read_bytes(), str(_APP), "exec"))
