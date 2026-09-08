"""Long-shot regression test for subpixel image motion.

python test_motion.py --ffmpeg PATH --image PATH
"""
import argparse
import subprocess

from pipeline import motion_filter


def frame_hashes(ffmpeg, image, vf, frames):
    result = subprocess.run(
        [ffmpeg, '-hide_banner', '-loglevel', 'error', '-loop', '1',
         '-framerate', '30', '-i', image, '-vf', vf, '-frames:v', str(frames),
         '-f', 'framemd5', '-'],
        capture_output=True, text=True, encoding='utf-8', check=True)
    return [line.rsplit(',', 1)[-1].strip()
            for line in result.stdout.splitlines() if line and not line.startswith('#')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', required=True)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()

    frames = 751  # 25 seconds at 30 fps, representative of the reported bug.
    modes = ('still', 'push', 'pull', 'pan-left', 'pan-right')
    for mode in modes:
        hashes = frame_hashes(args.ffmpeg, args.image,
                              motion_filter(640, 360, frames, mode), frames)
        assert len(hashes) == frames, (mode, len(hashes))
        distinct = len(set(hashes))
        if mode == 'still':
            assert distinct == 1, (mode, distinct)
            continue
        runs = []
        run = 1
        for previous, current in zip(hashes, hashes[1:]):
            if current == previous:
                run += 1
            else:
                runs.append(run)
                run = 1
        runs.append(run)
        assert distinct >= frames * 0.99, (mode, distinct)
        # Smoothstep intentionally slows at the endpoints; a few repeated
        # raster frames are acceptable, but long zoompan-style plateaus are not.
        assert max(runs) <= 5, (mode, max(runs))
    print('Subpixel motion regression passed for ' + ', '.join(modes))


if __name__ == '__main__':
    main()
