"""Plan, resume and attach free-quota browser I2V jobs."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

from generators import file_sha256, normalize_provider
from import_generated_videos import probe, validate_decodable_video
from narrated_project import load_project
from .store import read_json, state_lease, write_json


PROVIDER = 'browser_i2v'
PLATFORMS = ('pixverse', 'jimeng', 'kling')
TERMINAL = {'ATTACHED', 'FAILED', 'CANCELLED', 'SUPERSEDED'}
REMOTE_ACTIVE = {'SUBMITTED', 'QUEUED', 'GENERATING'}
BLOCKED_OUTCOMES = {
    'login_required': 'LOGIN_REQUIRED', 'captcha_required': 'CAPTCHA_REQUIRED',
    'quota_exhausted': 'QUOTA_EXHAUSTED', 'cost_unconfirmed': 'COST_UNCONFIRMED',
    'provider_busy': 'PROVIDER_BUSY', 'ui_changed': 'UI_CHANGED',
    'download_unavailable': 'DOWNLOAD_UNAVAILABLE',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S%z')


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def runtime_type(value):
    return value.get('type') if isinstance(value, dict) else value


def is_browser_plan(plan, project):
    generation = plan.get('generation') or {}
    video = project.get('video_generation') or {}
    provider = generation.get('provider') or video.get('provider')
    runtime = generation.get('runtime') or video.get('runtime')
    return provider == PROVIDER or runtime_type(runtime) == 'browser'


def browser_settings(project):
    video = project.get('video_generation') or {}
    providers = video.get('providers') or {}
    raw = providers.get(PROVIDER) or {}
    require(isinstance(raw, dict), 'video_generation.providers.browser_i2v must be an object')
    platforms = raw.get('platforms', list(PLATFORMS))
    require(isinstance(platforms, list) and platforms,
            'browser_i2v.platforms must be a nonempty list')
    require(len(set(platforms)) == len(platforms) and all(p in PLATFORMS for p in platforms),
            'browser_i2v.platforms only supports: ' + ', '.join(PLATFORMS))
    require(raw.get('free_only', True) is True,
            'Browser I2V currently requires free_only=true; paid balance is never authorized implicitly')
    return {
        'platforms': platforms, 'free_only': True,
        'quota_max_age_seconds': int(raw.get('quota_max_age_seconds', 600)),
        'query_interval_seconds': int(raw.get('query_interval_seconds', 1800)),
        'max_attempts': int(raw.get('max_attempts', 2)),
    }


def browser_request_for_plan(plan, project, project_root):
    require(plan.get('asset_strategy') == 'generated_video',
            plan.get('id', '?') + ': browser I2V requires asset_strategy=generated_video')
    require(is_browser_plan(plan, project), plan.get('id', '?') + ': not a browser I2V shot')
    generation = plan.get('generation') or {}
    source_value = plan.get('source_image')
    require(isinstance(source_value, str) and source_value,
            plan.get('id', '?') + ': source_image is required')
    source = Path(source_value)
    if not source.is_absolute():
        source = (Path(project_root) / source).resolve()
    require(source.is_file(), plan.get('id', '?') + ': source image missing: ' + str(source))
    duration = generation.get('target_duration_sec')
    require(type(duration) in (int, float) and 1 <= duration <= 30,
            plan.get('id', '?') + ': target_duration_sec must be 1..30')
    seed = generation.get('seed', 0)
    require(type(seed) is int and 0 <= seed <= 2**32 - 1,
            plan.get('id', '?') + ': seed must be an integer in 0..2^32-1')
    settings = browser_settings(project)
    request = {
        'version': 1, 'shot_id': plan['id'],
        'source_image': source_value, 'source_sha256': file_sha256(source),
        'prompt': plan.get('motion_prompt') or plan.get('prompt'),
        'negative_prompt': plan.get('negative_prompt', ''),
        'constraints': plan.get('motion_constraints') or [],
        'generation': {
            'target_duration_sec': float(duration), 'seed': seed,
            'aspect_ratio': generation.get('aspect_ratio'),
            'motion': generation.get('motion') or {},
        },
        'routing': {'platforms': settings['platforms'], 'free_only': True},
    }
    require(isinstance(request['prompt'], str) and request['prompt'].strip(),
            plan['id'] + ': browser I2V needs a motion prompt')
    request['digest'] = canonical_digest(request)
    return request


def _state_root(project_root):
    return Path(project_root) / '.narrated-video' / 'i2v'


def _state_path(project_root):
    return _state_root(project_root) / 'tasks.json'


def _empty_state(project_path):
    return {'version': 1, 'project': str(Path(project_path).resolve()),
            'tasks': {}, 'active_by_shot': {}, 'actions': {}}


def _load_state(project_path):
    state = read_json(_state_path(Path(project_path).parent), _empty_state(project_path))
    require(state.get('version') == 1, 'Unsupported browser I2V task-state version')
    require(Path(state.get('project', '')).resolve() == Path(project_path).resolve(),
            'Browser I2V task state belongs to another project')
    return state


def _save_state(project_path, state):
    write_json(_state_path(Path(project_path).parent), state)


def plan_tasks(project, stage):
    selected = {shot['id'] for shot in project.selected(stage)}
    settings = browser_settings(project.c)
    created, reused = [], []
    root = _state_root(project.root)
    with state_lease(root):
        state = _load_state(project.path)
        for shot_id, plan in project.storyboard_shots.items():
            if shot_id not in selected or plan.get('asset_strategy') != 'generated_video' or not is_browser_plan(plan, project.c):
                continue
            request = browser_request_for_plan(plan, project.c, project.root)
            task_id = 'BI2V-' + shot_id + '-' + request['digest'][:12]
            previous_id = state['active_by_shot'].get(shot_id)
            if previous_id and previous_id != task_id:
                previous = state['tasks'].get(previous_id)
                if previous and previous.get('state') not in TERMINAL:
                    previous['state'] = 'SUPERSEDED'
                    previous['updated_at'] = now()
            if task_id not in state['tasks']:
                state['tasks'][task_id] = {
                    'id': task_id, 'shot_id': shot_id, 'request': request,
                    'state': 'PLANNED', 'blocked_reason': None,
                    'platform': None, 'remote': {}, 'download': None,
                    'platform_failures': {},
                    'attempts': [], 'next_check_at': None,
                    'created_at': now(), 'updated_at': now(),
                    'max_attempts': settings['max_attempts'],
                    'query_interval_seconds': settings['query_interval_seconds'],
                }
                created.append(task_id)
            else:
                reused.append(task_id)
            state['active_by_shot'][shot_id] = task_id
        require(created or reused, 'No browser I2V shots selected')
        _save_state(project.path, state)
    return {'stage': stage, 'created': created, 'reused': reused,
            'state_file': str(_state_path(project.root))}


def _parse_time(value):
    if not value:
        return 0
    try:
        return time.mktime(time.strptime(value[:19], '%Y-%m-%dT%H:%M:%S'))
    except ValueError:
        return 0


def _provider_snapshot(root):
    return read_json(root / 'provider-status.json', {'version': 1, 'providers': {}})


def _eligible_platform(task, snapshot, settings):
    current = time.time()
    for name in task['request']['routing']['platforms']:
        if name in task.get('platform_failures', {}):
            continue
        row = (snapshot.get('providers') or {}).get(name) or {}
        age = current - _parse_time(row.get('checked_at'))
        if (row.get('available') is True and row.get('logged_in') is True and
                row.get('free_eligible') is True and row.get('cost_confirmed_zero') is True and
                age <= settings['quota_max_age_seconds']):
            return name
    return None


def _issue(state, task, kind, platform=None):
    existing = next((a for a in state['actions'].values()
                     if a.get('task_id') == task['id'] and a.get('status') == 'issued'), None)
    if existing:
        return existing
    number = len(task['attempts']) + sum(1 for a in state['actions'].values()
                                         if a.get('task_id') == task['id']) + 1
    action_id = task['id'] + '-' + kind.upper() + '-' + str(number)
    action = {
        'version': 1, 'id': action_id, 'task_id': task['id'], 'kind': kind,
        'platform': platform or task.get('platform'), 'status': 'issued',
        'issued_at': now(), 'request': copy.deepcopy(task['request']),
    }
    if kind in ('query', 'query_history'):
        action['remote'] = copy.deepcopy(task.get('remote') or {})
    state['actions'][action_id] = action
    return action


def _can_submit(task):
    if len(task.get('attempts') or []) < int(task.get('max_attempts', 2)):
        return True
    task['blocked_reason'] = 'MAX_ATTEMPTS_REACHED'
    task['updated_at'] = now()
    return False


def next_action(project_path):
    project_path = Path(project_path).resolve();root = _state_root(project_path.parent)
    with state_lease(root):
        state = _load_state(project_path);snapshot = _provider_snapshot(root)
        settings = None
        document = load_project(project_path);settings = browser_settings(document.legacy_view())
        for task_id in state['active_by_shot'].values():
            task = state['tasks'][task_id]
            if task['state'] in TERMINAL or task.get('blocked_reason'):
                continue
            outstanding = next((a for a in state['actions'].values()
                                if a.get('task_id') == task_id and a.get('status') == 'issued'), None)
            if outstanding:
                return outstanding
            if task['state'] == 'PLANNED':
                platform = _eligible_platform(task, snapshot, settings)
                remaining = [p for p in task['request']['routing']['platforms']
                             if p not in task.get('platform_failures', {})]
                if not remaining:
                    task['blocked_reason'] = 'NO_FREE_PROVIDER_AVAILABLE'
                    task['updated_at'] = now();_save_state(project_path, state)
                    continue
                if platform and not _can_submit(task):
                    _save_state(project_path, state)
                    continue
                action = (_issue(state, task, 'submit', platform) if platform else
                          _issue(state, task, 'inspect', remaining[0]))
            elif task['state'] == 'READY':
                platform = _eligible_platform(task, snapshot, settings)
                remaining = [p for p in task['request']['routing']['platforms']
                             if p not in task.get('platform_failures', {})]
                if not remaining:
                    task['blocked_reason'] = 'NO_FREE_PROVIDER_AVAILABLE'
                    task['updated_at'] = now();_save_state(project_path, state)
                    continue
                if platform and not _can_submit(task):
                    _save_state(project_path, state)
                    continue
                action = (_issue(state, task, 'submit', platform) if platform else
                          _issue(state, task, 'inspect', remaining[0]))
            elif task['state'] == 'SUBMISSION_UNKNOWN':
                action = _issue(state, task, 'query_history', task.get('platform'))
            elif task['state'] in REMOTE_ACTIVE:
                if task.get('next_check_at') and _parse_time(task['next_check_at']) > time.time():
                    continue
                action = _issue(state, task, 'query', task.get('platform'))
            elif task['state'] == 'COMPLETED':
                action = _issue(state, task, 'download', task.get('platform'))
            else:
                continue
            _save_state(project_path, state)
            request_dir = root / 'requests';write_json(request_dir / (action['id'] + '.json'), action)
            return action
        return {'version': 1, 'kind': 'none', 'reason': 'no_due_browser_action'}


def _future(seconds):
    return time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(time.time() + seconds))


def observe_action(project_path, observation_path):
    project_path = Path(project_path).resolve();root = _state_root(project_path.parent)
    observation = read_json(observation_path)
    require(isinstance(observation, dict), 'Observation must be a JSON object')
    action_id = observation.get('action_id');outcome = observation.get('outcome')
    require(isinstance(action_id, str) and isinstance(outcome, str),
            'Observation requires action_id and outcome')
    with state_lease(root):
        state = _load_state(project_path);action = state['actions'].get(action_id)
        require(action and action.get('status') == 'issued', 'Unknown or already observed browser action: ' + action_id)
        task = state['tasks'][action['task_id']]
        require(observation.get('platform', action.get('platform')) == action.get('platform'),
                'Observation platform does not match the issued action')
        action['status'] = 'observed';action['observed_at'] = now();action['outcome'] = outcome
        write_json(root / 'observations' / (action_id + '.json'), observation)
        if outcome in BLOCKED_OUTCOMES:
            reason = BLOCKED_OUTCOMES[outcome]
            task.setdefault('platform_failures', {})[action['platform']] = reason
            remaining = [p for p in task['request']['routing']['platforms']
                         if p not in task['platform_failures']]
            task['blocked_reason'] = None if remaining and action['kind'] in ('inspect', 'submit') else reason
            if remaining and action['kind'] in ('inspect', 'submit'):
                task['state'] = 'PLANNED'
        elif action['kind'] == 'inspect':
            require(outcome == 'available', 'Unsupported inspect outcome: ' + outcome)
            require(observation.get('logged_in') is True and observation.get('free_eligible') is True and
                    observation.get('cost_confirmed_zero') is True,
                    'available inspection must confirm login, free eligibility and zero cost')
            status = _provider_snapshot(root);status.setdefault('providers', {})[action['platform']] = {
                'available': True, 'logged_in': True, 'free_eligible': True,
                'cost_confirmed_zero': True, 'checked_at': now(),
                'model': observation.get('model'), 'quota_hint': observation.get('quota_hint'),
                'queue_hint': observation.get('queue_hint'),
            }
            write_json(root / 'provider-status.json', status)
            task['state'] = 'READY';task['platform'] = action['platform'];task['blocked_reason'] = None
        elif action['kind'] == 'submit':
            require(outcome in ('submitted', 'queued', 'generating', 'unknown'),
                    'Unsupported submit outcome: ' + outcome)
            task['platform'] = action['platform']
            task['attempts'].append({'platform': action['platform'], 'submitted_at': now(),
                                     'model': observation.get('model')})
            if outcome == 'unknown':
                task['state'] = 'SUBMISSION_UNKNOWN'
            else:
                require(observation.get('remote_task_id') or observation.get('task_url') or observation.get('visible_signature'),
                        'Submitted task needs a remote identifier, URL or visible signature')
                task['state'] = {'submitted': 'SUBMITTED', 'queued': 'QUEUED',
                                 'generating': 'GENERATING'}[outcome]
                task['remote'] = {key: observation[key] for key in
                                  ('remote_task_id', 'task_url', 'visible_signature') if observation.get(key)}
                task['next_check_at'] = _future(int(observation.get(
                    'retry_after_seconds', task.get('query_interval_seconds', 1800))))
        elif action['kind'] in ('query', 'query_history'):
            require(outcome in ('submitted', 'queued', 'generating', 'completed', 'failed', 'not_found'),
                    'Unsupported query outcome: ' + outcome)
            if outcome == 'not_found':
                task['state'] = 'SUBMISSION_UNKNOWN';task['blocked_reason'] = 'REMOTE_TASK_NOT_FOUND'
            elif outcome == 'failed':
                task['state'] = 'FAILED';task['failure'] = observation.get('reason', 'remote generation failed')
            else:
                if outcome in ('submitted', 'queued', 'generating'):
                    require(task.get('remote') or observation.get('remote_task_id') or observation.get('task_url'),
                            'Active remote task needs an identifier')
                task['state'] = outcome.upper()
                for key in ('remote_task_id', 'task_url', 'visible_signature'):
                    if observation.get(key):task.setdefault('remote', {})[key] = observation[key]
                task['next_check_at'] = (None if outcome == 'completed' else _future(int(
                    observation.get('retry_after_seconds', task.get('query_interval_seconds', 1800)))))
        elif action['kind'] == 'download':
            require(outcome == 'downloaded', 'Unsupported download outcome: ' + outcome)
            path = observation.get('path');require(isinstance(path, str) and Path(path).is_file(),
                                                             'Downloaded observation path is missing')
            task['state'] = 'DOWNLOADED';task['download'] = str(Path(path).resolve())
        else:
            raise ValueError('Unsupported browser action kind: ' + action['kind'])
        task['updated_at'] = now();_save_state(project_path, state)
        return {'task': task['id'], 'state': task['state'],
                'blocked_reason': task.get('blocked_reason')}


def status_report(project_path):
    state = _load_state(Path(project_path).resolve())
    rows=[]
    for task_id in state['active_by_shot'].values():
        task=state['tasks'][task_id]
        rows.append({key: task.get(key) for key in ('id','shot_id','state','blocked_reason','platform','remote','next_check_at')})
    return {'version': 1, 'tasks': rows, 'state_file': str(_state_path(Path(project_path).resolve().parent))}


def _requested_ratio(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*', value)
    if not match or float(match.group(2)) == 0:
        return None
    return float(match.group(1)) / float(match.group(2))


def sync_downloads(project_path, ffprobe=None, ffmpeg=None):
    project_path=Path(project_path).resolve();root=_state_root(project_path.parent)
    document=load_project(project_path);config=document.legacy_view();imported=[];failed=[]
    current_plans = {row.get('id'): row for row in document.storyboard_view().get('shots', [])}
    with state_lease(root):
        state=_load_state(project_path)
        for task_id in list(state['active_by_shot'].values()):
            task=state['tasks'][task_id]
            if task['state'] not in ('DOWNLOADED','VALIDATED'):continue
            source=Path(task.get('download') or '')
            try:
                require(source.is_file(),'download file is missing')
                current_plan = current_plans.get(task['shot_id'])
                require(current_plan is not None,
                        'current storyboard no longer contains this browser I2V shot')
                current_request = browser_request_for_plan(
                    current_plan, config, project_path.parent)
                require(current_request['digest'] == task['request']['digest'],
                        'current shot request changed after generation; run i2v-plan again')
                info=probe(source,ffprobe,ffmpeg);validate_decodable_video(source,ffmpeg)
                target_duration=float(task['request']['generation']['target_duration_sec'])
                require(info['duration'] >= max(1,target_duration*.6),
                        'downloaded video is materially shorter than requested')
                expected_ratio = _requested_ratio(
                    task['request']['generation'].get('aspect_ratio'))
                if expected_ratio is not None:
                    actual_ratio = float(info['width']) / float(info['height'])
                    require(abs(actual_ratio - expected_ratio) <= 0.08,
                            'downloaded video aspect ratio differs from the request')
                digest=task['request']['digest'];shot_id=task['shot_id']
                destination=project_path.parent/'assets'/'generated-video'/PROVIDER/digest
                destination.mkdir(parents=True,exist_ok=True);target=destination/(shot_id+'.mp4')
                partial=target.with_suffix('.mp4.partial');shutil.copyfile(source,partial);os.replace(partial,target)
                output_hash=file_sha256(target);relative=target.relative_to(project_path.parent).as_posix()
                generated={'provider':PROVIDER,'platform':task['platform'],'cache_key':digest,
                           'asset':relative,'sha256':output_hash,'runtime':'browser',
                           'profile':config.get('video_generation',{}).get('profile'),
                           'model':(task['attempts'][-1].get('model') if task['attempts'] else None),
                           'request_digest':digest,'imported_at':now(),**info}
                document.set_generated_video(shot_id,generated)
                index_path=project_path.parent/'.narrated-video'/'generated-video-index.json'
                index=read_json(index_path,{'version':1,'entries':{}});index.setdefault('entries',{})[digest]={'id':shot_id,**generated}
                write_json(index_path,index);task['state']='ATTACHED';task['updated_at']=now();imported.append({'id':shot_id,**generated})
            except (OSError,ValueError) as error:
                failed.append({'id':task['shot_id'],'error':str(error)})
        if document.source_format=='v1':document.save()
        else:
            legacy=document.legacy_raw
            for row in imported:
                for shot in legacy.get('shots',[]):
                    if shot.get('id')==row['id']:shot['generated_video']={k:v for k,v in row.items() if k!='id'}
            write_json(project_path,legacy)
        _save_state(project_path,state)
    report={'version':1,'provider':PROVIDER,'imported':imported,'failed':failed}
    write_json(root/'reports'/'sync.json',report);return report
