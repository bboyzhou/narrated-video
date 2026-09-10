"""Deterministic media layers and offline catalog lookup; no network or packages."""
import argparse
import json
import math
from pathlib import Path


def require(ok, message):
    if not ok:
        raise ValueError(message)


def catalog(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    require(data.get('version') == 1 and isinstance(data.get('assets'), list), 'Invalid asset catalog')
    entries = {}
    for item in data['assets']:
        require(isinstance(item, dict), 'Catalog entry must be an object')
        ident = item.get('id')
        require(isinstance(ident, str) and ident and ident not in entries, 'Invalid/duplicate catalog ID')
        require(item.get('type') in ('image', 'video'), 'Catalog type must be image/video')
        require(all(isinstance(item.get(k), str) and item[k].strip() for k in ('path', 'source', 'license')),
                'Catalog entry needs path, source and license')
        asset = (path.parent / item['path']).resolve()
        require(asset.is_relative_to(path.parent), 'Catalog asset must stay inside its directory')
        entries[ident] = {**item, 'path': str(asset)}
    return entries


def resolve_asset(root, config, value):
    if isinstance(value, Path):
        value = str(value)
    require(isinstance(value, str) and value, 'Asset must be a nonempty path or library:ID')
    if value.startswith('library:'):
        location = config.get('asset_library')
        require(isinstance(location, str) and location, 'library: requires asset_library catalog path')
        entries = catalog(Path(root) / location)
        ident = value[len('library:'):]
        require(ident in entries, 'Unknown library asset: ' + ident)
        return Path(entries[ident]['path']), entries[ident]
    require('://' not in value, 'Download remote assets locally before rendering')
    return (Path(root) / value).resolve(), {}


def number(value, label, low, high):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
            label + f' must be finite in {low}..{high}')


def validate_media(item):
    require(item.get('type') in ('image', 'video'), 'Media type must be image/video')
    require(isinstance(item.get('asset'), str) and item['asset'], 'Media needs asset')
    number(item.get('source_start', 0), 'source_start', 0, 21600)
    require(type(item.get('loop', False)) is bool, 'loop must be boolean')
    if item['type'] == 'image':
        require(not item.get('source_start') and not item.get('loop'), 'source_start/loop apply only to video')


def validate_layers(shot, duration=None):
    validate_media(shot)
    layers = shot.get('layers', [])
    require(isinstance(layers, list) and len(layers) <= 16, 'layers must be a list of at most 16 items')
    ids = set()
    for layer in layers:
        require(isinstance(layer, dict), 'Layer must be an object')
        ident = layer.get('id')
        require(isinstance(ident, str) and ident and ident not in ids, 'Invalid/duplicate layer ID')
        ids.add(ident)
        validate_media(layer)
        number(layer.get('start'), 'layer.start', 0, 21600)
        number(layer.get('end'), 'layer.end', 0, 21600)
        require(layer['end'] > layer['start'], 'Layer end must follow start')
        if duration is not None:
            require(layer['end'] <= duration + 1e-8, 'Layer exceeds actual narration duration: ' + ident)
        for key in ('width', 'height'):
            number(layer.get(key, .3), 'layer.' + key, .01, 2)
        require(layer.get('easing', 'smoothstep') in ('linear', 'smoothstep'), 'Invalid layer easing')
        frames = layer.get('keyframes')
        require(isinstance(frames, list) and 1 <= len(frames) <= 32, 'Need 1..32 keyframes')
        previous = -1
        for frame in frames:
            require(isinstance(frame, dict), 'Keyframe must be an object')
            number(frame.get('time'), 'keyframe.time', 0, layer['end'] - layer['start'])
            require(frame['time'] > previous, 'Keyframe times must increase strictly')
            previous = frame['time']
            for key, low, high in (('x', -2, 3), ('y', -2, 3), ('scale', .05, 4),
                                  ('rotation', -3600, 3600), ('opacity', 0, 1)):
                number(frame.get(key), 'keyframe.' + key, low, high)
        require(frames[0]['time'] == 0, 'First keyframe time must be zero')


