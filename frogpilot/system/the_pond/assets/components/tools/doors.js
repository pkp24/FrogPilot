import { html, reactive } from "/assets/vendor/arrow.mjs";
import { fetchJson } from "/assets/js/api.js";
import { showSnackbar } from "/assets/js/snackbar.js";
import { confirmDialog } from "/assets/components/modal.js";

export function mount(container) {
  const controller = new AbortController();
  const state = reactive({ available: false, busy: false, loading: true, message: "" });

  async function command(action) {
    if (state.busy || !state.available) {
      return;
    }

    state.busy = true;

    try {
      if (action === "unlock") {
        const confirmed = await confirmDialog("Unlock doors", "Unlock your car doors?", { confirmText: "Unlock" });
        if (!confirmed || controller.signal.aborted) {
          return;
        }
      }

      state.message = "Waiting for the car to confirm its door state...";
      const result = await fetchJson(`/api/doors/${action}`, { method: "POST" });

      state.message = result.message;
      if (!controller.signal.aborted) {
        showSnackbar(result.message);
      }
    } catch (error) {
      state.message = error.message;
      if (!controller.signal.aborted) {
        showSnackbar(error.message, "error");
      }
    } finally {
      state.busy = false;
    }
  }

  html`
    <div class="door-control-wrapper">
      <section class="door-control-widget">
        <h1 class="door-control-title">Lock/Unlock Doors</h1>
        <p class="door-control-text">Remotely lock or unlock your car doors while the car is off.</p>
        <button type="button" class="door-control-button" disabled="${() => !state.available || state.busy}"
          @click="${() => command("lock")}">🔒 Lock Doors</button>
        <button type="button" class="door-control-button" disabled="${() => !state.available || state.busy}"
          @click="${() => command("unlock")}">🔓 Unlock Doors</button>
        <p class="door-control-text" role="status" aria-live="polite" aria-busy="${() => state.loading}">${() => {
          if (state.loading) {
            return "...";
          }

          return state.message;
        }}</p>
      </section>
    </div>
  `(container);

  fetchJson("/api/doors_available", { signal: controller.signal }).then(data => {
    state.available = data.result;
    state.message = "Door control is not supported for this vehicle and device.";
    if (state.available) {
      state.message = "Ready. Door commands are available while the car is off.";
    }
  }).catch(error => {
    if (!controller.signal.aborted) {
      state.message = error.message;
    }
  }).finally(() => {
    state.loading = false;
  });

  return () => controller.abort();
}
