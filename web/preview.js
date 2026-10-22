import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

app.registerExtension({
    name: "CreateVideoExternalFFmpeg.Preview",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!["CreateVideoExternalFFmpegNVENC", "SaveVideoPreviewSwitch", "PreviewVideoExternalFFmpeg"].includes(nodeData.name)) return;
        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            const savedVideo = nodeData.name === "SaveVideoPreviewSwitch" ? message.video?.[0] : null;
            const hidePreview = message.ffmpeg_hide_preview?.[0] ?? true;
            // Retain support for cached results from earlier node versions.
            const preview = savedVideo ? (hidePreview ? null : savedVideo) : message.ffmpeg_preview?.[0];
            const download = savedVideo ? (hidePreview ? savedVideo : null) : message.ffmpeg_download?.[0];
            const mode = preview ? "video" : download ? "download" : null;
            if (this.ffmpegPreviewWidget && this.ffmpegPreviewWidget.ffmpegMode !== mode) {
                this.ffmpegPreviewWidget.onRemove?.();
                this.widgets.splice(this.widgets.indexOf(this.ffmpegPreviewWidget), 1);
                this.ffmpegPreviewWidget = null;
            }
            if (!mode) {
                this.setSize(this.computeSize());
                this.setDirtyCanvas(true, true);
                return;
            }
            if (mode === "download") {
                if (!this.ffmpegPreviewWidget) {
                    const link = document.createElement("a");
                    link.textContent = "Download video";
                    link.style.cssText = "display:flex;align-items:center;justify-content:center;box-sizing:border-box;width:100%;height:100%;border:1px solid var(--border-color,#555);border-radius:6px;background:var(--comfy-input-bg,#222);color:var(--input-text,#ddd);text-decoration:none;font:14px sans-serif;cursor:pointer;";
                    this.ffmpegPreviewWidget = this.addDOMWidget("ffmpeg_preview", "download", link, { serialize: false });
                    this.ffmpegPreviewWidget.ffmpegMode = mode;
                    this.ffmpegPreviewWidget.computeSize = (width) => [width, 44];
                    this.ffmpegPreviewWidget.onRemove = () => link.remove();
                }
                const link = this.ffmpegPreviewWidget.element;
                link.href = api.apiURL("/view?" + new URLSearchParams(download));
                link.download = download.filename;
                link.title = download.filename;
                this.setSize(this.computeSize());
                this.setDirtyCanvas(true, true);
                return;
            }
            if (!this.ffmpegPreviewWidget) {
                const video = document.createElement("video");
                video.controls = true;
                video.loop = true;
                video.muted = true;
                video.playsInline = true;
                video.style.cssText = "width:100%;height:100%;object-fit:contain;";
                this.ffmpegPreviewWidget = this.addDOMWidget("ffmpeg_preview", "video", video, { serialize: false });
                this.ffmpegPreviewWidget.ffmpegMode = mode;
                this.ffmpegPreviewWidget.computeSize = (width) => [width, 220];
                this.ffmpegPreviewWidget.onRemove = () => {
                    video.pause();
                    video.removeAttribute("src");
                    video.load();
                    video.remove();
                };
            }
            this.ffmpegPreviewWidget.element.src = api.apiURL("/view?" + new URLSearchParams(preview));
            this.setSize(this.computeSize());
            this.setDirtyCanvas(true, true);
        };
    },
});
