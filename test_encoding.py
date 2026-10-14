"""Run with Python, numpy and imageio-ffmpeg; ComfyUI/torch are stubbed."""
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
import imageio_ffmpeg


class Tensor:
    def __init__(self, value):
        self.value = np.asarray(value)

    @property
    def shape(self):
        return self.value.shape

    @property
    def ndim(self):
        return self.value.ndim

    def __iter__(self):
        return (Tensor(v) for v in self.value)

    def detach(self):
        return self

    def clamp(self, lo, hi):
        return Tensor(np.clip(self.value, lo, hi))

    def mul(self, value):
        return Tensor(self.value * value)

    def round(self):
        return Tensor(np.round(self.value))

    def to(self, device=None, dtype=None):
        return Tensor(self.value.astype(dtype))

    def contiguous(self):
        return self

    def numpy(self):
        return self.value


class EncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        comfy = types.ModuleType("comfy")
        comfy.model_management = types.SimpleNamespace(throw_exception_if_processing_interrupted=lambda: None)
        comfy.utils = types.SimpleNamespace(ProgressBar=lambda count: types.SimpleNamespace(update=lambda n: None))
        class VideoFromFile:
            def __init__(self, path):
                pass
        modules = {
            "torch": types.SimpleNamespace(float32=np.float32, uint8=np.uint8),
            "folder_paths": types.SimpleNamespace(get_temp_directory=lambda: cls.temp.name),
            "comfy": comfy, "comfy.model_management": comfy.model_management,
            "comfy.utils": comfy.utils,
            "comfy_api.latest": types.SimpleNamespace(InputImpl=types.SimpleNamespace(VideoFromFile=VideoFromFile)),
        }
        spec = importlib.util.spec_from_file_location("external_video_test", Path(__file__).with_name("nodes.py"))
        cls.node = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(cls.node)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_encode_and_stream_copy_all_color_depth_combinations(self):
        # Float16 source exercises the 65535 overflow regression in the 10-bit path.
        images = Tensor(np.linspace(0, 1, 4 * 32 * 32 * 3, dtype=np.float16).reshape(4, 32, 32, 3))
        for color, transfer in [("sRGB", "iec61966-2-1"), ("HDR", "arib-std-b67"), ("HDR PQ", "smpte2084")]:
            for depth in (8, 10):
                with self.subTest(color=color, depth=depth):
                    video, report = self.node.CreateVideoExternalFFmpeg().create_video(
                        images, 24, "libx264", 20, "p4", self.ffmpeg,
                        bit_depth=depth, color_space=color)
                    self.assertEqual(video.get_bit_depth(), depth)
                    self.assertEqual(video.get_color_space(), color)
                    self.assertIn(f"bit depth: {depth}", report)
                    output = str(Path(self.temp.name) / f"saved-{color}-{depth}.mp4")
                    video.save_to(output, bit_depth=depth, color_space=color)
                    info = subprocess.run([self.ffmpeg, "-hide_banner", "-i", output], capture_output=True).stderr.decode()
                    self.assertIn("yuv420p10le" if depth == 10 else "yuv420p", info)
                    self.assertIn(transfer, info)
                    self.assertIn("bt709" if color == "sRGB" else "bt2020nc/bt2020", info)
                    # Stream-copy must retain identical encoded video payloads.
                    def digest(path):
                        return subprocess.check_output([self.ffmpeg, "-v", "error", "-i", path,
                                                       "-map", "0:v:0", "-c", "copy", "-f", "hash", "-"])
                    self.assertEqual(digest(video.path), digest(output))
                    raw = subprocess.check_output([self.ffmpeg, "-v", "error", "-i", output,
                                                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
                    self.assertEqual(len(raw), 4 * 32 * 32 * 3)
                    with self.assertRaises(ValueError):
                        video.save_to(io.BytesIO(), bit_depth=10 if depth == 8 else 8)

    def test_auto_and_nvenc_formats(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.node.encoding_settings("auto", "auto", "sRGB")[:2], ("libx264", 8))
            self.assertEqual(self.node.encoding_settings("auto", "auto", "HDR")[:2], ("libx264", 10))
        with patch.dict(os.environ, {"NVENC_ENABLED_HOST": "0"}):
            self.assertEqual(self.node.encoding_settings("auto", "auto", "sRGB")[:2], ("h264_nvenc", 8))
            encoder, depth, args = self.node.encoding_settings("auto", "auto", "HDR PQ")
            self.assertEqual((encoder, depth), ("hevc_nvenc", 10))
            self.assertIn("p010le", args)
        for encoder in ("hevc_nvenc", "av1_nvenc"):
            self.assertIn("p010le", self.node.encoding_settings(encoder, 10, "sRGB")[2])
        with self.assertRaises(ValueError):
            self.node.encoding_settings("h264_nvenc", 10, "sRGB")

    def test_invalid_settings_and_missing_encoder(self):
        for values in [("libx264", 12, "sRGB"), ("libx264", 8, "invalid"), ("invalid", 8, "sRGB")]:
            with self.assertRaises(ValueError):
                self.node.encoding_settings(*values)
        with self.assertRaises(RuntimeError):
            self.node.check_pixel_format(self.ffmpeg, "nonexistent_encoder", "yuv420p")


if __name__ == "__main__":
    unittest.main()
