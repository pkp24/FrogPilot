import { html, reactive } from "/assets/vendor/arrow.mjs";
import { downloadBlob, fetchResponse } from "/assets/js/api.js";
import { showSnackbar } from "/assets/js/snackbar.js";

export function mount(container) {
  const controller = new AbortController();
  const state = reactive({ busy: false });

  async function download() {
    if (state.busy) {
      return;
    }

    state.busy = true;

    try {
      const response = await fetchResponse("/api/speed_limits", { method: "POST", signal: controller.signal });
      const file = await response.blob();

      if (!controller.signal.aborted) {
        downloadBlob(file, "speed_limits.json");
        showSnackbar("Speed limit data downloaded!");
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        showSnackbar(error.message, "error");
      }
    } finally {
      state.busy = false;
    }
  }

  html`
    <div class="download-speed-limits-wrapper">
      <section class="download-speed-limits-widget">
        <h1 class="download-speed-limits-title">Download Speed Limits</h1>
        <p class="download-speed-limits-text">
          Download data collected using Speed Limit Filler, then review it on the website before submitting any OSM edits.
        </p>
        <div class="download-speed-limits-button-wrapper">
          <button type="button" class="download-speed-limits-button" disabled="${() => state.busy}" @click="${download}">
            ${() => state.busy ? "Downloading..." : "Download"}
          </button>
          <a class="download-speed-limits-button" href="https://speedlimitfiller.frogpilot.com" target="_blank" rel="noopener noreferrer">Open Website</a>
        </div>
      </section>
    </div>
  `(container);

  return () => controller.abort();
}