def expression(layer, key, clock='t'):
    frames = layer['keyframes']
    result = str(frames[-1][key])
    for a, b in reversed(list(zip(frames, frames[1:]))):
        u = f'clip(({clock}-{a["time"]})/{b["time"]-a["time"]},0,1)'
        if layer.get('easing', 'smoothstep') == 'smoothstep':
            u = f'({u})*({u})*(3-2*({u}))'
        value = f'{a[key]}+({b[key]-a[key]})*({u})'
        result = f'if(lt({clock},{b["time"]}),{value},{result})'
    return result


def media_input(item, path, fps):
    if item['type'] == 'image':
        return ['-loop', '1', '-framerate', str(fps), '-i', path]
    args = ['-stream_loop', '-1'] if item.get('loop', False) else []
    return args + ['-ss', item.get('source_start', 0), '-i', path]


def render_args(shot, path_for, width, height, fps, frames, base_filter):
    """Return video-only args. Layer coordinates refer to output canvas centers."""
    duration = frames / fps
    args = ['-filter_complex_threads', '1'] + media_input(shot, path_for(shot['asset']), fps)
    if shot['type'] == 'video':
        base_filter = (f'scale={width}:{height}:force_original_aspect_ratio=increase,'
                       f'crop={width}:{height},setsar=1')
    filters = [f'[0:v]setpts=PTS-STARTPTS,fps={fps},tpad=stop_mode=clone:stop_duration={duration},'
               f'trim=duration={duration},{base_filter},format=rgba[base0]']
    for i, layer in enumerate(shot.get('layers', []), 1):
        args += media_input(layer, path_for(layer['asset']), fps)
        length = layer['end'] - layer['start']
        w, h = max(2, round(width * layer.get('width', .3))), max(2, round(height * layer.get('height', .3)))
        scale = expression(layer, 'scale')
        rotation = expression(layer, 'rotation')
        opacity = expression(layer, 'opacity', 'T')
        # Constant square bounds preserve the center through rotation and scaling.
        side = math.ceil(math.hypot(w, h) * max(f['scale'] for f in layer['keyframes'])) + 4
        require(side <= 8192, 'Layer canvas exceeds 8192 pixels; reduce size/scale')
        filters.append(
            f'[{i}:v]setpts=PTS-STARTPTS,fps={fps},tpad=stop_mode=clone:stop_duration={length},'
            f'trim=duration={length},format=rgba,scale={w}:{h}:force_original_aspect_ratio=decrease,'
            f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black@0,setsar=1,'
            f"scale=w='{w}*({scale})':h='{h}*({scale})':eval=frame,"
            f"rotate=angle='({rotation})*PI/180':ow={side}:oh={side}:c=none,"
            f"format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*({opacity})',"
            f"setpts=PTS-STARTPTS+{layer['start']}/TB[layer{i}]")
        x = expression(layer, 'x', f'(t-{layer["start"]})')
        y = expression(layer, 'y', f'(t-{layer["start"]})')
        filters.append(f"[base{i-1}][layer{i}]overlay=x='W*({x})-w/2':y='H*({y})-h/2':"
                       f"enable='gte(t,{layer['start']})*lt(t,{layer['end']})':"
                       f'eof_action=pass:repeatlast=0:format=auto[base{i}]')
    filters.append(f'[base{len(shot.get("layers", []))}]format=yuv420p[v]')
    return args + ['-filter_complex', ';'.join(filters), '-map', '[v]', '-frames:v', frames,
                   '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Search an offline asset catalog (read-only)')
    parser.add_argument('catalog')
    parser.add_argument('--query', default='')
    options = parser.parse_args()
    result = [dict(item, available=Path(item['path']).is_file()) for item in catalog(options.catalog).values()
              if options.query.casefold() in json.dumps(item, ensure_ascii=False).casefold()]
    print(json.dumps(result, ensure_ascii=False, indent=2))
