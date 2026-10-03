import { html, reactive } from "/assets/vendor/arrow.mjs";
import { downloadBlob, fetchJson, fetchResponse } from "/assets/js/api.js";
import { showSnackbar } from "/assets/js/snackbar.js";
import { confirmDialog } from "/assets/components/modal.js";

export function mount(container) {
  const controller = new AbortController();
  const state = reactive({ busy: false });

  async function backup() {
    if (state.busy) {
      return;
    }

    state.busy = true;

    try {
      const response = await fetchResponse("/api/toggles/backup", { method: "POST", signal: controller.signal });
      const file = await response.blob();

      if (!controller.signal.aborted) {
        downloadBlob(file, "toggle-backup.json");
        showSnackbar("Toggle backup downloaded!");
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        showSnackbar(error.message, "error");
      }
    } finally {
      state.busy = false;
    }
  }

  async function restore(event) {
    const file = event.currentTarget.files[0];
    event.currentTarget.value = "";
    if (!file || state.busy) {
      return;
    }

    state.busy = true;

    try {
      const data = JSON.parse(await file.text());
      if (controller.signal.aborted) {
        return;
      }

      const result = await fetchJson("/api/toggles/restore", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
      });

      if (!controller.signal.aborted) {
        showSnackbar(result.message);
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        showSnackbar(`Could not restore toggles: ${error.message}`, "error");
      }
    } finally {
      state.busy = false;
    }
  }

  async function reset(stock) {
    if (state.busy) {
      return;
    }

    state.busy = true;
    let defaults = "FrogPilot defaults";
    let action = "reset_default";
    if (stock) {
      defaults = "stock openpilot defaults";
      action = "reset_stock";
    }

    try {
      const confirmed = await confirmDialog("Reset toggles", `Reset all toggles to ${defaults} and reboot the device?`, {
        confirmText: "Reset and reboot", danger: true,
      });
      if (!confirmed || controller.signal.aborted) {
        return;
      }

      const result = await fetchJson(`/api/toggles/${action}`, { method: "POST" });
      if (!controller.signal.aborted) {
        showSnackbar(result.message);
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
    <div class="toggle-control-wrapper">
      <section class="toggle-control-widget">
        <h1 class="toggle-control-title">Backup/Restore Toggles</h1>
        <p class="toggle-control-text">Save your toggle settings or restore a compatible backup.</p>
        <button type="button" class="toggle-control-button" disabled="${() => state.busy}" @click="${backup}">Backup Toggles</button>
        <button type="button" class="toggle-control-button" disabled="${() => state.busy}"
          @click="${() => container.querySelector('input[type="file"]').click()}">Restore Toggles</button>
        <input type="file" accept=".json,application/json" hidden @change="${restore}">
      </section>
      <section class="toggle-control-widget">
        <h2 class="toggle-control-title">Reset Toggles to Default FrogPilot/Stock openpilot</h2>
        <p class="toggle-control-text">Reset all toggles and reboot. Resets are available only while offroad.</p>
        <button type="button" class="toggle-control-button" disabled="${() => state.busy}" @click="${() => reset(false)}">Reset Toggles to Default</button>
        <button type="button" class="toggle-control-button" disabled="${() => state.busy}" @click="${() => reset(true)}">Reset Toggles to Stock</button>
      </section>
    </div>
  `(container);

  return () => controller.abort();
}
