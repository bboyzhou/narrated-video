"""Planning primitives for generated-video providers."""

from .hardware import detect_hardware, normalize_hardware
from .profile import PROFILES, get_profile

__all__ = ['PROFILES', 'detect_hardware', 'get_profile', 'normalize_hardware']
