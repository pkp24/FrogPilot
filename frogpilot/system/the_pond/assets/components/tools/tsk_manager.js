import { html, reactive } from "/assets/vendor/arrow.mjs";
import { fetchJson } from "/assets/js/api.js";
import { showSnackbar } from "/assets/js/snackbar.js";
import { confirmDialog } from "/assets/components/modal.js";

export function mount(container) {
  const controller = new AbortController();
  const state = reactive({ available: false, busy: false, error: "", keyName: "", keys: [], keyValue: "", loading: true, selectedName: "" });
  const selectedKey = () => state.keys.find(key => key.name === state.selectedName);
  const duplicateName = () => state.keys.some(key => key.name === state.keyName.trim() && key.name !== state.selectedName);

  function select(name) {
    state.selectedName = name;
    state.keyName = name;
    state.keyValue = "";
  }

  function canSave() {
    if (state.loading || !state.available || state.busy || !state.keyName.trim() || duplicateName()) {
      return false;
    }

    if (state.keyValue) {
      return /^[0-9a-fA-F]{32}$/.test(state.keyValue);
    }

    return Boolean(selectedKey()?.value_set && state.keyName.trim() !== state.selectedName);
  }

  async function save() {
    if (!canSave()) {
      return;
    }

    state.busy = true;
    state.error = "";

    const name = state.keyName.trim();
    const keys = state.keys.filter(key => key.name !== state.selectedName).map(key => ({ name: key.name }));
    if (state.keyValue) {
      keys.push({ name, value: state.keyValue });
    } else {
      keys.push({ name, rename_from: state.selectedName });
    }

    try {
      state.keys = await fetchJson("/api/tsk_keys", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(keys),
      });

      select(name);
      if (!controller.signal.aborted) {
        showSnackbar("Security key saved!");
      }
    } catch (error) {
      state.error = error.message;
    } finally {
      state.busy = false;
    }
  }

  async function remove() {
    if (state.busy || !state.selectedName) {
      return;
    }

    state.busy = true;
    const name = state.selectedName;

    try {
      const confirmed = await confirmDialog("Delete security key", `Delete the saved key “${name}”?`, { confirmText: "Delete", danger: true });
      if (!confirmed || controller.signal.aborted) {
        return;
      }

      state.keys = await fetchJson(`/api/tsk_keys?name=${encodeURIComponent(name)}`, { method: "DELETE" });

      select("");
      state.error = "";
      if (!controller.signal.aborted) {
        showSnackbar("Security key deleted!");
      }
    } catch (error) {
      state.error = error.message;
    } finally {
      state.busy = false;
    }
  }

  async function apply() {
    if (state.busy || !selectedKey()?.value_set) {
      return;
    }

    state.busy = true;
    state.error = "";

    try {
      await fetchJson("/api/tsk_key_set", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: state.selectedName }),
      });

      if (!controller.signal.aborted) {
        showSnackbar("Security key applied!");
      }
    } catch (error) {
      state.error = error.message;
    } finally {
      state.busy = false;
    }
  }

  html`
    <div class="tskkeys-wrapper tskkeys-offset-top">
      <section class="tskkeys-container">
        <h1 class="tskkeys-title">Toyota Security Key Manager</h1>
        <p role="status" hidden="${() => state.loading || state.available || Boolean(state.error)}">Security keys are not applicable to this vehicle.</p>
        <div hidden="${() => !state.loading && !state.available}"
          inert="${() => state.loading}" aria-busy="${() => state.loading}" aria-label="Security keys">
          <label class="tskkeys-label" for="tsk-select-key">Select Key</label>
          <div class="tskkeys-row">
            <select id="tsk-select-key" class="tskkeys-select" value="${() => state.selectedName}" disabled="${() => state.busy}"
              @change="${event => select(event.currentTarget.value)}">
              <option value="">-- Add a new key --</option>
              ${() => state.keys.map(key => html`<option value="${() => key.name}">${() => key.name}</option>`)}
            </select>
          </div>
          <label class="tskkeys-label" for="tsk-key-name">Key Name</label>
          <div class="tskkeys-row">
            <input id="tsk-key-name" class="tskkeys-input" placeholder="Enter key name..." autocomplete="off" maxlength="256"
              value="${() => state.keyName}" disabled="${() => state.busy}" @input="${event => {
                state.keyName = event.currentTarget.value;
              }}">
          </div>
          <p class="tskkeys-error" hidden="${() => !duplicateName()}">A key with this name already exists.</p>
          <label class="tskkeys-label" for="tsk-key-value">Key Value</label>
          <div class="tskkeys-row">
            <input id="tsk-key-value" class="tskkeys-input" autocomplete="off" spellcheck="false" maxlength="32"
              placeholder="${() => selectedKey()?.value_set ? "Configured. Enter a value to replace it..." : "32 hexadecimal characters"}"
              value="${() => state.keyValue}" disabled="${() => state.busy}" @input="${event => {
                state.keyValue = event.currentTarget.value.trim();
              }}">
            <button type="button" class="tskkeys-btn" aria-label="Save key" disabled="${() => !canSave()}" @click="${save}">💾</button>
            <button type="button" class="tskkeys-btn delete" aria-label="Delete key" disabled="${() => state.busy || !state.selectedName}"
              @click="${remove}">🗑️</button>
          </div>
          <p class="tskkeys-message" hidden="${() => !selectedKey()?.value_set}">A value is configured. Saved secret values are never sent to this page.</p>
          <div class="tskkeys-row tskkeys-apply-wrapper">
            <button type="button" class="tskkeys-btn apply" disabled="${() => state.busy || !selectedKey()?.value_set}" @click="${apply}">Apply Key</button>
          </div>
        </div>
        <p class="tskkeys-error" role="alert">${() => state.error}</p>
      </section>
    </div>
  `(container);

  Promise.all([
    fetchJson("/api/tsk_available", { signal: controller.signal }),
    fetchJson("/api/tsk_keys", { signal: controller.signal }),
  ]).then(([availability, keys]) => {
    state.available = availability.result;
    state.keys = keys;
  }).catch(error => {
    if (!controller.signal.aborted) {
      state.error = error.message;
    }
  }).finally(() => {
    state.loading = false;
  });

  return () => {
    controller.abort();
    state.keyValue = "";
  };
}
