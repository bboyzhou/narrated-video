"""Stable adapter interface and explicit capability negotiation."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AdapterCapabilities:
    name: str
    renders_video: bool
    exports_editable_project: bool
    features: frozenset = field(default_factory=frozenset)


def plan_features(plan):
    features = {'shots', 'captions', 'narration_audio'}
    if plan.get('music'):
        features.add('music')
    for shot in plan.get('shots', []):
        if shot.get('type') == 'video':
            features.add('video_shots')
        if shot.get('motion') != 'still':
            features.add('motion')
        if shot.get('transition_frames'):
            features.add('transitions')
        if shot.get('layers'):
            features.add('layers')
        if shot.get('graphics'):
            features.add('graphics')
        if shot.get('effects'):
            features.add('effects')
        if any(layer.get('depth') for layer in shot.get('layers', [])):
            features.add('parallax')
    return features


class AdapterError(RuntimeError):
    pass


class UnsupportedFeatures(AdapterError):
    def __init__(self, adapter, features):
        self.adapter = adapter
        self.features = sorted(features)
        super().__init__(adapter + ' cannot preserve: ' + ', '.join(self.features))


class RenderAdapter:
    capabilities = AdapterCapabilities('unknown', False, False)

    def unsupported_features(self, plan):
        return plan_features(plan) - set(self.capabilities.features)

    def require_lossless(self, plan):
        unsupported = self.unsupported_features(plan)
        if unsupported:
            raise UnsupportedFeatures(self.capabilities.name, unsupported)

    def render(self, plan, output, context):
        raise AdapterError(self.capabilities.name + ' does not render video')

    def export(self, plan, output, context=None):
        raise AdapterError(self.capabilities.name + ' does not export editable projects')
