# Create Video (External FFmpeg / NVENC)

Independent ComfyUI custom node. ID: `CreateVideoExternalFFmpegNVENC`.
The built-in Create Video node is not modified or replaced.

## Install

Copy this complete folder to the actual ComfyUI server's `custom_nodes` directory
and restart ComfyUI. Requires a recent ComfyUI providing
`comfy_api.latest.InputImpl.VideoFromFile`; torch/numpy are supplied by ComfyUI.
No additional Python packages are needed. FFmpeg is a separate prerequisite.

On RunPod, set `VHS_FORCE_FFMPEG_PATH=/usr/bin/ffmpeg` in the ComfyUI process
environment, or enter `/usr/bin/ffmpeg` in the node's `ffmpeg_path` field.
Resolution priority: node field, environment variable, then `ffmpeg` on PATH.
VideoHelperSuite does not need to be installed.

## Workflow

`IMAGE -> Create Video (External FFmpeg / NVENC) -> Save Video`

Optional AUDIO input: one mono or stereo batch. Audio is encoded as AAC,
padded with silence if shorter than the video and trimmed if longer.

The `report` STRING output shows the encoder actually used, for example
`Encoder used: h264_nvenc` or `Encoder used: libx264`, including when `auto`
is selected. Connect it to a text display node for debugging.

On Save Video select **format mp4 (or auto)** and **codec auto**. MKV is also
supported. The node's VIDEO object overrides saving to use external FFmpeg
stream-copy, preserving encoded video/audio and adding workflow metadata.
No second video encoding occurs. Re-encoding options on Save Video are rejected;
set quality on this node instead. WebM is not supported by this implementation.

Encoders: `auto` (default), `h264_nvenc`, `hevc_nvenc`, `av1_nvenc`, `libx264` (CPU).
`auto` selects `h264_nvenc` when `NVENC_ENABLED_HOST` is present in the ComfyUI
process environment (regardless of its value), otherwise `libx264`.
Explicit encoder selections override this automatic choice.
NVENC requires a compatible NVIDIA GPU, driver, FFmpeg build and container GPU
video-driver access. AV1 encoding requires a GPU supporting AV1 NVENC.
No silent CPU fallback occurs. Lower quality numbers mean higher quality and
larger files (NVENC CQ / x264 CRF). NVENC presets run from p1 to p7; CPU uses medium.

This version accepts **8-bit SDR/sRGB RGB images**, converted to limited-range
YUV 4:2:0. Width/height must be even. HDR, 10-bit and alpha are not supported.
Frames are streamed individually; the entire image batch is not copied to CPU.
Encoding occurs when Create Video executes, rather than being deferred to Save Video.

Encoding and direct Save Video saving use the external FFmpeg executable, not
PyAV. The native VIDEO wrapper inherits ComfyUI decoding/editing operations:
downstream extraction, trim or crop nodes may use PyAV or return native VIDEO
objects. The external-only saving guarantee applies to the direct connection
shown above. ComfyUI itself still requires its normal PyAV installation.

Encoded source files remain in ComfyUI's temp directory for cached VIDEO outputs;
they are not removed immediately after saving because the output may be reused.
Manage these with normal ComfyUI temp-directory cleanup when no workflow uses them.

## Server smoke test

Run inside the same environment/container as ComfyUI:

```bash
/usr/bin/ffmpeg -f lavfi -i color=size=1280x720:rate=30 -t 1 -c:v h264_nvenc -f null -
```

Then run a small image batch through the node into Save Video. Check frame count,
fps, audio and output playback. On a CPU-only machine choose `libx264`.
