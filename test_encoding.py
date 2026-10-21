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
                    video, report, preview_video = self.node.CreateVideoExternalFFmpeg().create_video(
                        images, 24, "libx264", 20, "p4", self.ffmpeg,
                        bit_depth=depth, color_space=color)["result"]
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

    def test_preview_keeps_full_resolution_output(self):
        images = Tensor(np.zeros((4, 32, 64, 3), dtype=np.float32))
        for enabled, percent, dimensions in [(False, 50, None), (True, 50, (32, 16)),
                                               (True, 33, (20, 10)), (True, 1, (2, 2)),
                                               (True, 100, (64, 32))]:
            with self.subTest(enabled=enabled, percent=percent):
                result = self.node.CreateVideoExternalFFmpeg().create_video(
                    images, 24, "libx264", 20, "p4", self.ffmpeg,
                    preview=enabled, preview_percent=percent)
                video, report, preview_video = result["result"]
                self.assertIn("video: size: 64x32 px; fps: 24; duration: 0.167 s", report)
                self.assertEqual(video.get_dimensions(), (64, 32))
                def decoded_size(path):
                    return len(subprocess.check_output([self.ffmpeg, "-v", "error", "-i", path,
                                                       "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]))
                self.assertEqual(decoded_size(video.path), 4 * 64 * 32 * 3)
                previews = result["ui"]["ffmpeg_preview"]
                if enabled:
                    self.assertIn(f"preview_video: size: {dimensions[0]}x{dimensions[1]} px ({percent}%); fps: 24; duration: 0.167 s", report)
                    self.assertEqual(preview_video.get_dimensions(), dimensions)
                    self.assertEqual(preview_video.get_frame_count(), 4)
                    self.assertEqual(preview_video.get_frame_rate(), video.get_frame_rate())
                    preview_saved = str(Path(self.temp.name) / "saved-preview-output.mp4")
                    preview_video.save_to(preview_saved)
                    self.assertEqual(decoded_size(preview_saved), 4 * dimensions[0] * dimensions[1] * 3)
                    path = str(Path(self.temp.name) / previews[0]["filename"])
                    self.assertNotEqual(path, video.path)
                    self.assertEqual(decoded_size(path), 4 * dimensions[0] * dimensions[1] * 3)
                    saved = str(Path(self.temp.name) / "saved-preview-test.mp4")
                    video.save_to(saved)
                    self.assertEqual(decoded_size(saved), 4 * 64 * 32 * 3)
                else:
                    self.assertIn("preview_video: disabled", report)
                    self.assertIsNone(preview_video)
                    self.assertEqual(previews, [])

    def test_preview_failure_cleans_up_files(self):
        images = Tensor(np.zeros((1, 32, 32, 3), dtype=np.float32))
        before = set(Path(self.temp.name).iterdir())
        with patch.object(self.node, "run_ffmpeg", side_effect=RuntimeError("preview failed")):
            with self.assertRaisesRegex(RuntimeError, "preview failed"):
                self.node.CreateVideoExternalFFmpeg().create_video(
                    images, 24, "libx264", 20, "p4", self.ffmpeg, preview=True)
        self.assertEqual(set(Path(self.temp.name).iterdir()), before)

    def test_save_preview_switch_always_saves_full_video(self):
        images = Tensor(np.zeros((4, 32, 64, 3), dtype=np.float32))
        video = self.node.CreateVideoExternalFFmpeg().create_video(
            images, 24, "libx264", 20, "p4", self.ffmpeg)["result"][0]
        modules = {
            "comfy.cli_args": types.SimpleNamespace(args=types.SimpleNamespace(disable_metadata=False)),
            "comfy_api.latest": types.SimpleNamespace(Types=types.SimpleNamespace(VideoContainer=str, VideoCodec=str)),
        }
        for hidden in (False, True):
            with self.subTest(hide_preview=hidden), patch.dict(sys.modules, modules), patch.object(
                self.node.folder_paths, "get_output_directory", return_value=self.temp.name, create=True
            ), patch.object(self.node.folder_paths, "get_save_image_path", create=True,
                            return_value=(self.temp.name, "switch", 1, "", "switch")):
                with patch.object(video, "save_to", wraps=video.save_to) as save:
                    result = self.node.SaveVideoPreviewSwitch().save_video(
                        video, "switch", "auto", "auto", hidden,
                        prompt={"test": 1}, extra_pnginfo={"workflow": {"nodes": []}})
                self.assertIs(result["result"][0], video)
                self.assertEqual(save.call_args.kwargs["metadata"],
                                 {"prompt": {"test": 1}, "workflow": {"nodes": []}})
                raw = subprocess.check_output([self.ffmpeg, "-v", "error", "-i", result["result"][1],
                                               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
                self.assertEqual(len(raw), 4 * 64 * 32 * 3)
                self.assertEqual(len(result["ui"]["ffmpeg_preview"]), 0 if hidden else 1)

    def test_disable_metadata_on_both_outputs(self):
        images = Tensor(np.zeros((2, 32, 64, 3), dtype=np.float32))
        for disabled in (False, True):
            result = self.node.CreateVideoExternalFFmpeg().create_video(
                images, 24, "libx264", 20, "p4", self.ffmpeg,
                preview=True, disable_metadata=disabled)
            for index in (0, 2):
                with self.subTest(disabled=disabled, output=index):
                    video = result["result"][index]
                    # Oversized workflow must never reach the OS argument list when disabled.
                    marker = "workflow_metadata_marker"
                    metadata = {"workflow": marker + ("x" * 200000 if disabled else ""),
                                "prompt": {"test": 1}}
                    destination = str(Path(self.temp.name) / f"metadata-{disabled}-{index}.mp4")
                    with patch.object(self.node, "run_ffmpeg", wraps=self.node.run_ffmpeg) as run:
                        video.save_to(destination, metadata=metadata)
                    command = run.call_args.args[0]
                    self.assertEqual("-metadata" in command, not disabled)
                    self.assertEqual(marker.encode() in Path(destination).read_bytes(), not disabled)
                    def digest(path):
                        return subprocess.check_output([self.ffmpeg, "-v", "error", "-i", path,
                                                       "-map", "0:v:0", "-c", "copy", "-f", "hash", "-"])
                    self.assertEqual(digest(video.path), digest(destination))

    def test_preview_only_uses_temp_and_preserves_video(self):
        images = Tensor(np.zeros((2, 32, 64, 3), dtype=np.float32))
        video = self.node.CreateVideoExternalFFmpeg().create_video(
            images, 24, "libx264", 20, "p4", self.ffmpeg)["result"][0]
        modules = {"comfy_api.latest": types.SimpleNamespace(
            Types=types.SimpleNamespace(VideoContainer=str, VideoCodec=str))}
        with patch.dict(sys.modules, modules), patch.object(
            self.node.folder_paths, "get_output_directory", create=True,
            side_effect=AssertionError("Preview must not access output directory")
        ), patch.object(video, "save_to", wraps=video.save_to) as save:
            result = self.node.PreviewVideoExternalFFmpeg().preview_video(video)
        self.assertIs(result["result"][0], video)
        self.assertIsNone(save.call_args.kwargs["metadata"])
        preview = result["ui"]["ffmpeg_preview"][0]
        self.assertEqual(preview["type"], "temp")
        path = Path(self.temp.name) / preview["filename"]
        raw = subprocess.check_output([self.ffmpeg, "-v", "error", "-i", str(path),
                                       "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
        self.assertEqual(len(raw), 2 * 32 * 64 * 3)
        before = set(Path(self.temp.name).iterdir())
        with patch.dict(sys.modules, modules), patch.object(video, "save_to", side_effect=RuntimeError("failed")):
            with self.assertRaisesRegex(RuntimeError, "failed"):
                self.node.PreviewVideoExternalFFmpeg().preview_video(video)
        self.assertEqual(set(Path(self.temp.name).iterdir()), before)
        empty = self.node.PreviewVideoExternalFFmpeg().preview_video(None)
        self.assertEqual(empty["ui"]["ffmpeg_preview"], [])

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
