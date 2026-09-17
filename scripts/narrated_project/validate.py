"""Semantic validation that complements narrated-project-v1.schema.json."""

import re


ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')
PROFILES = {'smoke', 'fast', 'balanced', 'quality', 'max_quality'}
ADAPTERS = {'ffmpeg', 'remotion', 'openchatcut'}
LOW_LEVEL_I2V_FIELDS = {
    'dtype', 'resolution', 'frame_num', 'fps', 'steps', 'inference_steps',
    'attention', 'attention_backend', 'offload', 'teacache', 'world_size',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _object(value, label):
    require(isinstance(value, dict), label + ' must be an object')
    return value


def _array(value, label, allow_empty=False):
    require(isinstance(value, list) and (allow_empty or value),
            label + (' must be an array' if allow_empty else ' must be a nonempty array'))
    return value


def _text(value, label, allow_empty=False):
    require(isinstance(value, str) and (allow_empty or value.strip()),
            label + ' must be text')
    return value


def _ids(rows, label):
    values = []
    for index, row in enumerate(rows):
        _object(row, f'{label}[{index}]')
        value = _text(row.get('id'), f'{label}[{index}].id')
        require(ID_PATTERN.fullmatch(value), value + ': IDs must use ASCII letters, digits, _ or -')
        values.append(value)
    require(len(values) == len(set(values)), label + ' IDs must be unique')
    return values


def _reject_i2v_execution_fields(value, path='providers.i2v'):
    if isinstance(value, dict):
        for key, child in value.items():
            require(key not in LOW_LEVEL_I2V_FIELDS,
                    path + '.' + key + ' belongs in a generated RuntimePlan, not NarratedProject')
            _reject_i2v_execution_fields(child, path + '.' + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_i2v_execution_fields(child, f'{path}[{index}]')


def validate_project(data, stage='production'):
    """Validate the stable authoring contract and cross-reference invariants."""
    require(stage in ('draft', 'script', 'production'), 'Unknown validation stage')
    _object(data, 'project')
    require(data.get('kind') == 'NarratedProject', 'kind must be NarratedProject')
    require(data.get('version') == 1, 'Unsupported NarratedProject version')

    project = _object(data.get('project'), 'project')
    _text(project.get('id'), 'project.id')
    _text(project.get('title'), 'project.title')
    sources = _object(data.get('sources'), 'sources')
    _text(sources.get('script'), 'sources.script')
    creative = _object(data.get('creative'), 'creative')
    _object(creative.get('brief'), 'creative.brief')
    _object(creative.get('style'), 'creative.style')
    providers = _object(data.get('providers'), 'providers')
    _object(providers.get('image'), 'providers.image')
    tts = _object(providers.get('tts'), 'providers.tts')
    _text(tts.get('engine'), 'providers.tts.engine')
    i2v = _object(providers.get('i2v'), 'providers.i2v')
    require(i2v.get('profile', 'balanced') in PROFILES,
            'providers.i2v.profile must express only speed/quality/cost intent')
    _reject_i2v_execution_fields(i2v.get('providers', {}))
    runtime = i2v.get('runtime')
    runtime_name = runtime.get('type') if isinstance(runtime, dict) else runtime
    if i2v.get('provider') == 'browser_i2v' or runtime_name == 'browser':
        require(i2v.get('provider') == 'browser_i2v' and runtime_name == 'browser',
                'Browser I2V requires provider=browser_i2v and runtime.type=browser')
        browser = _object((i2v.get('providers') or {}).get('browser_i2v'),
                          'providers.i2v.providers.browser_i2v')
        platforms = _array(browser.get('platforms'),
                           'providers.i2v.providers.browser_i2v.platforms')
        supported = {'pixverse', 'jimeng', 'kling'}
        require(len(platforms) == len(set(platforms)) and all(p in supported for p in platforms),
                'browser_i2v.platforms contains duplicates or unsupported platforms')
        require(browser.get('free_only') is True,
                'browser_i2v.free_only must be true; paid usage requires a separate explicit workflow')

    render = _object(data.get('render'), 'render')
    target = _object(render.get('target'), 'render.target')
    require(target.get('adapter') in ADAPTERS, 'render.target.adapter is unsupported')
    fallback = target.get('fallback', 'none')
    require(fallback in ADAPTERS | {'none'}, 'render.target.fallback is unsupported')
    output = _object(render.get('output'), 'render.output')
    for key in ('width', 'height'):
        value = output.get(key)
        require(type(value) is int and value >= 64 and value % 2 == 0,
                'render.output.' + key + ' must be an even integer >= 64')
    require(type(output.get('fps')) is int and 1 <= output['fps'] <= 60,
            'render.output.fps must be an integer in 1..60')

    timeline = _object(data.get('timeline'), 'timeline')
    narration = _array(timeline.get('narration'), 'timeline.narration', allow_empty=stage == 'draft')
    narration_ids = _ids(narration, 'timeline.narration')
    for row in narration:
        _text(row.get('text'), row.get('id', '?') + '.text')
    if stage == 'draft':
        _array(timeline.get('shots'), 'timeline.shots', allow_empty=True)
        _array(timeline.get('music'), 'timeline.music', allow_empty=True)
        _object(timeline.get('demo'), 'timeline.demo')
        return data

    require(narration_ids, 'timeline.narration must be filled before script approval')
    if stage == 'script':
        return data

    shots = _array(timeline.get('shots'), 'timeline.shots')
    shot_ids = _ids(shots, 'timeline.shots')
    covered = []
    for shot in shots:
        sid = shot['id']
        require(shot.get('type') in ('image', 'video'), sid + '.type must be image or video')
        _text(shot.get('asset'), sid + '.asset')
        narration_refs = _array(shot.get('narration'), sid + '.narration')
        require(all(ref in narration_ids for ref in narration_refs), sid + ' references unknown narration')
        covered.extend(narration_refs)
        _text(shot.get('purpose'), sid + '.purpose')
        require(type(shot.get('estimated_duration_seconds')) in (int, float) and
                shot['estimated_duration_seconds'] > 0,
                sid + '.estimated_duration_seconds must be positive')
        visual = _object(shot.get('visual'), sid + '.visual')
        for key in ('subject', 'action', 'setting', 'shot_size', 'composition', 'lighting_color'):
            _text(visual.get(key), sid + '.visual.' + key)
        _array(shot.get('continuity'), sid + '.continuity')
        _text(shot.get('prompt'), sid + '.prompt')
        _text(shot.get('negative_prompt'), sid + '.negative_prompt')
        require(shot.get('asset_strategy') in
                ('user', 'generate', 'licensed', 'mixed', 'generated_video'),
                sid + '.asset_strategy is unsupported')
        require(shot.get('motion', 'push') in
                ('still', 'push', 'pull', 'pan-left', 'pan-right'),
                sid + '.motion is unsupported')
        transition = shot.get('transition_seconds', 0.3)
        require(type(transition) in (int, float) and 0 <= transition <= 2,
                sid + '.transition_seconds must be 0..2')
        if shot.get('type') == 'video':
            require(shot.get('motion', 'still') == 'still', sid + ': video shots require motion=still')
        if shot.get('asset_strategy') == 'generated_video':
            _text(shot.get('source_image'), sid + '.source_image')
            _text(shot.get('motion_prompt'), sid + '.motion_prompt')
            _array(shot.get('motion_constraints'), sid + '.motion_constraints')
            _object(shot.get('generation'), sid + '.generation')
    require(covered == narration_ids,
            'timeline.shots must cover narration once, in order, without gaps')

    demo = _object(timeline.get('demo'), 'timeline.demo')
    demo_ids = _array(demo.get('shots'), 'timeline.demo.shots')
    require(all(value in shot_ids for value in demo_ids), 'timeline.demo references unknown shots')
    positions = [shot_ids.index(value) for value in demo_ids]
    require(positions == list(range(positions[0], positions[0] + len(positions))),
            'timeline.demo.shots must be consecutive and ordered')
    _text(demo.get('selection_reason'), 'timeline.demo.selection_reason')
    _array(demo.get('validation_goals'), 'timeline.demo.validation_goals')
    _array(timeline.get('music'), 'timeline.music', allow_empty=True)
    return data
