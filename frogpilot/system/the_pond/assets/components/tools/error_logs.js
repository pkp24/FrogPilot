import { html, reactive } from "/assets/vendor/arrow.mjs";
import { fetchJson, fetchResponse } from "/assets/js/api.js";
import { showSnackbar } from "/assets/js/snackbar.js";
import { formatSecondsToHuman, parseErrorLogToDate } from "/assets/js/utils.js";
import { confirmDialog } from "/assets/components/modal.js";

function fileDetails(filename) {
  let age = "Unknown age";
  let label = filename;

  try {
    const date = parseErrorLogToDate(filename);
    const seconds = Math.max(0, (Date.now() - date.getTime()) / 1000);
    label = date.toLocaleString();
    age = "Just now";
    if (seconds >= 60) {
      age = `${formatSecondsToHuman(seconds)} ago`;
    }
  } catch {}

  return { age, filename, label };
}

export function mount(container) {
  const controller = new AbortController();
  const state = reactive({ busy: false, content: "", error: "", files: [], loading: true, readError: "", reading: false, selected: "" });
  let viewerController = null;

  async function load() {
    state.loading = true;
    state.error = "";

    try {
      const names = await fetchJson("/api/error_logs", { signal: controller.signal });
      state.files = names.map(fileDetails);
    } catch (error) {
      if (!controller.signal.aborted) {
        state.error = error.message;
      }
    } finally {
      state.loading = false;
    }
  }

  function closeViewer() {
    viewerController?.abort();
    viewerController = null;

    state.content = "";
    state.readError = "";
    state.selected = "";
  }

  async function read(filename) {
    if (state.selected === filename) {
      closeViewer();
      return;
    }

    closeViewer();
    const requestController = new AbortController();
    viewerController = requestController;
    state.selected = filename;
    state.reading = true;

    try {
      const response = await fetchResponse(`/api/error_logs/${encodeURIComponent(filename)}`, { signal: requestController.signal });
      const content = await response.text();

      if (!requestController.signal.aborted) {
        state.content = content;
      }
    } catch (error) {
      if (!requestController.signal.aborted) {
        state.readError = `Could not read this log: ${error.message}`;
      }
    } finally {
      if (!requestController.signal.aborted) {
        state.reading = false;
      }
    }
  }

  async function remove(filename = "") {
    if (state.busy) {
      return;
    }

    state.busy = true;
    let message = "Delete all error logs? This cannot be undone.";
    let target = "delete_all";
    if (filename) {
      message = `Delete “${filename}”? This cannot be undone.`;
      target = encodeURIComponent(filename);
    }

    try {
      const confirmed = await confirmDialog("Delete error logs", message, { confirmText: "Delete", danger: true });
      if (!confirmed || controller.signal.aborted) {
        return;
      }

      await fetchJson(`/api/error_logs/${target}`, { method: "DELETE" });

      if (!filename || state.selected === filename) {
        closeViewer();
      }
      state.files = state.files.filter(file => filename && file.filename !== filename);

      if (!controller.signal.aborted) {
        showSnackbar("Error logs deleted!");
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        showSnackbar(error.message, "error");
      }
    } finally {
      state.busy = false;
    }
  }

  async function copy() {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(state.content);
      } else {
        const previousFocus = document.activeElement;
        const text = document.createElement("textarea");
        text.value = state.content;
        text.style.position = "fixed";
        text.style.left = "-9999px";
        container.append(text);

        try {
          text.select();
          if (!document.execCommand("copy")) {
            throw new Error("Clipboard access was refused");
          }
        } finally {
          text.remove();
          previousFocus?.focus();
        }
      }

      if (!controller.signal.aborted) {
        showSnackbar("Log copied!");
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        showSnackbar(`Could not copy log: ${error.message}`, "error");
      }
    }
  }

  html`
    <div class="error-logs-wrapper">
      <div id="errorLogs">
        <div id="fileList" aria-label="Error logs" aria-busy="${() => state.loading}">
          <p role="status">${() => {
            if (state.loading) {
              return "...";
            }

            if (state.error) {
              return state.error;
            }

            if (!state.files.length) {
              return "No error logs!";
            }

            return "";
          }}</p>
          <button type="button" hidden="${() => !state.error}" @click="${load}">Try again</button>
          ${() => state.files.map(file => html`
            <button type="button" class="fileEntry" aria-expanded="${() => state.selected === file.filename}"
              disabled="${() => state.busy}" @click="${() => read(file.filename)}">
              <span>${() => file.label}</span><span class="time-since">${() => file.age}</span>
            </button>
          `.key(file.filename))}
          <button type="button" class="delete-all-button" hidden="${() => !state.files.length}" disabled="${() => state.busy}"
            @click="${() => remove()}">Delete All Error Logs</button>
        </div>
        <div id="fileViewer" hidden="${() => !state.selected}">
          <div>
            <p>${() => state.selected}</p>
            <button type="button" aria-label="Close log viewer" @click="${closeViewer}"><i class="bi bi-x-lg"></i></button>
            <button type="button" aria-label="Delete log" disabled="${() => state.busy}" @click="${() => remove(state.selected)}">
              <i class="bi bi-trash"></i>
            </button>
            <button type="button" aria-label="Copy log to clipboard" disabled="${() => state.reading || Boolean(state.readError)}" @click="${copy}">
              <i class="bi bi-clipboard"></i>
            </button>
            <a aria-label="Download log" href="${() => `/api/error_logs/${encodeURIComponent(state.selected)}`}" download="${() => state.selected}">
              <i class="bi bi-download"></i>
            </a>
          </div>
          <pre aria-label="Log contents" aria-busy="${() => state.reading}">${() => state.reading ? "..." : state.readError || state.content}</pre>
        </div>
      </div>
    </div>
  `(container);

  load();

  return () => {
    controller.abort();
    closeViewer();
  };
}
