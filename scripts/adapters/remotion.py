"""Remotion adapter facade; implementation details stay outside the project model."""

from pathlib import Path
import shutil

from .base import AdapterCapabilities, RenderAdapter


class RemotionAdapter(RenderAdapter):
    capabilities = AdapterCapabilities(
        name='remotion',
        renders_video=True,
        exports_editable_project=False,
        features=frozenset({
            'shots', 'captions', 'narration_audio', 'music', 'video_shots',
            'motion', 'transitions', 'layers', 'graphics', 'effects', 'parallax',
        }),
    )

    def render(self, plan, output, context):
        self.require_lossless(plan)
        from remotion_adapter import prepare_plan, render, renderer_identity, validate_plan

        prepared = prepare_plan(plan, context)
        plan_path = context.work / (plan['stage'] + '-remotion-plan.json')
        from narrated_project.io import write_json
        write_json(plan_path, prepared)
        node = context.runtime.get('node') or 'node'
        validate_plan(plan_path, node)
        output = Path(output)
        rendered = context.cached(
            'remotion',
            [context.asset(plan_path), renderer_identity()],
            output.suffix or '.mp4',
            lambda target: render(plan_path, target, node),
        )
        qa_path = plan_path.with_name(plan_path.stem + '-qa.json')
        if qa_path.is_file():
            destination = context.root / 'deliverables' / (plan['stage'] + '-render-plan-qa.json')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(qa_path, destination)
        return rendered
