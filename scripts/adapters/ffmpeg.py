"""FFmpeg visual adapter consuming only RenderPlan fields plus execution services."""

import re
import shutil
from pathlib import Path

from composition import render_args, validate_layers
from .base import AdapterCapabilities, RenderAdapter


class FFmpegAdapter(RenderAdapter):
    capabilities = AdapterCapabilities(
        name='ffmpeg',
        renders_video=True,
        exports_editable_project=False,
        features=frozenset({
            'shots', 'captions', 'narration_audio', 'music', 'video_shots',
            'motion', 'transitions', 'layers',
        }),
    )

    def render(self, plan, output, context):
        self.require_lossless(plan)
        from pipeline import file_hash, motion_filter
        adapter_code = file_hash(__file__)

        width, height, fps = plan['width'], plan['height'], plan['fps']
        shots = plan['shots']
        if any(shot['type'] == 'video' or shot.get('layers') for shot in shots):
            available = context.ff(['-filters']).stdout
            for name in ('overlay', 'scale', 'pad', 'rotate', 'geq', 'tpad', 'fps'):
                if not re.search(r'\b' + name + r'\b', available):
                    raise ValueError('FFmpeg lacks composition filter: ' + name)
            checked = set()
            for shot in shots:
                for media in [shot, *shot.get('layers', [])]:
                    if media['type'] != 'video':
                        continue
                    source = Path(media['asset'])
                    offset = media.get('source_start', 0)
                    if (source, offset) in checked:
                        continue
                    probe = context.ff([
                        '-ss', offset, '-i', source, '-map', '0:v:0', '-frames:v', 1,
                        '-progress', 'pipe:1', '-f', 'null', '-',
                    ])
                    if not any(int(value) > 0 for value in re.findall(
                            r'^frame=(\d+)', probe.stdout, re.MULTILINE)):
                        raise ValueError('No decodable video frame at source_start: ' + str(source))
                    checked.add((source, offset))

        raw = []
        for shot in shots:
            validate_layers(shot, shot['spoken_frames'] / fps)
            frames = shot['duration_frames']
            motion_config = plan.get('motion', {})
            visual_filter = motion_filter(
                width,
                height,
                frames,
                shot.get('motion', 'push'),
                motion_config.get('easing', 'smoothstep'),
                float(motion_config.get('max_zoom', 0.06)),
            )
            asset = Path(shot['asset'])
            if shot['type'] == 'video' or shot.get('layers'):
                args = render_args(shot, lambda value: Path(value), width, height, fps,
                                   frames, visual_filter)
                raw.append(context.cached(
                    'ffmpeg-composition',
                    [adapter_code, context.asset(asset), shot, width, height, fps, frames, visual_filter],
                    '.mp4',
                    lambda target, args=args: context.ff([*args, target]),
                ))
            else:
                raw.append(context.cached(
                    'ffmpeg-image-motion',
                    [adapter_code, file_hash(asset), visual_filter, fps, frames],
                    '.mp4',
                    lambda target, asset=asset, visual_filter=visual_filter, frames=frames:
                    context.ff([
                        '-loop', '1', '-framerate', str(fps), '-i', asset,
                        '-vf', visual_filter, '-frames:v', frames, '-an',
                        '-c:v', 'libx264', '-preset', 'fast', '-crf', '19',
                        '-pix_fmt', 'yuv420p', target,
                    ]),
                ))

        clips = []
        for index, shot in enumerate(shots):
            frames = shot['spoken_frames']
            incoming = shot['incoming_transition_frames']
            inputs = [adapter_code, file_hash(raw[index]), frames]
            if incoming:
                inputs.extend([file_hash(raw[index - 1]), incoming])

            def segment(target, index=index, frames=frames, incoming=incoming):
                args = ['-filter_complex_threads', '1', '-i', raw[index]]
                if incoming:
                    previous_spoken = shots[index - 1]['spoken_frames']
                    args += ['-ss', previous_spoken / fps, '-i', raw[index - 1]]
                    filters = [
                        '[1:v]settb=AVTB,setpts=PTS-STARTPTS[prev]',
                        '[0:v]settb=AVTB,setpts=PTS-STARTPTS[cur]',
                        f'[prev][cur]xfade=transition=fade:duration={incoming/fps}:'
                        f'offset=0,trim=duration={frames/fps},setpts=PTS-STARTPTS[v]',
                    ]
                else:
                    filters = [
                        f'[0:v]trim=duration={frames/fps},setpts=PTS-STARTPTS[v]']
                context.ff(args + [
                    '-filter_complex', ';'.join(filters), '-map', '[v]', '-an',
                    '-t', frames / fps, '-c:v', 'libx264', '-preset', 'fast',
                    '-crf', '19', '-pix_fmt', 'yuv420p', target,
                ])

            clips.append(context.cached('ffmpeg-segment', inputs, '.mkv', segment))

        listing = context.cache / 'visual-assembly.txt'
        listing.write_text(
            '\n'.join("file '" + path.name + "'" for path in clips) + '\n',
            encoding='utf-8',
        )
        joined = context.cached(
            'ffmpeg-visual-assembly',
            [adapter_code, *[file_hash(path) for path in clips]],
            '.mkv',
            lambda target: context.ff([
                '-f', 'concat', '-safe', '0', '-i', listing, '-c', 'copy', target,
            ]),
        )
        if output:
            output = Path(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(joined, output)
            return output
        return joined
