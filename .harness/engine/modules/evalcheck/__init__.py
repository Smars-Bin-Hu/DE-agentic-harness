"""Eval: fixed scenarios and `cli eval check`, which judges a finished run from its session log and request folder."""

from .handler import NAME, doctor, handle

__all__ = ["NAME", "doctor", "handle"]
