import { html, reactive } from "/assets/vendor/arrow.mjs";
import { fetchJson } from "/assets/js/api.js";
import { showSnackbar } from "/assets/js/snackbar.js";
import { formatSecondsToHuman } from "/assets/js/utils.js";
import { confirmDialog, openDialog } from "/assets/components/modal.js";

export function mount(container) {
  const controller = new AbortController();
  const state = reactive({ busy: false, error: "", output: null, paused: false });
  let selector = null;
  let stream = null;

  function closeStream() {
    stream?.close();
    stream = null;
  }

  function connectStream() {
    closeStream();
    if (controller.signal.aborted || state.paused || document.hidden) {
      return;
    }

    state.error = "";
    stream = new EventSource("/api/tmux_log/live");
    stream.onmessage = event => {
      state.error = "";
      state.output = event.data;
    };
    stream.onerror = () => {
      state.error = "Live tmux output is unavailable. Reconnecting...";
    };
  }

  async function capture() {
    if (state.busy) {
      return;
    }

    state.busy = true;

    try {
      const result = await fetchJson("/api/tmux_log/capture", { method: "POST" });
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

  async function deleteAll() {
    if (state.busy) {
      return;
    }

    state.busy = true;

    try {
      const confirmed = await confirmDialog("Delete captured logs", "Delete all saved tmux logs? This cannot be undone.", {
        confirmText: "Delete all", danger: true,
      });
      if (!confirmed || controller.signal.aborted) {
        return;
      }

      const result = await fetchJson("/api/tmux_log/delete_all", { method: "DELETE" });
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

  function chooseLog(action) {
    if (selector) {
      return;
    }

    const requestController = new AbortController();
    const files = reactive({ error: "", items: [], loading: true });

    async function loadFiles() {
      if (requestController.signal.aborted) {
        return;
      }

      files.loading = true;
      files.error = "";

      try {
        files.items = await fetchJson("/api/tmux_log/list", { signal: requestController.signal });
      } catch (error) {
        if (!requestController.signal.aborted) {
          files.error = error.message;
        }
      } finally {
        files.loading = false;
      }
    }

    async function useFile(file) {
      if (state.busy) {
        return;
      }

      if (action === "download") {
        const link = document.createElement("a");
        link.href = `/api/tmux_log/download/${encodeURIComponent(file.filename)}`;
        link.download = file.filename;

        document.body.append(link);
        link.click();
        link.remove();
        return;
      }

      state.busy = true;

      try {
        if (action === "rename") {
          let name = await confirmDialog("Rename captured log", "Choose a filename for this log.", {
            confirmText: "Rename", inputValue: file.filename.replace(/\.json$/, ""),
          });
          if (typeof name !== "string" || !name.trim() || controller.signal.aborted) {
            return;
          }

          name = name.trim();
          if (!name.endsWith(".json")) {
            name += ".json";
          }

          if (name === file.filename) {
            return;
          }

          await fetchJson(`/api/tmux_log/rename/${encodeURIComponent(file.filename)}/${encodeURIComponent(name)}`, { method: "PUT" });
          await loadFiles();
        } else {
          const confirmed = await confirmDialog("Delete captured log", `Delete “${file.filename}”?`, { confirmText: "Delete", danger: true });
          if (!confirmed || controller.signal.aborted) {
            return;
          }

          await fetchJson(`/api/tmux_log/delete/${encodeURIComponent(file.filename)}`, { method: "DELETE" });
          files.items = files.items.filter(item => item.filename !== file.filename);
        }

        if (!controller.signal.aborted) {
          showSnackbar("Captured log updated!");
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          showSnackbar(error.message, "error");
        }
      } finally {
        state.busy = false;
      }
    }

    const dialog = openDialog(`${action[0].toUpperCase() + action.slice(1)} captured log`, html`
      <div id="fileList" aria-label="Captured logs" aria-busy="${() => files.loading}">
        <div class="fileEntry header"><span>Filename</span><span>Date</span><span>Age</span></div>
        <p role="status">${() => {
          if (files.loading) {
            return "...";
          }

          if (files.error) {
            return files.error;
          }

          if (!files.items.length) {
            return "No tmux logs found.";
          }

          return "";
        }}</p>
        <button type="button" hidden="${() => !files.error}" @click="${loadFiles}">Try again</button>
        ${() => files.items.map(file => {
          const date = new Date(file.timestamp * 1000);
          const seconds = Math.max(0, (Date.now() - date.getTime()) / 1000);
          let age = "Just now";
          if (seconds >= 60) {
            age = `${formatSecondsToHuman(seconds)} ago`;
          }

          return html`
            <button type="button" class="fileEntry" disabled="${() => state.busy}" @click="${() => useFile(file)}">
              <span>${() => file.filename}</span><span>${() => date.toLocaleString()}</span><span>${() => age}</span>
            </button>
          `;
        })}
      </div>
    `);
    dialog.classList.add("tmux-log-dialog");
    selector = dialog;

    dialog.addEventListener("close", () => {
      requestController.abort();
      selector = null;
    }, { once: true });

    loadFiles();
  }

  html`
    <div class="tmux-block">
      <div class="tmux-wrapper">
        <section class="tmuxContainer">
          <h1 class="tmuxHeader">Tmux Live Log</h1>
          <pre class="tmuxLog" aria-label="Live tmux output" aria-busy="${() => state.output === null && !state.error && !state.paused}">${() => {
            if (state.output === null && !state.error && !state.paused) {
              return "...";
            }

            return state.output || "";
          }}</pre>
        </section>
      </div>
      <p role="status">${() => state.error}</p>
      <div class="tmux-controls">
        <button type="button" class="tmux-control-button" disabled="${() => state.busy}" @click="${capture}">💾 Capture Log</button>
        <button type="button" class="tmux-control-button" disabled="${() => state.busy}" @click="${() => chooseLog("delete")}">🗑️ Delete Log</button>
        <button type="button" class="tmux-control-button" disabled="${() => state.busy}" @click="${deleteAll}">🧨 Delete All Logs</button>
        <button type="button" class="tmux-control-button" disabled="${() => state.busy}" @click="${() => chooseLog("download")}">⬇️ Download Log</button>
        <button type="button" class="tmux-control-button" @click="${() => {
          state.paused = !state.paused;
          connectStream();
        }}">
          ${() => state.paused ? "▶️ Resume Log" : "⏸️ Pause Log"}
        </button>
        <button type="button" class="tmux-control-button" disabled="${() => state.busy}" @click="${() => chooseLog("rename")}">✏️ Rename Log</button>
      </div>
    </div>
  `(container);

  document.addEventListener("visibilitychange", connectStream);
  connectStream();

  return () => {
    controller.abort();
    closeStream();
    selector?.close();
    document.removeEventListener("visibilitychange", connectStream);
  };
}
