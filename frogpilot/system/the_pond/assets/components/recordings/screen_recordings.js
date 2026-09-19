import { html, reactive } from "/assets/vendor/arrow.mjs";
import { fetchEvents, fetchJson } from "/assets/js/api.js";
import { showSnackbar } from "/assets/js/snackbar.js";
import { confirmDialog, openDialog } from "/assets/components/modal.js";

export function formatMediaDate(value) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) {
    return value || "Unknown date";
  }

  const day = date.getDate();
  const endings = ["th", "st", "nd", "rd"];
  const remainder = day % 100;
  const ending = endings[(remainder - 20) % 10] || endings[remainder] || endings[0];
  const month = date.toLocaleString("en-US", { month: "long" });
  const time = date.toLocaleString("en-US", { hour: "numeric", minute: "2-digit", hour12: true }).replace(" ", "").toLowerCase();

  return `${month} ${day}${ending}, ${date.getFullYear()} - ${time}`;
}

export function stopPreviews(container) {
  container.querySelectorAll(".recording-preview-gif").forEach(image => {
    image.hidden = true;
    image.removeAttribute("src");
  });
}

export function mediaCard(item, title, open, disabled, action = "") {
  return html`
    <article class="recording-card"
      @mouseenter="${event => {
        if (disabled()) {
          return;
        }

        const image = event.currentTarget.querySelector(".recording-preview-gif");
        image.src = item.gif;
        image.hidden = false;
      }}"
      @mouseleave="${event => stopPreviews(event.currentTarget)}">
      <button type="button" class="recording-open" aria-label="${() => `Open ${title}`}"
        disabled="${disabled}" @click="${open}">
        <span class="recording-preview-container" aria-busy="true">
          <img class="recording-preview" src="${() => item.png}" alt="" loading="lazy" decoding="async"
            @load="${event => {
              event.currentTarget.parentElement.setAttribute("aria-busy", "false");
            }}"
            @error="${event => {
              event.currentTarget.style.visibility = "hidden";
              event.currentTarget.parentElement.setAttribute("aria-busy", "false");
            }}">
          <img class="recording-preview recording-preview-gif" alt="" hidden
            @error="${event => {
              event.currentTarget.hidden = true;
            }}">
        </span>
        <span class="recording-filename" title="${() => title}">${() => title}</span>
      </button>
      ${() => action}
    </article>
  `.key(item.filename || item.name);
}

function recordingTitle(recording) {
  if (recording.is_custom_name) {
    return recording.filename.replace(/\.mp4$/i, "").replace(/_/g, " ");
  }

  return formatMediaDate(recording.timestamp);
}

