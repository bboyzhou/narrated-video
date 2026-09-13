"""Model- and hardware-neutral I2V generation intents."""

PROFILES = {
    'smoke': {
        'speed_priority': 10, 'quality_priority': 0, 'cost_priority': 10,
        'max_generated_seconds': 2,
    },
    'fast': {
        'speed_priority': 8, 'quality_priority': 3, 'cost_priority': 8,
        'max_generated_seconds': 4,
    },
    'balanced': {
        'speed_priority': 6, 'quality_priority': 6, 'cost_priority': 6,
        'max_generated_seconds': 4,
    },
    'quality': {
        'speed_priority': 3, 'quality_priority': 9, 'cost_priority': 3,
        'max_generated_seconds': 6,
    },
    'max_quality': {
        'speed_priority': 1, 'quality_priority': 10, 'cost_priority': 1,
        'max_generated_seconds': 8,
    },
}


def get_profile(name):
    if name not in PROFILES:
        raise ValueError('Unknown I2V profile: ' + str(name) +
                         '; available: ' + ', '.join(PROFILES))
    return {'name': name, **PROFILES[name]}
