import { html, reactive } from "/assets/vendor/arrow.mjs";
import { fetchJson } from "/assets/js/api.js";
import { confirmDialog } from "/assets/components/modal.js";
import { showSnackbar } from "/assets/js/snackbar.js";

const KEYS = {
  amap1: { label: "AMap Key 1", prefix: "", length: 39, status: "amap1KeySet" },
  amap2: { label: "AMap Key 2", prefix: "", length: 39, status: "amap2KeySet" },
  public: { label: "Public Mapbox Key", prefix: "pk.", length: 80, status: "mapboxPublic" },
  secret: { label: "Secret Mapbox Key", prefix: "sk.", length: 80, status: "mapboxSecretSet" },
};

export function mount(container) {
  const controller = new AbortController();
  const keys = {};
  for (const kind of Object.keys(KEYS)) {
    keys[kind] = { saved: false, value: "" };
  }

  const state = reactive({ loading: true, busy: false, error: "", help: false, initialComplete: false, keys });

  async function load() {
    state.loading = true;
    state.error = "";

    try {
      const data = await fetchJson("/api/navigation", { signal: controller.signal });
      if (controller.signal.aborted) {
        return;
      }

      for (const [kind, key] of Object.entries(KEYS)) {
        state.keys[kind].saved = !!data[key.status];
      }
      state.initialComplete = state.keys.public.saved && state.keys.secret.saved;
    } catch (error) {
      if (!controller.signal.aborted) {
        state.error = error.message;
      }
    } finally {
      state.loading = false;
    }
  }

  function valueFor(kind) {
    let value = state.keys[kind].value.trim();
    if (value && !value.startsWith("pk.") && !value.startsWith("sk.")) {
      value = KEYS[kind].prefix + value;
    }

    return value;
  }

  async function update(kind, deleting = false) {
    if (state.busy || state.loading || state.error || controller.signal.aborted) {
      return;
    }

    const key = KEYS[kind];
    state.busy = true;

    try {
      if (deleting) {
        const confirmed = await confirmDialog("Delete Navigation Key", `Delete your ${key.label}?`, { confirmText: "Delete", danger: true });
        if (!confirmed || controller.signal.aborted) {
          return;
        }
      }

      let result;
      if (deleting) {
        result = await fetchJson(`/api/navigation_key?type=${kind}`, { method: "DELETE" });
      } else {
        const value = valueFor(kind);
        if (value.length < key.length) {
          throw new Error(`${key.label} is too short.`);
        }

        result = await fetchJson("/api/navigation_key", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [kind]: value }) });
      }

      state.keys[kind].value = "";
      state.keys[kind].saved = !deleting;
      if (deleting && (kind === "public" || kind === "secret")) {
        state.initialComplete = false;
      }

      if (!controller.signal.aborted) {
        showSnackbar(result.message, "success");
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        showSnackbar(error.message, "error");
      }
    } finally {
      state.busy = false;
    }
  }

  function group(title, kinds) {
    return html`<section class="navkeys-container" aria-busy="${() => state.loading}"><h1 class="navkeys-title">${() => title}
      ${title === "Mapbox Keys" ? html`<button type="button" class="navkeys-help-icon" aria-label="Toggle Mapbox setup guide"
        aria-expanded="${() => state.help}" @click="${() => {
          state.help = !state.help;
        }}"><i class="bi bi-info-circle" aria-hidden="true"></i></button>` : ""}</h1>
      ${kinds.map(kind => html`<form @submit="${event => {
        event.preventDefault();
        update(kind);
      }}">
        <label class="navkeys-label" for="${() => `${kind}-key`}">${() => KEYS[kind].label}
          <span class="navkeys-saved" role="status">${() => state.loading || state.error ? "..." : state.keys[kind].saved ? "Saved" : "Not saved"}</span></label>
        <div class="navkeys-row">
          <input class="navkeys-input" id="${() => `${kind}-key`}" type="password" autocomplete="new-password"
          spellcheck="false" placeholder="${() => state.keys[kind].saved ? "•••••••• — enter a replacement" : `${KEYS[kind].prefix}Enter key`}"
          value="${() => state.keys[kind].value}" disabled="${() => state.loading || state.busy || Boolean(state.error)}"
          @input="${event => {
            state.keys[kind].value = event.target.value;
          }}" />
          <button class="navkeys-btn" type="submit" disabled="${() => state.loading || state.busy || Boolean(state.error) || valueFor(kind).length < KEYS[kind].length}">
            ${() => state.keys[kind].saved ? "Replace" : "Save"}</button>
          ${() => state.keys[kind].saved ? html`<button class="navkeys-btn delete" type="button"
            aria-label="${() => `Delete ${KEYS[kind].label}`}" disabled="${() => state.loading || state.busy || Boolean(state.error)}"
            @click="${() => update(kind, true)}">Delete</button>` : ""}</div>
      </form>`)}
      ${() => {
        if (title !== "Mapbox Keys" || !state.help) {
          return "";
        }

        let image = "no_keys_set.png";
        if (state.keys.public.saved && state.keys.secret.saved) {
          image = "both_keys_set.png";
          if (state.initialComplete) {
            image = "setup_completed.png";
          }
        } else if (state.keys.public.saved) {
          image = "public_key_set.png";
        }

        return html`<div class="navkeys-help-img"><img src="${() => `/mapbox-help/${image}`}" alt="Mapbox key setup guide" /></div>`;
      }}</section>`;
  }

  html`<div class="navkeys-page"><div class="navkeys-progress" role="status">${() => state.busy ? "Updating key..." : ""}</div>
    ${() => state.error ? html`<p class="navkeys-error" role="alert">${() => state.error}
      <button class="navkeys-btn" type="button" @click="${load}">Retry</button></p>` : ""}
    <div class="navkeys-wrapper navkeys-offset-top">${group("AMap Keys", ["amap1", "amap2"])}${group("Mapbox Keys", ["public", "secret"])}</div>
  </div>`(container);

  load();

  return () => {
    controller.abort();

    for (const key of Object.values(state.keys)) {
      key.value = "";
    }

    container.replaceChildren();
  };
}
