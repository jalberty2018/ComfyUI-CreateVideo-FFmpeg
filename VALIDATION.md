# Validation

2026-10-14: `test_encoding.py` passes all three tests, including six real
libx264 encode/decode/remux combinations (8/10-bit x sRGB/HLG/PQ), using the
Windows FFmpeg 7.1 executable bundled with imageio-ffmpeg 0.6.0. NumPy-backed
tensor and ComfyUI shims are used; no real PyTorch/ComfyUI installation is available.

Verified in this run:
- Correct output pixel formats and primaries/matrix/transfer tags after Save Video.
- Encoded video payload hashes unchanged by stream-copy; all four test frames decode.
- Float16 input is promoted before 16-bit RGB scaling to prevent overflow.
- Auto bit depth, NVIDIA auto encoder selection, and P010 selection for 10-bit NVENC.
- Clear rejection of 10-bit H.264 NVENC, invalid settings and unavailable encoders.
- Save rejects requests to change the encoded bit depth.

The first test run exposed missing transfer/primaries tags with this FFmpeg build.
Setting frame properties explicitly with `setparams` fixed all six combinations.
Ubuntu 24.04/FFmpeg 6.1 compatibility was reviewed against upstream source and
Ubuntu package information (links in README); it was not executed on Ubuntu.
NVENC hardware encoding, UI discovery, real PyTorch and HDR display playback still
require verification on the target server. No remote server was accessed.

To rerun: install numpy and imageio-ffmpeg in a test environment, then run
`python test_encoding.py` from this directory. These are test-only dependencies.

## Earlier baseline

2026-09-17: four automated test cases passed using an actual external FFmpeg
executable and libx264 on Windows. This environment has no ComfyUI/PyTorch/GPU;
ComfyUI interfaces and tensor operations were replaced with test shims backed by
NumPy. These tests do not establish compatibility with a particular installed
ComfyUI release or prove that NVENC works on the target RunPod.

Verified:
- Encoding 12 RGB frames; decoding yields all 12 at the expected dimensions.
- Saving MP4, MKV and an in-memory file; workflow/prompt metadata survive.
- Compressed video packet hashes match before/after Save Video stream-copy.
- Short audio is padded and long audio is trimmed to the video duration.
- Explicit FFmpeg path takes precedence over VHS_FORCE_FFMPEG_PATH.
- Invalid dimensions, unavailable executable and incompatible save options fail clearly.
- Cancellation kills the subprocess and removes its incomplete source file.
- NVENC command construction selects the requested encoder, CQ, preset and HEVC tag.

Still required on the target installation: restart ComfyUI, verify node discovery,
run a small workflow with h264_nvenc and Save Video codec=auto, then check playback.
