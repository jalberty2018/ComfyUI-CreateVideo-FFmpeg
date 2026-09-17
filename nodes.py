"""External FFmpeg encoding with a native ComfyUI VIDEO output."""
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from fractions import Fraction

import torch
import folder_paths
import comfy.model_management
import comfy.utils
from comfy_api.latest import InputImpl


ENCODERS = ("h264_nvenc", "hevc_nvenc", "av1_nvenc", "libx264")


def resolve_ffmpeg(value=""):
    candidate = value.strip() or os.environ.get("VHS_FORCE_FFMPEG_PATH") or "ffmpeg"
    resolved = shutil.which(candidate)
    if not resolved:
        raise RuntimeError(
            f"FFmpeg not found: {candidate!r}. Set ffmpeg_path or "
            "VHS_FORCE_FFMPEG_PATH to the executable inside the ComfyUI server/container."
        )
    return resolved


def run_ffmpeg(command):
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True)
    if result.returncode:
        raise RuntimeError("External FFmpeg failed:\n" + result.stderr.decode("utf-8", "replace")[-12000:])


def value_of(value):
    return getattr(value, "value", value)


class ExternalFFmpegVideo(InputImpl.VideoFromFile):
    """Use external stream-copy for Save Video; inherited decoding stays compatible."""

    def __init__(self, path, ffmpeg, width, height, count, fps, encoder):
        super().__init__(path)
        self.path = path
        self.ffmpeg = ffmpeg
        self.width, self.height = width, height
        self.count, self.fps, self.encoder = count, fps, encoder

    def get_dimensions(self):
        return self.width, self.height

    def get_frame_count(self):
        return self.count

    def get_frame_rate(self):
        return self.fps

    def get_duration(self):
        return float(self.count / self.fps)

    def get_bit_depth(self):
        return 8

    def get_color_space(self):
        return "sRGB"

    def get_container_format(self):
        return "mp4"

    def save_to(self, path, format="auto", codec="auto", metadata=None,
                bit_depth=None, crf=None, color_space=None, preset=None):
        container, codec = value_of(format), value_of(codec)
        source_codec = {"h264_nvenc": "h264", "libx264": "h264",
                        "hevc_nvenc": "hevc", "av1_nvenc": "av1"}[self.encoder]
        if codec not in (None, "auto", source_codec):
            raise ValueError("Set Save Video codec to auto; select the encoder on Create Video (External FFmpeg / NVENC).")
        if crf is not None or bit_depth not in (None, 8) or color_space not in (None, "auto", "sRGB"):
            raise ValueError("This VIDEO is already encoded. Set quality on Create Video; disable re-encoding in Save Video.")
        is_file = isinstance(path, (str, os.PathLike))
        if container in (None, "auto"):
            container = Path(path).suffix.lower().lstrip(".") if is_file else "mp4"
            container = container or "mp4"
        if container not in ("mp4", "mkv"):
            raise ValueError("External FFmpeg VIDEO supports Save Video format mp4 or mkv. Use mp4/auto, not webm.")
        if is_file and os.path.abspath(path) == os.path.abspath(self.path):
            raise ValueError("The output must differ from the temporary source video.")
        # Always stage output so failed FFmpeg never leaves a partial destination.
        directory = os.path.dirname(os.path.abspath(path)) if is_file else folder_paths.get_temp_directory()
        os.makedirs(directory, exist_ok=True)
        fd, staged = tempfile.mkstemp(suffix="." + container, prefix="ffmpeg-save-", dir=directory)
        os.close(fd)
        try:
            command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                       "-i", self.path, "-map", "0:v:0", "-map", "0:a?", "-c", "copy"]
            for key, value in (metadata or {}).items():
                command += ["-metadata", f"{key}={value if isinstance(value, str) else json.dumps(value)}"]
            if container == "mp4":
                command += ["-movflags", "+faststart+use_metadata_tags"]
            command += ["-f", "matroska" if container == "mkv" else "mp4", staged]
            run_ffmpeg(command)
            if is_file:
                os.replace(staged, path)
            else:
                with open(staged, "rb") as source:
                    shutil.copyfileobj(source, path)
        finally:
            if os.path.exists(staged):
                os.unlink(staged)


