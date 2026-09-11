"""Wan2.2 TI2V-5B adapter for a manually launched Kaggle worker."""
from .base import VideoGenerator, require


class WanKaggleGenerator(VideoGenerator):
    provider = 'wan22_kaggle'
    defaults = {
        'model': 'Wan-AI/Wan2.2-TI2V-5B',
        'task': 'ti2v-5B',
        'size': '1280*704',
        'fps': 24,
        'max_frame_num': 121,
        'sample_steps': 50,
        'sample_shift': 5.0,
        'sample_solver': 'unipc',
        'sample_guide_scale': 5.0,
        'world_size': 2,
        'gpu_mode': 'dual_t4',
        'dit_fsdp': True,
        't5_fsdp': True,
        'ulysses_size': 2,
    }

    def validate_backend(self, backend):
        super().validate_backend(backend)
        require(backend.get('task') == 'ti2v-5B', 'wan22_kaggle task must be ti2v-5B')
        require(backend.get('size') in ('1280*704', '704*1280'),
                'wan22_kaggle size must be 1280*704 or 704*1280')
        require(backend.get('fps') == 24, 'Wan2.2 TI2V-5B output fps must be 24')
        revision = backend.get('model_revision')
        require(isinstance(revision, str) and revision.strip() and revision not in ('main', 'latest'),
                'wan22_kaggle requires a pinned model_revision/dataset version for cache safety')
        frame_num = backend.get('max_frame_num')
        require(type(frame_num) is int and 5 <= frame_num <= 121 and (frame_num - 1) % 4 == 0,
                'wan22_kaggle max_frame_num must be 4n+1 in 5..121')
        require(type(backend.get('world_size')) is int and backend['world_size'] >= 1,
                'wan22_kaggle world_size must be a positive integer')
        require(backend.get('ulysses_size') == backend['world_size'],
                'wan22_kaggle ulysses_size must equal world_size')
        require(24 % backend['ulysses_size'] == 0,
                'Wan2.2 TI2V-5B has 24 attention heads; ulysses_size must divide 24')
        require(1 <= int(backend.get('sample_steps', 0)) <= 100,
                'wan22_kaggle sample_steps must be 1..100')
        require(backend.get('sample_solver') in ('unipc', 'dpm++'),
                'wan22_kaggle sample_solver must be unipc or dpm++')

    def normalize_generation(self, generation, backend):
        value = super().normalize_generation(generation, backend)
        requested = float(value['duration_target']) * backend['fps']
        frame_num = 1 + 4 * round((requested - 1) / 4)
        frame_num = max(5, min(backend['max_frame_num'], frame_num))
        value.update({
            'frame_num': frame_num,
            'output_fps': backend['fps'],
            'sample_steps': int(generation.get('sample_steps', backend['sample_steps'])),
            'sample_shift': float(generation.get('sample_shift', backend['sample_shift'])),
            'sample_solver': generation.get('sample_solver', backend['sample_solver']),
            'sample_guide_scale': float(generation.get('sample_guide_scale', backend['sample_guide_scale'])),
        })
        require(1 <= value['sample_steps'] <= 100, 'wan22_kaggle sample_steps must be 1..100')
        require(value['sample_solver'] in ('unipc', 'dpm++'),
                'wan22_kaggle sample_solver must be unipc or dpm++')
        return value

