import { html, reactive } from "/assets/vendor/arrow.mjs";
import { fetchJson } from "/assets/js/api.js";
import { confirmDialog } from "/assets/components/modal.js";
import { showSnackbar } from "/assets/js/snackbar.js";

export function isValidTailscaleAuthUrl(value) {
  if (typeof value !== "string") {
    return false;
  }

  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "login.tailscale.com" && !url.username && !url.password && !url.port;
  } catch {
    return false;
  }
}

export function mount(container) {
  const controller = new AbortController();
  const state = reactive({ status: "checking", installed: false, external: false, error: "" });

  async function checkStatus() {
    state.error = "";

    try {
      const result = await fetchJson("/api/tailscale/installed", { signal: controller.signal });
      if (!controller.signal.aborted) {
        state.external = result.external === true;
        state.installed = result.installed === true;
        state.status = "idle";
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        state.error = error.message;
        state.status = "error";
      }
    }
  }

  async function changeInstallation(uninstalling = state.installed) {
    if (state.status !== "idle" || state.external || controller.signal.aborted) {
      return;
    }

    state.status = "confirming";

    try {
      if (uninstalling) {
        const confirmed = await confirmDialog("Uninstall Tailscale", "Uninstall the Tailscale installation managed by The Pond?",
          { confirmText: "Uninstall", danger: true });
        if (!confirmed || controller.signal.aborted) {
          return;
        }
      }

      let endpoint = "/api/tailscale/setup";
      state.status = "installing";
      if (uninstalling) {
        endpoint = "/api/tailscale/uninstall";
        state.status = "uninstalling";
      } else if (state.installed) {
        state.status = "signingin";
      }

      const result = await fetchJson(endpoint, { method: "POST" });
      if (controller.signal.aborted) {
        return;
      }

      showSnackbar(result.message, "success");
      if (!uninstalling) {
        if (!isValidTailscaleAuthUrl(result.auth_url)) {
          throw new Error("Tailscale returned an invalid sign-in URL. Please try again.");
        }

        window.location.assign(result.auth_url);
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        showSnackbar(error.message, "error");
      }
    } finally {
      if (!controller.signal.aborted) {
        state.status = "checking";
        await checkStatus();
      }
    }
  }

  function actionLabel() {
    if (state.status === "checking") {
      return "...";
    }

    if (state.status === "installing") {
      return "Installing...";
    }

    if (state.status === "uninstalling") {
      return "Uninstalling...";
    }

    if (state.status === "signingin") {
      return "Opening sign-in...";
    }

    if (state.external) {
      return "Managed Outside The Pond";
    }

    if (state.installed) {
      return "Uninstall";
    }

    return "Install";
  }

  html`<div class="tailscale-wrapper"><section class="tailscale-widget"><h1 class="tailscale-title">Tailscale</h1>
    <p class="tailscale-text">${() => state.external ? "This Tailscale installation is managed outside The Pond."
      : "Connect your device to your phone or computer through Tailscale to access The Pond remotely."}</p>
    <p class="tailscale-text" role="status" aria-busy="${() => state.status === "checking"}">${() => {
      if (state.status === "checking") {
        return "...";
      }

      if (state.status === "idle" && !state.external) {
        return state.installed ? "Tailscale is installed and managed by The Pond." : "Tailscale is not installed.";
      }

      return "";
    }}</p>
    ${() => state.error ? html`<p class="tailscale-text" role="alert">${() => state.error}</p>
      <button type="button" class="tailscale-button" @click="${() => {
        state.status = "checking";
        checkStatus();
      }}">Retry status check</button>` : ""}
    <div class="tailscale-button-wrapper"><button class="tailscale-button" type="button" @click="${() => changeInstallation()}"
      disabled="${() => state.status !== "idle" || state.external}">${actionLabel}</button>
      ${() => state.installed && !state.external ? html`<button class="tailscale-button" type="button"
        disabled="${() => state.status !== "idle"}" @click="${() => changeInstallation(false)}">Continue Tailscale sign-in</button>` : ""}
      <a class="tailscale-link" href="https://tailscale.com/download" target="_blank" rel="noopener noreferrer">Download Tailscale on your other devices</a>
    </div></section></div>`(container);

  checkStatus();

  return () => {
    controller.abort();
    container.replaceChildren();
  };
}
