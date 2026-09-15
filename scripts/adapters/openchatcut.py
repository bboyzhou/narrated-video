"""Loss-reporting OpenChatCut interchange adapter.

The public OpenChatCut MCP/EditorCore surface is the integration boundary.  This
adapter emits a deterministic import plan; a connected host may apply the plan
through the public commands without depending on OpenChatCut's private store.
"""

import copy
from pathlib import Path

from narrated_project.io import write_json
from .base import AdapterCapabilities, RenderAdapter, plan_features


class OpenChatCutAdapter(RenderAdapter):
    capabilities = AdapterCapabilities(
        name='openchatcut',
        renders_video=False,
        exports_editable_project=True,
        features=frozenset({
            'shots', 'captions', 'narration_audio', 'music', 'video_shots',
            'motion', 'transitions', 'layers',
        }),
    )

    def export(self, plan, output, context=None):
        unsupported = sorted(plan_features(plan) - set(self.capabilities.features))
        video_items = []
        overlay_tracks = {}
        for shot in plan['shots']:
            video_items.append({
                'id': shot['id'],
                'asset': shot['asset'],
                'type': shot['type'],
                'start_frame': shot['start_frame'],
                'duration_frames': shot['spoken_frames'],
                'source_start_seconds': shot.get('source_start', 0),
                'loop': shot.get('loop', False),
                'motion': shot.get('motion', 'still'),
                'transition_out_frames': shot.get('transition_frames', 0),
            })
            for index, layer in enumerate(shot.get('layers', [])):
                overlay_tracks.setdefault(index, []).append({
                    'id': shot['id'] + ':' + layer['id'],
                    'asset': layer['asset'],
                    'type': layer['type'],
                    'start_frame': shot['start_frame'] + round(layer['start'] * plan['fps']),
                    'duration_frames': round((layer['end'] - layer['start']) * plan['fps']),
                    'keyframes': copy.deepcopy(layer.get('keyframes', [])),
                })
        narration_items = []
        for caption in plan.get('captions', []):
            audio = plan['audio'][caption['id']]
            narration_items.append({
                'id': caption['id'],
                'asset': audio['path'],
                'start_frame': caption['start_frame'],
                'duration_frames': audio['frames'],
            })
        payload = {
            'kind': 'OpenChatCutImportPlan',
            'version': 1,
            'transport': 'mcp/editor-core',
            'source_project': copy.deepcopy(plan['source_project']),
            'canvas': {'width': plan['width'], 'height': plan['height'], 'fps': plan['fps']},
            'tracks': [
                {'id': 'video-main', 'kind': 'video', 'items': video_items},
                *[
                    {'id': 'video-overlay-' + str(index + 1), 'kind': 'video', 'items': items}
                    for index, items in sorted(overlay_tracks.items())
                ],
                {'id': 'audio-narration', 'kind': 'audio', 'items': narration_items},
                {'id': 'audio-music', 'kind': 'audio', 'items': copy.deepcopy(plan.get('music', []))},
                {'id': 'captions', 'kind': 'captions', 'items': copy.deepcopy(plan.get('captions', []))},
            ],
            'loss_report': {
                'lossless': not unsupported,
                'unsupported_features': unsupported,
                'note': ('Apply through OpenChatCut public MCP/EditorCore commands; '
                         'never write its private local project store directly.'),
            },
        }
        write_json(output, payload)
        return Path(output)
