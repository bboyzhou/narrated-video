"""Portable, best-effort hardware discovery used by provider planners."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_hardware(value=None):
    value = value if isinstance(value, dict) else {}
    gpus = value.get('gpus') if isinstance(value.get('gpus'), list) else []
    normalized = []
    for gpu in gpus:
        if not isinstance(gpu, dict):
            continue
        normalized.append({
            'name': str(gpu.get('name') or 'unknown'),
            'vram_gib': round(_number(gpu.get('vram_gib')), 2),
            'compute_capability': str(gpu.get('compute_capability') or ''),
            'supports_fp16': bool(gpu.get('supports_fp16', True)),
            'supports_bf16': bool(gpu.get('supports_bf16', False)),
        })
    return {
        'gpu_count': len(normalized),
        'gpus': normalized,
        'ram_available_gib': round(_number(value.get('ram_available_gib')), 2),
        'software': value.get('software') if isinstance(value.get('software'), dict) else {},
        'detected': bool(value.get('detected', normalized)),
    }


def detect_hardware():
    """Detect without importing torch or requiring an ML environment."""
    gpus = []
    nvidia_smi = shutil.which('nvidia-smi')
    if nvidia_smi:
        command = [nvidia_smi, '--query-gpu=name,memory.total,compute_cap',
                   '--format=csv,noheader,nounits']
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', check=False)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                fields = [part.strip() for part in line.split(',')]
                if len(fields) < 2:
                    continue
                capability = fields[2] if len(fields) > 2 else ''
                major = int(capability.split('.')[0]) if capability[:1].isdigit() else 0
                gpus.append({
                    'name': fields[0],
                    'vram_gib': round(_number(fields[1]) / 1024, 2),
                    'compute_capability': capability,
                    'supports_fp16': major >= 5,
                    'supports_bf16': major >= 8,
                })
    ram = 0.0
    try:
        if platform.system() == 'Windows':
            result = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 '[math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,2)'],
                capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)
            ram = _number(result.stdout.strip())
        elif hasattr(os, 'sysconf'):
            ram = os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') / 1024**3
    except (OSError, ValueError):
        pass
    return normalize_hardware({
        'gpus': gpus,
        'ram_available_gib': ram,
        'software': {'platform': platform.platform()},
        'detected': True,
    })