export function mount(container) {
  const controller = new AbortController();
  const state = reactive({ busy: false, error: "", loading: true, recordings: [], total: 0 });
  let player = null;

  async function refresh() {
    if (controller.signal.aborted) {
      return;
    }

    state.loading = true;
    state.error = "";
    state.recordings = [];
    state.total = 0;

    try {
      await fetchEvents("/api/screen_recordings/list", data => {
        if (data.recordings) {
          state.recordings.push(...data.recordings);
        }

        if (data.total !== undefined) {
          state.total = data.total;
        }
      }, { signal: controller.signal });
    } catch (error) {
      if (!controller.signal.aborted) {
        state.error = error.message;
      }
    } finally {
      if (!controller.signal.aborted) {
        state.loading = false;
      }
    }
  }

  async function rename(recording) {
    if (state.busy) {
      return;
    }

    state.busy = true;

    try {
      const name = await confirmDialog("Rename recording", "Choose a name for this recording.", {
        confirmText: "Save", inputValue: recording.filename.replace(/\.mp4$/i, ""),
      });
      if (typeof name !== "string" || !name.trim() || controller.signal.aborted) {
        return;
      }

      await fetchJson("/api/screen_recordings/rename", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ old: recording.filename, new: name.trim() }),
      });

      player?.close();
      await refresh();

      if (!controller.signal.aborted) {
        showSnackbar("Recording renamed!");
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        showSnackbar(error.message, "error");
      }
    } finally {
      state.busy = false;
    }
  }

  async function remove(recording = null) {
    if (state.busy) {
      return;
    }

    state.busy = true;

    try {
      let message = "Delete all completed screen recordings? This cannot be undone.";
      let url = "/api/screen_recordings/delete_all";
      if (recording) {
        message = `Delete “${recordingTitle(recording)}”? This cannot be undone.`;
        url = `/api/screen_recordings/delete/${encodeURIComponent(recording.filename)}`;
      }

      const confirmed = await confirmDialog("Delete recordings", message, { confirmText: "Delete", danger: true });
      if (!confirmed || controller.signal.aborted) {
        return;
      }

      await fetchJson(url, { method: "DELETE" });

      player?.close();
      await refresh();

      if (!controller.signal.aborted) {
        showSnackbar("Recordings deleted!");
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        showSnackbar(error.message, "error");
      }
    } finally {
      state.busy = false;
    }
  }

  function play(recording) {
    if (player) {
      return;
    }

    stopPreviews(container);
    const url = `/api/screen_recordings/download/${encodeURIComponent(recording.filename)}`;
    const dialog = openDialog(recordingTitle(recording), html`
      <div class="media-player-content">
        <div class="media-video" aria-busy="true">
          <video src="${() => url}" controls autoplay muted playsinline></video>
        </div>
        <p class="media-player-status" role="status"></p>
        <div class="button-row">
          <button type="button" class="close-button" disabled="${() => state.busy}" @click="${() => rename(recording)}">Rename</button>
          <a class="close-button action-download" href="${() => url}" download="${() => recording.filename}">Download</a>
          <button type="button" class="close-button action-delete" disabled="${() => state.busy}" @click="${() => remove(recording)}">Delete</button>
        </div>
      </div>
    `);
    dialog.classList.add("media-dialog");
    player = dialog;

    const video = dialog.querySelector("video");
    const videoContainer = dialog.querySelector(".media-video");
    video.addEventListener("loadedmetadata", () => {
      videoContainer.setAttribute("aria-busy", "false");
    });
    video.addEventListener("error", () => {
      videoContainer.setAttribute("aria-busy", "false");
      dialog.querySelector(".media-player-status").textContent = "Could not play this recording. Try its original download.";
    });

    dialog.addEventListener("close", () => {
      player = null;
    }, { once: true });
  }

  html`
    <div class="screen-recordings-wrapper">
      <section class="screen-recordings-widget">
        <h1 class="screen-recordings-title">Screen Recordings</h1>
        <p class="screen-recordings-message" role="status" aria-live="polite">${() => {
          if (state.error) {
            return state.error;
          }

          if (state.loading) {
            return "...";
          }

          if (!state.recordings.length) {
            return "No screen recordings found.";
          }

          return "";
        }}</p>
        <button type="button" class="show-preserved-button" hidden="${() => !state.error}" @click="${refresh}">Try again</button>
        <div class="screen-recordings-grid" aria-label="Screen recordings" aria-busy="${() => state.loading}">
          ${() => state.recordings.map(recording => mediaCard(recording, recordingTitle(recording), () => play(recording), () => state.busy || state.loading))}
          ${() => {
            if (!state.loading) {
              return "";
            }

            const count = Math.min(6, Math.max(0, state.total - state.recordings.length));

            return Array.from({ length: count }, () => html`<article class="recording-card" aria-hidden="true">
              <span class="recording-preview-container" aria-busy="true"></span>
              <span class="recording-filename">...</span>
            </article>`);
          }}
        </div>
        <button type="button" class="delete-all-button" hidden="${() => !state.recordings.length && !(state.loading && state.total)}"
          disabled="${() => state.loading || state.busy}" @click="${() => remove()}">
          ${() => state.busy ? "Please wait..." : "Delete All Recordings"}
        </button>
      </section>
    </div>
  `(container);

  refresh();

  return () => {
    controller.abort();
    player?.close();
    container.querySelectorAll("img").forEach(image => image.removeAttribute("src"));
  };
}
