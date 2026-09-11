"""Compatibility adapter for the original CogVideoX/Colab workflow."""
from .base import VideoGenerator


class CogVideoXColabGenerator(VideoGenerator):
    provider = 'cogvideox_colab'
    defaults = {
        'model': 'THUDM/CogVideoX-5b-I2V',
        'model_revision': 'legacy-unpinned',
        'fps': 8,
        'sample_steps': 50,
        'guidance_scale': 6,
    }

