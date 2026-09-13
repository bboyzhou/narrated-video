"""Execution environments, intentionally independent from model providers."""

RUNTIMES = {
    'local': {'type': 'local', 'gpu': True, 'persistent_storage': True,
              'network': True, 'batch_job': False, 'interactive': True},
    'kaggle': {'type': 'remote_gpu', 'gpu': True, 'persistent_storage': False,
               'network': True, 'batch_job': True, 'interactive': True},
    'colab': {'type': 'remote_gpu', 'gpu': True, 'persistent_storage': False,
              'network': True, 'batch_job': True, 'interactive': True},
    'runpod': {'type': 'remote_gpu', 'gpu': True, 'persistent_storage': True,
               'network': True, 'batch_job': True, 'interactive': True},
    'remote_worker': {'type': 'remote_gpu', 'gpu': True, 'persistent_storage': None,
                      'network': None, 'batch_job': True, 'interactive': None},
    'cloud_api': {'type': 'api', 'gpu': False, 'persistent_storage': None,
                  'network': True, 'batch_job': True, 'interactive': False},
}


def runtime_capabilities(runtime_type):
    if runtime_type not in RUNTIMES:
        raise ValueError('Unknown I2V runtime: ' + str(runtime_type) +
                         '; available: auto, ' + ', '.join(RUNTIMES))
    return dict(RUNTIMES[runtime_type])


def resolve_runtime(value, default='local'):
    if isinstance(value, str):
        value = {'type': value}
    value = value if isinstance(value, dict) else {}
    requested_type = value.get('type', default)
    runtime_type = requested_type
    if runtime_type == 'auto':
        runtime_type = default
    capabilities = runtime_capabilities(runtime_type)
    hardware = value.get('hardware') if isinstance(value.get('hardware'), dict) else None
    overrides = value.get('overrides') if isinstance(value.get('overrides'), dict) else {}
    allowed = {'max_vram_gib', 'device'}
    unexpected = sorted(set(overrides) - allowed)
    if unexpected:
        raise ValueError('runtime.overrides only supports: ' + ', '.join(sorted(allowed)))
    return {'type': runtime_type, 'requested_type': requested_type,
            'capabilities': capabilities,
            'hardware': hardware, 'overrides': overrides}