class CreateVideoExternalFFmpeg:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "fps": ("FLOAT", {"default": 30.0, "min": 1.0, "max": 240.0, "step": 0.01}),
                "encoder": (list(ENCODERS), {"default": "h264_nvenc"}),
                "quality": ("INT", {"default": 20, "min": 1, "max": 51,
                    "tooltip": "Lower means higher quality/larger files. NVENC CQ; libx264 CRF."}),
                "nvenc_preset": (["p1", "p2", "p3", "p4", "p5", "p6", "p7"], {"default": "p4"}),
                "ffmpeg_path": ("STRING", {"default": "",
                    "tooltip": "Empty: VHS_FORCE_FFMPEG_PATH, then PATH. Linux example: /usr/bin/ffmpeg"}),
            },
            "optional": {"audio": ("AUDIO",)},
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "create_video"
    CATEGORY = "video/External FFmpeg"
    DESCRIPTION = "Encode 8-bit SDR images with external FFmpeg/NVENC. Connect to Save Video with codec auto."

    def create_video(self, images, fps, encoder, quality, nvenc_preset, ffmpeg_path="", audio=None):
        if encoder not in ENCODERS:
            raise ValueError("Unsupported encoder")
        if not math.isfinite(fps) or not 1 <= fps <= 240:
            raise ValueError("fps must be between 1 and 240")
        if not 1 <= quality <= 51 or nvenc_preset not in {f"p{i}" for i in range(1, 8)}:
            raise ValueError("Invalid quality or NVENC preset")
        if images.ndim != 4 or images.shape[-1] != 3 or images.shape[0] < 1:
            raise ValueError("Expected a nonempty IMAGE batch [frames, height, width, 3] (RGB).")
        count, height, width, _ = images.shape
        if width < 2 or height < 2 or width % 2 or height % 2:
            raise ValueError("Video width and height must be positive even numbers for YUV 4:2:0. Resize images first.")
        ffmpeg = resolve_ffmpeg(ffmpeg_path)
        rate = Fraction(str(fps)).limit_denominator(100000)
        temp_root = folder_paths.get_temp_directory()
        os.makedirs(temp_root, exist_ok=True)
        fd, output = tempfile.mkstemp(prefix="external-ffmpeg-", suffix=".mp4", dir=temp_root)
        os.close(fd)
        try:
            with tempfile.TemporaryDirectory(prefix="ffmpeg-input-", dir=temp_root) as scratch:
                command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{width}x{height}",
                    "-framerate", f"{rate.numerator}/{rate.denominator}", "-i", "pipe:0"]
                if audio is not None:
                    waveform = audio["waveform"]
                    sample_rate = int(audio["sample_rate"])
                    if waveform.ndim != 3 or waveform.shape[0] != 1 or waveform.shape[1] not in (1, 2) or waveform.shape[2] < 1 or sample_rate <= 0:
                        raise ValueError("Audio must contain one nonempty mono/stereo waveform [1, channels, samples] and a positive sample_rate.")
                    audio_path = os.path.join(scratch, "audio.f32le")
                    samples = waveform[0].detach().to(device="cpu", dtype=torch.float32).transpose(0, 1).contiguous().numpy()
                    samples.astype("<f4", copy=False).tofile(audio_path)
                    command += ["-f", "f32le", "-ar", str(sample_rate), "-ac", str(waveform.shape[1]), "-i", audio_path]
                command += ["-map", "0:v:0"]
                if audio is not None:
                    command += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k", "-af", "apad",
                                "-t", str(float(count / rate))]
                command += ["-c:v", encoder]
                if encoder.endswith("_nvenc"):
                    command += ["-preset", nvenc_preset, "-rc", "vbr", "-cq", str(quality), "-b:v", "0"]
                else:
                    command += ["-preset", "medium", "-crf", str(quality)]
                command += ["-vf", "scale=in_range=full:out_range=limited:out_color_matrix=bt709",
                            "-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709",
                            "-color_primaries", "bt709", "-color_trc", "iec61966-2-1"]
                if encoder == "hevc_nvenc":
                    command += ["-tag:v", "hvc1"]
                command += ["-movflags", "+faststart", output]
                # File-backed stderr avoids a full pipe deadlocking the encoder.
                with tempfile.TemporaryFile() as stderr:
                    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=stderr)
                    progress = comfy.utils.ProgressBar(count)
                    try:
                        try:
                            for frame in images:
                                comfy.model_management.throw_exception_if_processing_interrupted()
                                pixels = frame.detach().clamp(0, 1).mul(255).round().to(device="cpu", dtype=torch.uint8).contiguous().numpy()
                                process.stdin.write(pixels.tobytes())
                                progress.update(1)
                            process.stdin.close()
                        except BrokenPipeError:
                            pass
                        returncode = process.wait()
                        if returncode:
                            stderr.seek(0)
                            details = stderr.read().decode("utf-8", "replace")[-12000:]
                            raise RuntimeError(f"FFmpeg encoding with {encoder} failed. Check encoder support, GPU and container driver access.\n{details}")
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait()
                        if not process.stdin.closed:
                            try:
                                process.stdin.close()
                            except BrokenPipeError:
                                pass
            return (ExternalFFmpegVideo(output, ffmpeg, width, height, count, rate, encoder),)
        except BaseException:
            if os.path.exists(output):
                os.unlink(output)
            raise


NODE_CLASS_MAPPINGS = {"CreateVideoExternalFFmpegNVENC": CreateVideoExternalFFmpeg}
NODE_DISPLAY_NAME_MAPPINGS = {"CreateVideoExternalFFmpegNVENC": "Create Video (External FFmpeg / NVENC)"}
