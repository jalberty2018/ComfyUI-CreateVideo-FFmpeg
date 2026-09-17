# Validation

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
