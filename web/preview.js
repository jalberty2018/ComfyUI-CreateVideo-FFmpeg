import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

app.registerExtension({
    name: "CreateVideoExternalFFmpeg.Preview",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!["CreateVideoExternalFFmpegNVENC", "SaveVideoPreviewSwitch"].includes(nodeData.name)) return;
        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            const preview = message.ffmpeg_preview?.[0];
            if (!preview) {
                if (this.ffmpegPreviewWidget) {
                    this.ffmpegPreviewWidget.onRemove?.();
                    this.widgets.splice(this.widgets.indexOf(this.ffmpegPreviewWidget), 1);
                    this.ffmpegPreviewWidget = null;
                    this.setSize(this.computeSize());
                }
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
