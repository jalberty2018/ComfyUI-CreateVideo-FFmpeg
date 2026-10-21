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

Set **disable_metadata = true** on Create Video to prevent workflow/prompt
metadata supplied by downstream Save Video nodes from being passed to FFmpeg.
This applies to both `video` and `preview_video` when saved directly, including
with the built-in Save Video and Save Video (Preview Switch). It avoids
`Argument list too long` errors caused by large workflow metadata. The saved
file will not include that workflow/prompt; video/audio and color tags remain
unchanged. Default is false to preserve existing workflows. Nodes that decode
or recreate the VIDEO object may not retain this setting.

`IMAGE -> Create Video (External FFmpeg / NVENC) -> Save Video`

Optional AUDIO input: one mono or stereo batch. Audio is encoded as AAC,
padded with silence if shorter than the video and trimmed if longer.

Enable **preview** to show a separate temporary video player below this node.
Set **preview_percent** (1–100, default 50) to scale both width and height:
50% turns a 1920×1080 video into a 960×540 preview. Dimensions round down to
even pixels, with a minimum of 2. The `video` output and Save Video always
retain the original full resolution. Preview is off by default, including for
existing workflows, and no preview file is generated while off.

The third output, **preview_video** (VIDEO), provides the scaled preview for
connecting to other video nodes or Save Video. It is empty (`None`) when preview
is off; enable preview before using this output downstream. The existing
`video` and `report` outputs keep their positions. After updating, restart
ComfyUI and refresh the browser; recreate the node if the new socket is missing.

The preview uses a separate H.264 8-bit encode with libx264 and preserves audio,
frame rate and duration. This requires libx264 even when the main encoder uses
NVENC and adds encoding time. It is for checking motion/composition; HDR is not
tone-mapped for SDR displays. Preview files use ComfyUI's normal temp cleanup.
Restart ComfyUI and refresh the browser after installing this update.

The `report` STRING output shows the encoder actually used, for example
`Encoder used: h264_nvenc` or `Encoder used: libx264`, including when `auto`
is selected. Connect it to a text display node for debugging.

On Save Video select **format mp4 (or auto)** and **codec auto**. MKV is also
supported. The node's VIDEO object overrides saving to use external FFmpeg
stream-copy, preserving encoded video/audio and adding workflow metadata.
No second video encoding occurs. Re-encoding options on Save Video are rejected;
set quality on this node instead. WebM is not supported by this implementation.

Encoders: `auto` (default), `h264_nvenc`, `hevc_nvenc`, `av1_nvenc`, `libx264` (CPU).
`auto` selects `h264_nvenc` for 8-bit or `hevc_nvenc` for 10-bit when
`NVENC_ENABLED_HOST` is present (regardless of its value), otherwise `libx264`.
Explicit encoder selections override this automatic choice.
NVENC requires a compatible NVIDIA GPU, driver, FFmpeg build and container GPU
video-driver access. AV1 encoding requires a GPU supporting AV1 NVENC.
No silent CPU fallback occurs. Lower quality numbers mean higher quality and
larger files (NVENC CQ / x264 CRF). NVENC presets run from p1 to p7; CPU uses medium.

Native Create Video color inputs are supported:

- `bit_depth`: `auto`, `8`, `10`. Auto selects 8-bit for sRGB, 10-bit for HDR/HDR PQ.
- `color_space`: `sRGB`, `HDR` (BT.2020/HLG), `HDR PQ` (BT.2020/PQ).

These describe the **input** RGB values, just as in native Create Video. Selecting
HDR does not transform sRGB images into HDR. Supply images already encoded with
the selected transfer function and primaries. Values are clamped to [0, 1].
The node converts RGB to limited-range YUV 4:2:0 with the appropriate BT.709 or
BT.2020 matrix and writes primaries/transfer/matrix tags. 10-bit uses a 16-bit RGB
pipe to avoid intermediate 8-bit quantization. Width/height must be even; no alpha.
Explicit 8-bit HDR is allowed like the native node, but 10-bit is recommended.
No mastering-display or content-light metadata is synthesized for PQ.
Save Video stream-copy preserves the encoded bit depth and color tags.
Existing workflows default to 8-bit sRGB when these new optional inputs are absent.

The native advanced `codec` control is covered here by the existing `encoder`
selector. Native `codec=none` (deferred encoding) is not applicable: this node
always encodes with external FFmpeg when executed.

### Ubuntu 24.04 support

Ubuntu Noble ships FFmpeg 6.1.1 (package revision varies with updates).
The required RGB formats, scale matrices and HLG/PQ color tags are supported.

| Encoder | 8-bit | 10-bit | Requirements |
| --- | --- | --- | --- |
| `libx264` | Yes | Yes, with a 10-bit-capable build | CPU; 10-bit H.264 player support varies |
| `h264_nvenc` | Yes | No in the targeted FFmpeg 6.1 path | NVIDIA GPU/driver |
| `hevc_nvenc` | Yes | Yes | GPU supporting HEVC Main 10 |
| `av1_nvenc` | Yes | Yes | GPU supporting AV1 NVENC |

The node checks the actual executable's advertised encoder pixel formats before
encoding. GPU/driver availability is checked by FFmpeg when the encoder starts;
an advertised encoder alone does not establish that the GPU supports it.
10-bit H.264 NVENC is rejected explicitly instead of silently reducing precision.
For HDR on NVIDIA, use `encoder=hevc_nvenc`, `bit_depth=auto`, and the color space
matching your input. Keep Save Video codec on `auto`.

Check your server build with:

```bash
ffmpeg -version
ffmpeg -hide_banner -h encoder=libx264
ffmpeg -hide_banner -h encoder=hevc_nvenc
ffmpeg -hide_banner -h encoder=av1_nvenc
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,pix_fmt,color_range,color_space,color_transfer,color_primaries -of json output.mp4
```

References: [native Create Video](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_video.py),
[native RGB conversion](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_api/latest/_input_impl/video_types.py),
[Ubuntu package](https://packages.ubuntu.com/noble/ffmpeg),
[FFmpeg 6.1 NVENC implementation](https://github.com/FFmpeg/FFmpeg/blob/n6.1.1/libavcodec/nvenc.c),
[FFmpeg scale filter](https://ffmpeg.org/ffmpeg-filters.html#scale).

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

## Save Video (Preview Switch)

Use `VIDEO -> Save Video (Preview Switch)` to save a video with optional display.
**hide_preview ON** (default) saves the file without showing a video player;
**OFF** saves and displays the saved video. Running with ON also clears a preview
from a previous execution. This switch only affects this node's preview.

Like Save Video, the node supports `filename_prefix`, automatic numbering,
`format`, `codec`, and embedded workflow metadata (unless disabled in ComfyUI).
It outputs the unchanged `video` and `saved_path`. Use `format=auto/mp4` and
`codec=auto` for the external FFmpeg node to preserve its encoded full-resolution
video without re-encoding. No reduced preview copy is generated by this save node.

## Server smoke test

Run inside the same environment/container as ComfyUI:

```bash
/usr/bin/ffmpeg -f lavfi -i color=size=1280x720:rate=30 -t 1 -c:v h264_nvenc -f null -
```

Then run a small image batch through the node into Save Video. Check frame count,
fps, audio and output playback. On a CPU-only machine choose `libx264`.
