"""Adapter registry: renderer selection is data, never pipeline conditionals."""

import hashlib
import inspect
from pathlib import Path

from .ffmpeg import FFmpegAdapter
from .openchatcut import OpenChatCutAdapter
from .remotion import RemotionAdapter


_ADAPTERS = {
    adapter.capabilities.name: adapter
    for adapter in (FFmpegAdapter(), RemotionAdapter(), OpenChatCutAdapter())
}


def get_adapter(name):
    try:
        return _ADAPTERS[name]
    except KeyError as error:
        raise ValueError(
            'Unknown adapter: ' + str(name) + '; available: ' + ', '.join(sorted(_ADAPTERS))
        ) from error


def list_adapters():
    return {name: adapter.capabilities for name, adapter in _ADAPTERS.items()}


def adapter_identity(name):
    adapter = get_adapter(name)
    path = Path(inspect.getfile(adapter.__class__))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if name == 'remotion':
        from remotion_adapter import renderer_identity
        digest = hashlib.sha256((digest + renderer_identity()).encode()).hexdigest()
    return digest
