import { html, reactive } from "/assets/vendor/arrow.mjs";
import { fetchEvents, fetchJson } from "/assets/js/api.js";
import { showSnackbar } from "/assets/js/snackbar.js";
import { confirmDialog, openDialog } from "/assets/components/modal.js";
import { formatMediaDate, mediaCard, stopPreviews } from "/assets/components/recordings/screen_recordings.js";

function routeTitle(route) {
  if (route.is_custom_name) {
    return route.timestamp.replace(/_/g, " ");
  }

  return formatMediaDate(route.timestamp);
}

export function mount(container) {
  const controller = new AbortController();
  const state = reactive({ busy: false, error: "", loading: true, preservedOnly: false, routes: [], total: 0 });
  let player = null;
  let bulkDialog = null;

  async function refresh() {
    if (controller.signal.aborted) {
      return;
    }

    state.loading = true;
    state.error = "";
    state.routes = [];
    state.total = 0;

    try {
      await fetchEvents("/api/routes", data => {
        if (data.routes) {
          state.routes.push(...data.routes);
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

  async function setPreserved(route, preserve) {
    if (state.busy) {
      return;
    }

    state.busy = true;

    try {
      const result = await fetchJson(`/api/routes/${encodeURIComponent(route.name)}/preserve`, { method: preserve ? "POST" : "DELETE" });

      route.is_preserved = result.preservation !== null;
      route.preservation = result.preservation;
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

  async function rename(route, reset = false) {
    if (state.busy) {
      return;
    }

    state.busy = true;

    try {
      let url = "/api/routes/clear_name";
      let body = { name: route.name };
      if (!reset) {
        const name = await confirmDialog("Rename route", "Choose a display name for this drive.", {
          confirmText: "Save", inputValue: routeTitle(route),
        });
        if (typeof name !== "string" || !name.trim() || controller.signal.aborted) {
          return;
        }

        url = "/api/routes/rename";
        body = { old: route.name, new: name.trim() };
      }

      await fetchJson(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

      player?.close();
      await refresh();

      if (!controller.signal.aborted) {
        showSnackbar(reset ? "Route name reset!" : "Route renamed!");
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        showSnackbar(error.message, "error");
      }
    } finally {
      state.busy = false;
    }
  }

  async function remove(route) {
    if (state.busy) {
      return;
    }

    state.busy = true;

    try {
      let message = `Delete “${routeTitle(route)}” and all its recorded segments? This cannot be undone.`;
      if (route.is_preserved) {
        message += " This route is preserved; this deletion still removes it.";
      }

      const confirmed = await confirmDialog("Delete route", message, { confirmText: "Delete route", danger: true });
      if (!confirmed || controller.signal.aborted) {
        return;
      }

      await fetchJson(`/api/routes/${encodeURIComponent(route.name)}`, { method: "DELETE" });

      player?.close();
      await refresh();

      if (!controller.signal.aborted) {
        showSnackbar("Route deleted!");
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        showSnackbar(error.message, "error");
      }
    } finally {
      state.busy = false;
    }
  }

  function removeAll() {
    if (bulkDialog) {
      return;
    }

    const selection = reactive({ includePreserved: false });
    const count = () => state.routes.filter(route => selection.includePreserved || !route.is_preserved).length;
    const dialog = openDialog("Delete dashcam routes", html`
      <p>${() => selection.includePreserved
        ? `Delete all ${count()} routes, including preserved routes? This cannot be undone.`
        : `Delete ${count()} unpreserved routes? Preserved routes will be kept. This cannot be undone.`}</p>
      <label class="include-preserved">
        <input type="checkbox" @change="${event => {
          selection.includePreserved = event.currentTarget.checked;
        }}"
          disabled="${() => state.busy}"> Include preserved routes
      </label>
      <div class="dialog-buttons">
        <button type="button" @click="${() => dialog.close()}">Cancel</button>
        <button type="button" class="btn-del" disabled="${() => state.busy || !count()}" @click="${async () => {
          if (state.busy || controller.signal.aborted) {
            return;
          }

          state.busy = true;

          try {
            await fetchJson("/api/routes/delete_all", {
              method: "DELETE", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ include_preserved: selection.includePreserved }),
            });

            dialog.close();
            player?.close();
            await refresh();

            if (!controller.signal.aborted) {
              showSnackbar("Selected routes deleted!");
            }
          } catch (error) {
            if (!controller.signal.aborted) {
              showSnackbar(error.message, "error");
            }
          } finally {
            state.busy = false;
          }
        }}">${() => state.busy ? "Deleting..." : "Delete selected routes"}</button>
      </div>
    `);
    bulkDialog = dialog;
    dialog.addEventListener("close", () => {
      bulkDialog = null;
    }, { once: true });
  }

  function play(route) {
    if (player) {
      return;
    }

    stopPreviews(container);
    const requestController = new AbortController();
    const playback = reactive({ camera: "forward", cameras: {}, error: "", index: 0, loading: true });
    const segmentUrls = () => playback.cameras[playback.camera] || [];
    const downloadUrl = () => `/video/${encodeURIComponent(route.name)}/combined?camera=${playback.camera}`;
    const dialog = openDialog(routeTitle(route), html`
      <div class="media-player-content">
        <div class="media-video" aria-busy="true">
          <video controls autoplay muted playsinline></video>
        </div>
        <p class="media-player-status" role="status">${() => {
          if (playback.error) {
            return playback.error;
          }

          if (playback.loading) {
            return "Recorded segment 0 of 0";
          }

          return `Recorded segment ${playback.index + 1} of ${segmentUrls().length}`;
        }}</p>
        <div class="button-row media-segments">
          <button type="button" class="close-button" disabled="${() => playback.loading || playback.index === 0}"
            @click="${() => loadSegment(playback.index - 1)}">Previous segment</button>
          <button type="button" class="close-button" disabled="${() => playback.loading || playback.index + 1 >= segmentUrls().length}"
            @click="${() => loadSegment(playback.index + 1)}">Next segment</button>
        </div>
        <div class="button-row media-cameras">
          ${["forward", "wide", "driver"].map(camera => html`
            <button type="button" class="close-button camera-button" aria-pressed="${() => playback.camera === camera}"
              disabled="${() => playback.loading || !playback.cameras[camera]?.length}" @click="${() => changeCamera(camera)}">
              ${() => camera[0].toUpperCase() + camera.slice(1)}
            </button>
          `)}
        </div>
        <p class="media-preservation-note">${() => {
          if (route.preservation === "legacy") {
            return "An existing flag preserves the first segment. It stays when whole-route priority is removed.";
          }

          if (route.is_preserved) {
            return "This whole route has retention priority. It can still be removed when storage becomes critically low.";
          }

          return "Preserve up to five whole routes with retention priority.";
        }}</p>
        <div class="button-row">
          <button type="button" class="close-button" disabled="${() => state.busy}" @click="${() => rename(route)}">Rename</button>
          <button type="button" class="close-button" hidden="${() => !route.is_custom_name}" disabled="${() => state.busy}"
            @click="${() => rename(route, true)}">Reset name</button>
          <button type="button" class="close-button" disabled="${() => state.busy}"
            @click="${() => setPreserved(route, route.preservation !== "route")}">
            ${() => route.preservation === "route" ? "Unpreserve whole route" : "Preserve whole route"}
          </button>
          <button type="button" class="close-button" hidden="${() => route.preservation !== "legacy"}" disabled="${() => state.busy}"
            @click="${() => setPreserved(route, false)}">Unpreserve first segment</button>
          <a class="close-button action-download" href="${downloadUrl}" download="${() => `${routeTitle(route)}-${playback.camera}.mp4`}">Download</a>
          <button type="button" class="close-button action-delete" disabled="${() => state.busy}" @click="${() => remove(route)}">Delete</button>
        </div>
      </div>
    `);
    dialog.classList.add("media-dialog");
    player = dialog;

    const video = dialog.querySelector("video");
    const videoContainer = dialog.querySelector(".media-video");

    function loadSegment(index, position = 0, paused = false) {
      const url = segmentUrls()[index];
      if (!url) {
        return;
      }

      playback.index = index;
      playback.error = "";
      videoContainer.setAttribute("aria-busy", "true");

      video.onloadedmetadata = () => {
        if (position > 0 && Number.isFinite(video.duration)) {
          video.currentTime = Math.min(position, video.duration);
        }

        if (paused) {
          video.pause();
        }
      };

      video.src = `${url}?camera=${playback.camera}`;
    }

    function changeCamera(camera) {
      if (camera === playback.camera) {
        return;
      }

      const current = segmentUrls()[playback.index];
      const position = video.currentTime;
      const paused = video.paused;
      playback.camera = camera;

      let index = segmentUrls().indexOf(current);
      if (index < 0) {
        const number = Number(current?.split("--").at(-1));
        index = segmentUrls().findIndex(url => Number(url.split("--").at(-1)) >= number);
        if (index < 0) {
          index = segmentUrls().length - 1;
        }

        loadSegment(index, 0, paused);
      } else {
        loadSegment(index, position, paused);
      }
    }

    video.addEventListener("ended", () => loadSegment(playback.index + 1));
    video.addEventListener("loadedmetadata", () => {
      videoContainer.setAttribute("aria-busy", "false");
    });
    video.addEventListener("error", () => {
      videoContainer.setAttribute("aria-busy", "false");
      playback.error = "This segment is unavailable. Try another segment or camera, or download the route.";
    });

    dialog.addEventListener("close", () => {
      requestController.abort();
      video.onloadedmetadata = null;
      player = null;
    }, { once: true });

    fetchJson(`/api/routes/${encodeURIComponent(route.name)}`, { signal: requestController.signal }).then(data => {
      if (requestController.signal.aborted) {
        return;
      }

      playback.cameras = data.camera_segments;
      const cameras = Object.keys(data.camera_segments);
      if (!cameras.length) {
        playback.error = "No camera footage remains in this route.";
        return;
      }

      if (!playback.cameras.forward) {
        playback.camera = cameras[0];
      }

      loadSegment(0);
    }).catch(error => {
      if (!requestController.signal.aborted) {
        playback.error = error.message;
      }
    }).finally(() => {
      if (!requestController.signal.aborted) {
        playback.loading = false;
        if (playback.error) {
          videoContainer.setAttribute("aria-busy", "false");
        }
      }
    });
  }

  html`
    <div class="screen-recordings-wrapper">
      <section class="screen-recordings-widget">
        <h1 class="screen-recordings-title">Dashcam Routes</h1>
        <button type="button" class="show-preserved-button" aria-pressed="${() => state.preservedOnly}"
          @click="${() => {
            state.preservedOnly = !state.preservedOnly;
          }}">
          ${() => state.preservedOnly ? "Show All Routes" : "Show Only Preserved Routes"}
        </button>
        <p class="screen-recordings-message" role="status" aria-live="polite">${() => {
          if (state.error) {
            return state.error;
          }

          if (state.loading) {
            return "...";
          }

          if (!state.routes.length) {
            return "No dashcam routes found.";
          }

          if (state.preservedOnly && !state.routes.some(route => route.is_preserved)) {
            return "No preserved routes.";
          }

          return "";
        }}</p>
        <button type="button" class="show-preserved-button" hidden="${() => !state.error}" @click="${refresh}">Try again</button>
        <div class="screen-recordings-grid" aria-label="Dashcam routes" aria-busy="${() => state.loading}">
          ${() => state.routes.filter(route => !state.preservedOnly || route.is_preserved).map(route => mediaCard(
            route, routeTitle(route), () => play(route), () => state.busy || state.loading,
            html`<button type="button" class="preserved-icon" disabled="${() => state.busy || state.loading}"
              aria-label="${() => route.preservation === "route" ? "Unpreserve whole route" : "Preserve whole route"}"
              title="${() => route.preservation === "route" ? "Unpreserve whole route" : "Preserve whole route"}"
              @click="${() => setPreserved(route, route.preservation !== "route")}">
              <i class="${() => route.is_preserved ? "bi bi-heart-fill" : "bi bi-heart"}" aria-hidden="true"></i>
            </button>`))}
          ${() => {
            if (!state.loading) {
              return "";
            }

            const count = Math.min(6, Math.max(0, state.total - state.routes.length));

            return Array.from({ length: count }, () => html`<article class="recording-card" aria-hidden="true">
              <span class="recording-preview-container" aria-busy="true"></span>
              <span class="recording-filename">...</span>
            </article>`);
          }}
        </div>
        <button type="button" class="delete-all-button" hidden="${() => !state.routes.length && !(state.loading && state.total)}"
          disabled="${() => state.loading || state.busy}" @click="${removeAll}">Delete Routes</button>
      </section>
    </div>
  `(container);

  refresh();

  return () => {
    controller.abort();
    player?.close();
    bulkDialog?.close();
    container.querySelectorAll("img").forEach(image => image.removeAttribute("src"));
  };
}
