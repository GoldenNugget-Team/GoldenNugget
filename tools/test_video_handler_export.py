"""The video-loop export must hand PosterBoard a decodable frame sequence.

A CAKeyframeAnimation keeps every key image decoded in memory on the device,
so the renderer's footprint is frames x frame_width x frame_height x 4 bytes.
A 300-frame 1080x1920 export decodes to ~2.5 GB and jetsams the wallpaper
extension on iOS 27: still-frame fallback + ~1 s black blink on every respawn
(about a minute of flicker after a cold boot — issue #86). ``create_caml``
therefore fits every export inside the decoded-pixel budget (capping the fps,
skipping frames, and trading pixels for frames when the output would stutter)
while preserving the loop duration, and exports verbatim when the user turns
"Ignore Posterboard Frame Limit" on.
"""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy

from src.controllers import video_handler

# macOS uses its native encoder; Linux/Windows OpenCV wheels use FFmpeg.
_CAPTURE_API = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
_FOURCC = cv2.VideoWriter_fourcc(*("avc1" if sys.platform == "darwin" else "mp4v"))


def _write_video(path: str, frames: int, fps: float, size: tuple) -> tuple:
    """Encode a synthetic counting video; returns (frame count, fps) as later read back."""
    width, height = size
    writer = cv2.VideoWriter(path, _CAPTURE_API, _FOURCC, fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"VideoWriter refused to open {path}")
    for i in range(frames):
        canvas = numpy.zeros((height, width, 3), dtype=numpy.uint8)
        # every frame distinct so a skipped/seek bug shows up as duplicates
        canvas[:, :, 0] = (i * 7) % 255
        canvas[height // 2, :, 1] = 255
        writer.write(canvas)
    writer.release()
    cam = cv2.VideoCapture(path, _CAPTURE_API)
    # avc1 metadata over-counts (writer N -> getter N+1): count what decodes,
    # which is exactly what the exporter's own read loop will see.
    count, read_fps = 0, cam.get(cv2.CAP_PROP_FPS)
    while cam.read()[0]:
        count += 1
    cam.release()
    return count, read_fps


def _run_export(video: str, out_dir: str, **kwargs) -> dict:
    labels = []
    video_handler.create_caml(video, out_dir, auto_reverses=False, calculationMode='linear',
                              update_label=labels.append, **kwargs)
    caml = Path(out_dir, "main.caml").read_text()
    indices = [int(m) for m in re.findall(r'<CGImage src="assets/(\d+)\.jpg"/>', caml)]
    duration = float(re.search(r'duration="([\d.]+)"', caml).group(1))
    frame = cv2.imread(os.path.join(out_dir, "assets", f"{indices[0]}.jpg"))
    return {
        'labels': labels,
        'indices': indices,
        'duration': duration,
        'frame_h': frame.shape[0],
        'frame_w': frame.shape[1],
    }


class ExportAdaptationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._saved = (video_handler.ignore_pb_frame_limit,
                       video_handler.MAX_SEQUENCE_DECODED_BYTES)
        self.addCleanup(self._restore)
        video_handler.ignore_pb_frame_limit = False
        video_handler.MAX_SEQUENCE_DECODED_BYTES = 10 * 1024 * 1024  # shrink for test speed

    def _restore(self):
        video_handler.ignore_pb_frame_limit, video_handler.MAX_SEQUENCE_DECODED_BYTES = self._saved

    def _video(self, frames, fps, size):
        path = os.path.join(self._tmp.name, f"{frames}x{int(fps)}x{size[0]}.mp4")
        return path, _write_video(path, frames, fps, size)

    def test_small_exports_write_every_frame_verbatim(self):
        # 31 decoded frames x 320x200x4 = ~8 MB, under the 10 MB test budget
        video, (count, _) = self._video(30, 24, (320, 200))
        out = os.path.join(self._tmp.name, "out1")
        result = _run_export(video, out, bounds_scale=1.0)
        self.assertEqual(list(range(count)), result['indices'])
        self.assertFalse(any(l.startswith('Source:') for l in result['labels']))  # no adaptation notice
        self.assertGreater(result['duration'], 0)

    def test_adapted_export_fits_decoded_budget_and_keeps_duration(self):
        video, (count, read_fps) = self._video(120, 30, (320, 640))  # 808 KB decoded per frame > test budget
        out = os.path.join(self._tmp.name, "out2")
        # bounds_scale=1.0 keeps the render-relevant ceiling out of the way
        result = _run_export(video, out, bounds_scale=1.0)
        budget = video_handler.MAX_SEQUENCE_DECODED_BYTES
        decoded_bytes = len(result['indices']) * result['frame_w'] * result['frame_h'] * 4
        self.assertLessEqual(decoded_bytes, budget + 8 * result['frame_w'] * result['frame_h'])
        # frames are evenly strided, first frame present (the static <contents>)
        self.assertEqual(result['indices'][0], 0)
        stride = result['indices'][1]
        self.assertEqual(result['indices'], sorted(result['indices']))
        self.assertTrue(all(i % stride == 0 for i in result['indices']))
        # duration survives decimation
        self.assertAlmostEqual(result['duration'], count / read_fps, delta=max(0.05, 0.05 * count / read_fps))
        self.assertTrue(result['labels'])

    def test_resolution_is_capped_at_the_render_relevant_ceiling(self):
        # doc 100x100 + bounds_scale 1.0 -> every frame wider than 300 px is wasted
        video, (count, _) = self._video(12, 24, (1000, 500))
        out = os.path.join(self._tmp.name, "out3")
        result = _run_export(video, out, doc_width=100, doc_height=100, bounds_scale=1.0)
        self.assertLessEqual(result['frame_w'], 300)
        self.assertLessEqual(result['frame_h'], 300)
        self.assertEqual(list(range(count)), result['indices'])

    def test_ignore_switch_exports_the_source_verbatim(self):
        video, (count, _) = self._video(120, 30, (320, 640))
        out = os.path.join(self._tmp.name, "out4")
        video_handler.ignore_pb_frame_limit = True
        result = _run_export(video, out, bounds_scale=1.0)
        self.assertEqual(list(range(count)), result['indices'])
        self.assertFalse(any(l.startswith('Source:') for l in result['labels']))

    def test_over_limit_source_still_raises_with_the_switch_off(self):
        from src.exceptions.posterboard_exceptions import VideoLengthException
        video, _ = self._video(401, 30, (64, 48))
        with self.assertRaises(VideoLengthException):
            video_handler.create_caml(video, os.path.join(self._tmp.name, "out5"),
                                      auto_reverses=False, calculationMode='linear')


if __name__ == '__main__':
    unittest.main()
