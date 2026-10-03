import { html, reactive } from "/assets/vendor/arrow.mjs";
import { fetchJson, fetchResponse } from "/assets/js/api.js";
import { showSnackbar } from "/assets/js/snackbar.js";
import { confirmDialog, openDialog } from "/assets/components/modal.js";

const COLORS = {
  LaneLines: "Lane Lines", LeadMarker: "Lead Marker", Path: "Path", PathEdge: "Path Edge",
  Sidebar1: "Sidebar Top", Sidebar2: "Sidebar Middle", Sidebar3: "Sidebar Bottom",
};

const COMPONENTS = {
  colors: { label: "Colors", flag: "hasColors", catalog: "DownloadableColors" },
  distance_icons: { label: "Distance Icons", flag: "hasDistanceIcons", catalog: "DownloadableDistanceIcons" },
  icons: { label: "Icons", flag: "hasIcons", catalog: "DownloadableIcons" },
  sounds: { label: "Sounds", flag: "hasSounds", catalog: "DownloadableSounds" },
  steering_wheel: { label: "Steering Wheel", flag: "hasSteeringWheel", catalog: "DownloadableWheels" },
  turn_signals: { label: "Turn Signals", flag: "hasTurnSignals", catalog: "DownloadableSignals" },
};

const ASSETS = {
  distance_icons: [
    ["distanceIcons_traffic", "Traffic", "distance_icons"], ["distanceIcons_aggressive", "Aggressive", "distance_icons"],
    ["distanceIcons_standard", "Standard", "distance_icons"], ["distanceIcons_relaxed", "Relaxed", "distance_icons"],
  ],
  icons: [["homeButton", "Home", "icons"], ["settingsButton", "Settings", "icons"]],
  sounds: [["startup", "Startup", "sounds"], ["prompt", "Prompt", "sounds"], ["engage", "Engage", "sounds"], ["disengage", "Disengage", "sounds"]],
  steering_wheel: [["steeringWheel", "Steering Wheel", "steering_wheel"]],
  turn_signals: [["turnSignal", "Normal", "signals"], ["turnSignalBlindspot", "Blindspot", "signals"]],
};

const ACTIONS = {
  apply: { label: "Apply to device", url: "/api/themes/apply" },
  save: { label: "Save on device", url: "/api/themes" },
  submit: { label: "Submit for community use", url: "/api/themes/submit" },
};

// Files stay in this intentional draft, outside Arrow's recursive object proxies.
let draft = null;

function assetUrl(theme, path, type) {
  return `/api/themes/asset/${encodeURIComponent(theme)}/${path.split("/").map(encodeURIComponent).join("/")}?type=${encodeURIComponent(type)}`;
}

function colorHex(color) {
  return `#${[color.red, color.green, color.blue].map(value => value.toString(16).padStart(2, "0")).join("")}`;
}

export function mount(container) {
  const controller = new AbortController();
  const dialogs = new Set();
  const fileRequests = Array.from({ length: 4 }, () => Promise.resolve());
  const previewUrls = new Map();
  const state = reactive({ loading: !draft, error: "", busy: "", assets: 0, colors: 0, signals: 0, frames: 0, tab: "colors", catalog: [], progress: "" });
  let downloadTimer;
  let finishDownloadWait;
  let draggedFrame = null;
  let nextFileRequest = 0;

  if (!draft) {
    const colors = {};
    for (const key of Object.keys(COLORS)) {
      colors[key] = { red: 23, green: 134, blue: 68, alpha: 255 };
    }
    colors.PathEdge = { red: 18, green: 107, blue: 54, alpha: 255 };

    draft = { name: "", username: "", colors, assets: {}, frames: [], signalStyle: "Static", signalType: "Single Image",
      signalLength: 100, revision: 0, submitted: "" };
  }

  function stopPlayback() {
    for (const root of [container, ...dialogs]) {
      root.querySelectorAll("audio").forEach(audio => audio.pause());
    }
  }

  function changed(section) {
    draft.revision++;
    if (section) {
      state[section]++;
    }

    const retained = new Set([...Object.values(draft.assets), ...draft.frames].filter(Boolean).map(asset => asset.file));
    for (const [file, url] of previewUrls) {
      if (!retained.has(file)) {
        URL.revokeObjectURL(url);
        previewUrls.delete(file);
      }
    }
  }

  function preview(asset) {
    if (!previewUrls.has(asset.file)) {
      previewUrls.set(asset.file, URL.createObjectURL(asset.file));
    }

    return previewUrls.get(asset.file);
  }

  function dialog(title, body) {
    const element = openDialog(title, body);
    dialogs.add(element);
    element.addEventListener("close", () => {
      element.querySelectorAll("audio").forEach(audio => audio.pause());
      dialogs.delete(element);
    }, { once: true });

    return element;
  }

  function readFile(url, type = "text") {
    // Leave browser connections available for the driving-state check.
    const slot = nextFileRequest++ % fileRequests.length;
    const request = fileRequests[slot].then(async () => {
      const response = await fetchResponse(url, { signal: controller.signal });
      return response[type]();
    });
    fileRequests[slot] = request.catch(() => {});

    return request;
  }

  async function readAsset(theme, path, type, label) {
    const blob = await readFile(assetUrl(theme, path, type), "blob");
    return { file: new File([blob], path.split("/").pop(), { type: blob.type }), label };
  }

  async function readCategory(data, category, theme, type, label) {
    const assets = {};
    await Promise.all((ASSETS[category] || []).map(async ([field, , folder]) => {
      let descriptor = data.images?.[field];
      if (category === "sounds") {
        descriptor = data.sounds?.[field];
      } else if (category === "distance_icons") {
        descriptor = data.images?.distanceIcons?.[field.slice("distanceIcons_".length)];
      }

      assets[field] = null;
      if (descriptor) {
        let path = descriptor.path;
        if (typeof descriptor === "string") {
          path = `${folder}/${descriptor}`;
        }

        assets[field] = await readAsset(theme, path, type, label);
      }
    }));

    const result = { assets };
    if (category === "colors") {
      result.colors = data.colors;
    } else if (category === "turn_signals") {
      result.signalStyle = data.turnSignalStyle || "Static";
      result.signalType = data.turnSignalType || "Single Image";
      result.signalLength = data.turnSignalLength || 100;
      result.frames = await Promise.all((data.sequentialImages || []).map(name => readAsset(theme, `signals/${name}`, type, label)));
    }

    return result;
  }

  async function initialize() {
    try {
      const [data, username] = await Promise.all([
        readFile("/api/themes/default", "json"), readFile("/api/params?key=DiscordUsername"),
      ]);

      const categories = await Promise.all(Object.keys(COMPONENTS).map(category => {
        const nameKey = { distance_icons: "distanceIcons", steering_wheel: "steeringWheel", turn_signals: "turnSignals" }[category] || category;
        return readCategory(data, category, "__active__", "active", data.theme_names?.[nameKey] || "Active theme");
      }));
      if (controller.signal.aborted) {
        return;
      }

      draft.username = username;

      for (const category of categories) {
        Object.assign(draft.assets, category.assets);
        for (const key of ["colors", "frames", "signalStyle", "signalType", "signalLength"]) {
          if (category[key]) {
            draft[key] = category[key];
          }
        }
      }

      state.loading = false;
    } catch (error) {
      if (!controller.signal.aborted) {
        state.error = error.message;
        state.loading = false;
      }
    }
  }

  async function act(name, operation) {
    if (state.busy || controller.signal.aborted) {
      return;
    }

    state.busy = name;
    state.progress = "";

    try {
      await operation();
    } catch (error) {
      if (!controller.signal.aborted) {
        showSnackbar(error.message || "The theme action could not be completed.", "error");
      }
    } finally {
      state.busy = "";
    }
  }

  function selectFiles(event, field, sequence = false) {
    const files = Array.from(event.target.files);
    event.target.value = "";
    if (!files.length) {
      return;
    }

    const sound = ASSETS.sounds.some(([name]) => name === field);
    for (const file of files) {
      if (file.size > 5 * 1024 * 1024) {
        showSnackbar(`${file.name} exceeds the 5 MiB upload limit.`, "error");
        return;
      }

      if (!sound && !/\.(png|jpe?g|gif)$/i.test(file.name)) {
        showSnackbar("Choose a PNG, JPEG or GIF image.", "error");
        return;
      }

      if (sequence && /\.gif$/i.test(file.name)) {
        showSnackbar("Sequential frames support PNG and JPEG images. GIFs can be used as a single image.", "error");
        return;
      }
    }

    stopPlayback();
    if (sequence) {
      draft.frames.push(...files.map(file => ({ file, label: "" })));
      changed("frames");
    } else {
      draft.assets[field] = { file: files[0], label: "" };
      changed("assets");
    }
  }

  function clearAsset(field) {
    stopPlayback();
    draft.assets[field] = null;
    changed("assets");
  }

  function fileRow([field, label], sound = false) {
    const id = `theme-file-${field}`;
    return html`<div class="${() => `theme-asset-row${sound ? " theme-sound-row" : ""}`}">
      <div class="file-upload-label">
        <span class="file-upload-text">${() => label}</span>
        <input id="${() => id}" class="file-upload-input" type="file" accept="${() => sound ? "audio/*" : ".png,.jpg,.jpeg,.gif"}"
          @change="${event => selectFiles(event, field)}" />
        <button type="button" class="file-upload-button" @click="${() => container.querySelector(`#${id}`).click()}">Choose File</button>
        ${() => {
          state.assets;
          const asset = draft.assets[field];
          if (!asset) {
            return "";
          }

          return html`<button type="button" class="file-clear-button" aria-label="${() => `Clear ${label}`}"
            @click="${() => clearAsset(field)}">Clear</button>`;
        }}
      </div>
      ${() => {
        state.assets;
        const asset = draft.assets[field];
        if (!asset) {
          return html`<div class="theme-asset-preview"><span class="theme-asset-empty">No file selected</span></div>`;
        }

        return html`<div class="theme-asset-preview">
          ${() => sound ? html`<audio controls preload="none" src="${() => preview(asset)}" aria-label="${() => `Preview ${label}`}"
            @error="${() => showSnackbar("This browser cannot preview this sound. The device will validate it when used.", "error")}"></audio>`
          : html`<img src="${() => preview(asset)}" alt="${() => `${label} preview`}" />`}
          <span title="${() => asset.label ? `${asset.label} — ${asset.file.name}` : asset.file.name}">
            ${() => asset.label ? `${asset.label} — ${asset.file.name}` : asset.file.name}</span>
        </div>`;
      }}
    </div>`;
  }

  function moveFrame(frame, target, button) {
    const previous = draft.frames.indexOf(frame);
    if (previous < 0 || target < 0 || target >= draft.frames.length || previous === target) {
      return;
    }

    draft.frames.splice(previous, 1);
    draft.frames.splice(target, 0, frame);
    changed("frames");

    if (button) {
      queueMicrotask(() => {
        if (!controller.signal.aborted && button.isConnected) {
          if (button.disabled) {
            button.parentElement.querySelector("button:not([disabled])").focus();
          } else {
            button.focus();
          }
        }
      });
    }
  }

  function removeFrame(frame, button) {
    const row = button.closest(".draggable-item");
    const next = row.nextElementSibling || row.previousElementSibling;
    const close = button.closest("dialog").querySelector(".dialog-close");

    draft.frames.splice(draft.frames.indexOf(frame), 1);
    changed("frames");

    queueMicrotask(() => {
      if (!controller.signal.aborted) {
        if (next?.isConnected && next.matches(".draggable-item")) {
          next.querySelector("button:last-child").focus();
        } else {
          close.focus();
        }
      }
    });
  }

  function sequenceEditor() {
    dialog("Turn Signal Sequence", html`<div class="draggable-list">
      <p>Drag frames to reorder them, or use the move buttons.</p>
      ${() => {
        state.frames;
        if (!draft.frames.length) {
          return html`<p>No sequence frames selected.</p>`;
        }

        return draft.frames.map((frame, index) => html`<div class="draggable-item" draggable="true"
          @dragstart="${event => {
            draggedFrame = frame;
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", String(index));
          }}"
          @dragover="${event => {
            event.preventDefault();
            event.currentTarget.classList.add("drop-before");
          }}"
          @dragleave="${event => event.currentTarget.classList.remove("drop-before")}"
          @dragend="${() => {
            draggedFrame = null;
          }}"
          @drop="${event => {
            event.preventDefault();
            event.currentTarget.classList.remove("drop-before");

            moveFrame(draggedFrame, index);
            draggedFrame = null;
          }}">
          <img class="sequential-image-preview" src="${() => preview(frame)}" alt="${() => frame.file.name}" />
          <span class="theme-frame-name">${() => frame.file.name}</span>
          <div class="seq-move-buttons">
            <button type="button" class="seq-move-btn" disabled="${() => index === 0}" aria-label="${() => `Move ${frame.file.name} up`}"
              @click="${event => moveFrame(frame, index - 1, event.currentTarget)}">↑</button>
            <button type="button" class="seq-move-btn" disabled="${() => index === draft.frames.length - 1}"
              aria-label="${() => `Move ${frame.file.name} down`}"
              @click="${event => moveFrame(frame, index + 1, event.currentTarget)}">↓</button>
            <button type="button" class="seq-move-btn" aria-label="${() => `Remove ${frame.file.name}`}"
              @click="${event => removeFrame(frame, event.currentTarget)}">Remove</button>
          </div>
        </div>`.key(frame));
      }}
    </div>`);
  }

  function formData(selected) {
    const data = new FormData();
    data.set("themeName", draft.name.trim());
    data.set("discordUsername", draft.username.trim());
    data.set("saveChecklist", JSON.stringify(Object.fromEntries(selected.map(category => [category, true]))));

    for (const category of selected) {
      if (category === "colors") {
        data.set("colors", JSON.stringify(draft.colors));
        continue;
      }

      for (const [field] of ASSETS[category]) {
        if (field === "turnSignal" && draft.signalType === "Sequential") {
          continue;
        }

        if (draft.assets[field]) {
          data.set(field, draft.assets[field].file);
        }
      }

      if (category === "turn_signals") {
        data.set("turnSignalStyle", draft.signalStyle);
        data.set("turnSignalType", draft.signalType);
        data.set("turnSignalLength", String(draft.signalLength));
        if (draft.signalType === "Sequential") {
          draft.frames.forEach((asset, index) => data.set(`turn_signal_${index + 1}`, asset.file));
        }
      }
    }

    let bytes = 0;
    for (const value of data.values()) {
      bytes += value instanceof File ? value.size : new Blob([value]).size;
      if (value instanceof File && value.size > 5 * 1024 * 1024) {
        throw new Error(`${value.name} exceeds the 5 MiB upload limit.`);
      }
    }

    if (bytes > 32 * 1024 * 1024) {
      throw new Error("The selected components exceed the 32 MiB request limit.");
    }

    return data;
  }

  function hasCategory(category) {
    if (category === "colors") {
      return true;
    }

    if (category === "turn_signals" && draft.signalType === "Sequential") {
      return draft.frames.length > 0 || !!draft.assets.turnSignalBlindspot;
    }

    return ASSETS[category].some(([field]) => !!draft.assets[field]);
  }

  function chooseAction(action) {
    const selected = new Set();
    let confirmation;
    const content = html`<form class="theme-action-form" @submit="${event => {
      event.preventDefault();

      act(action, async () => {
        if (!selected.size) {
          throw new Error("Select at least one component.");
        }

        if (action !== "apply" && !draft.name.trim()) {
          throw new Error("Enter a theme name.");
        }

        if (action === "submit" && !draft.username.trim()) {
          throw new Error("Enter your Discord username.");
        }

        const categories = Object.keys(COMPONENTS).filter(category => selected.has(category));
        const submissionKey = `${draft.revision}:${categories.join(",")}`;
        if (action === "submit" && draft.submitted === submissionKey) {
          throw new Error("These components have already been submitted. Make an edit before submitting them again.");
        }

        const body = formData(categories);
        confirmation.close();

        const result = await fetchJson(ACTIONS[action].url, { method: "POST", body });

        if (action === "submit") {
          draft.submitted = submissionKey;
        }

        if (!controller.signal.aborted) {
          showSnackbar(result.message, "success");
        }
      });
    }}">
      ${action === "apply" ? html`<p>This enables custom themes and applies the selected components. Unselected category settings stay saved;
        enabling custom themes can reactivate their previously configured selections.</p>` : html`<label class="theme-name-label">Theme Name
        <input id="themeName" type="text" autocomplete="off" value="${() => draft.name}" @input="${event => {
          draft.name = event.target.value;
          changed();
        }}" />
      </label>`}
      ${action === "save" ? html`<p>Saving an existing name updates its selected categories. Other categories remain saved.</p>` : ""}
      ${action === "submit" ? html`<p>Submit the selected components for community review. Acceptance does not mean immediate publication.</p>
        <label class="theme-name-label">Discord Username<input class="discord-username-input" type="text" value="${() => draft.username}"
          @input="${event => {
            draft.username = event.target.value;
            changed();
          }}" /></label>` : ""}
      <div class="checklist-container">
        ${Object.entries(COMPONENTS).filter(([key]) => hasCategory(key)).map(([key, component]) => html`<label class="checklist-item">
          <input type="checkbox" @change="${event => {
            if (event.target.checked) {
              selected.add(key);
            } else {
              selected.delete(key);
            }
          }}" />
          <span class="label-text">${() => component.label}</span>
        </label>`)}
      </div>
      <p>Clearing an editor selection does not delete a saved component.</p>
      <div class="modal-actions"><button type="button" class="btn" @click="${() => confirmation.close()}">Cancel</button>
        <button class="btn btn-primary" type="submit" disabled="${() => !!state.busy}">${() => ACTIONS[action].label}</button></div>
    </form>`;

    confirmation = dialog(ACTIONS[action].label, content);
  }

  async function loadCatalog() {
    const [local, downloadable] = await Promise.all([
      readFile("/api/themes/list", "json"),
      Promise.all(Object.entries(COMPONENTS).map(async ([category, component]) => {
        const names = await readFile(`/api/params?key=${component.catalog}`);
        return [category, names.split(",").map(name => name.trim()).filter(Boolean)];
      })),
    ]);
    if (controller.signal.aborted) {
      return;
    }

    const entries = [];
    for (const [category, component] of Object.entries(COMPONENTS)) {
      const installed = local.themes.filter(theme => theme[component.flag]);
      entries.push(...installed.map(theme => ({ ...theme, category, installed: true })));

      const installedNames = new Set(installed.map(theme => theme.name.toLowerCase()));
      const names = downloadable.find(([key]) => key === category)[1];
      entries.push(...names.filter(name => !installedNames.has(name.toLowerCase())).map(name => ({ name, category, installed: false })));
    }

    state.catalog = entries.sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: "base", numeric: true }));
  }

  async function loadComponent(theme) {
    const category = theme.category;
    let path = theme.path;
    if (theme.type === "steering_wheel") {
      path = path.replace(/\.[^.]+$/, "");
    }

    const data = await readFile(`/api/themes/load/${encodeURIComponent(path)}?type=${encodeURIComponent(theme.type)}`, "json");
    const incoming = await readCategory(data, category, theme.path, theme.type, theme.name);
    if (controller.signal.aborted) {
      return;
    }

    stopPlayback();
    Object.assign(draft.assets, incoming.assets);
    if (category === "colors") {
      if (!incoming.colors) {
        throw new Error("This theme has no colors to load.");
      }

      draft.colors = incoming.colors;
      changed("colors");
    } else if (category === "turn_signals") {
      draft.frames = incoming.frames;
      draft.signalLength = incoming.signalLength;
      draft.signalStyle = incoming.signalStyle;
      draft.signalType = incoming.signalType;
      changed("signals");
      state.frames++;
      state.assets++;
    } else {
      changed("assets");
    }

    showSnackbar(`Loaded ${COMPONENTS[category].label} from ${theme.name} into the editor.`, "success");
  }

  async function downloadComponent(theme) {
    await fetchJson("/api/themes/download_asset", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ component: theme.category, name: theme.name }) });

    const deadline = Date.now() + 180000;
    while (!controller.signal.aborted) {
      const progress = await readFile("/api/params_memory?key=ThemeDownloadProgress");
      state.progress = progress;
      if (/Downloaded!/i.test(progress)) {
        await loadCatalog();
        if (!controller.signal.aborted) {
          showSnackbar(`Downloaded ${COMPONENTS[theme.category].label} from ${theme.name}. It has not been applied.`, "success");
        }
        return;
      }

      if (/failed|cancelled|offline|invalid/i.test(progress)) {
        throw new Error(progress);
      }

      if (Date.now() > deadline) {
        throw new Error("The download has not finished. Check its status on the device.");
      }

      await new Promise(resolve => {
        finishDownloadWait = resolve;
        downloadTimer = setTimeout(resolve, 1000);
      });
      finishDownloadWait = null;
    }
  }

  async function deleteComponent(theme) {
    const label = `${COMPONENTS[theme.category].label} from ${theme.name}`;
    if (!await confirmDialog(`Delete ${label}`, `Delete ${label}? This removes this local component.`, { confirmText: "Delete", danger: true })) {
      return;
    }

    if (controller.signal.aborted) {
      return;
    }

    let component = theme.category;
    if (component === "turn_signals") {
      component = "signals";
    }
    if (component === "steering_wheel") {
      component = "";
    }

    await fetchJson(`/api/themes/delete/${encodeURIComponent(theme.path)}?type=${encodeURIComponent(theme.type)}&component=${component}`, { method: "DELETE" });
    await loadCatalog();

    if (!controller.signal.aborted) {
      showSnackbar(`Deleted ${label}.`, "success");
    }
  }

  function manageThemes() {
    dialog("Manage Themes", html`<div class="manage-themes-tabs" role="tablist" aria-label="Theme components">
      ${Object.entries(COMPONENTS).map(([category, component]) => html`<button class="${() => `tab-button ${state.tab === category ? "active" : ""}`}"
        type="button" role="tab" aria-selected="${() => state.tab === category}"
        @click="${() => {
          state.tab = category;
        }}">${() => component.label}</button>`)}
      </div><p>Download components, then load them into the editor to mix or edit them. Downloading does not apply a theme.</p>
      <p role="status">${() => state.progress || (state.busy ? "Working..." : "")}</p>
      <div class="themes-list">${() => {
        const entries = state.catalog.filter(theme => theme.category === state.tab);
        if (!entries.length) {
          return html`<p>No themes available in this category.</p>`;
        }

        return entries.map(theme => html`<div class="theme-item">
          <span class="theme-button">${() => `${theme.name}${theme.is_user_created ? " ★" : ""}`}</span>
          ${() => theme.installed ? html`<button class="btn" type="button" disabled="${() => !!state.busy}"
            @click="${() => act("loading", () => loadComponent(theme))}">Load into editor</button>
            ${() => theme.type !== "holiday" ? html`<button class="delete-theme-button" type="button" disabled="${() => !!state.busy}"
              aria-label="${() => `Delete ${COMPONENTS[theme.category].label} from ${theme.name}`}"
              @click="${() => act("deleting", () => deleteComponent(theme))}">Delete</button>` : ""}`
          : html`<button class="download-theme-button" type="button" disabled="${() => !!state.busy}"
            @click="${() => act("downloading", () => downloadComponent(theme))}">Download</button>`}
        </div>`);
      }}</div>`);
  }

  function card(category, content) {
    return html`<section class="theme-maker-widget"><h2 class="theme-maker-title">${() => COMPONENTS[category].label}</h2>${content}</section>`;
  }

  function signalEditor() {
    return html`<div class="upload-section">
      <label class="theme-name-label">Frame interval (25–1000 ms)<input class="turn-signal-input" type="number" min="25" max="1000"
        value="${() => {
          state.signals;
          return draft.signalLength;
        }}" @change="${event => {
          draft.signalLength = Math.max(25, Math.min(1000, Number.parseInt(event.target.value, 10) || 25));
          event.target.value = draft.signalLength;
          changed();
        }}" /></label>
      <div class="signal-type-toggle">${["Static", "Traditional"].map(style => html`<button class="${() => {
        state.signals;
        return `toggle-button ${draft.signalStyle === style ? "active" : ""}`;
      }}" type="button" @click="${() => {
        draft.signalStyle = style;
        changed("signals");
      }}">${() => style}</button>`)}</div>
      <details class="turn-signal-help-text"><summary>About signal styles</summary><p>Static appears next to the current speed.
        Traditional moves across the bottom of the screen.</p></details>
      <div class="signal-type-toggle">${["Single Image", "Sequential"].map(type => html`<button class="${() => {
        state.signals;
        return `toggle-button ${draft.signalType === type ? "active" : ""}`;
      }}" type="button" @click="${() => {
        draft.signalType = type;
        changed("signals");
      }}">${() => type}</button>`)}</div>
      ${fileRow(ASSETS.turn_signals[1])}
      ${() => {
        state.signals;
        if (draft.signalType === "Single Image") {
          return fileRow(ASSETS.turn_signals[0]);
        }

        return html`<div class="theme-sequence-controls">
          <input id="theme-sequence-files" class="file-upload-input" type="file" multiple accept=".png,.jpg,.jpeg"
          @change="${event => selectFiles(event, "turnSignal", true)}" />
          <button class="file-upload-button" type="button" @click="${() => container.querySelector("#theme-sequence-files").click()}">Add frames</button>
          <span>${() => {
            state.frames;
            return `${draft.frames.length} frame(s)`;
          }}</span>
          <button class="file-clear-button" type="button" @click="${() => {
            draft.frames = [];
            changed("frames");
          }}">Clear sequence</button>
          <button class="sequence-order-button" type="button" @click="${sequenceEditor}">View and reorder frames</button></div>`;
      }}
    </div>`;
  }

  html`<div class="theme-maker-container">${() => {
    if (state.error) {
      return html`<div class="theme-load-error"><p role="alert">${() => state.error}</p><button class="btn" type="button" @click="${() => {
        state.error = "";
        state.loading = true;

        initialize();
      }}">Retry</button></div>`;
    }

    return html`<div class="theme-maker-main-widget" aria-busy="${() => state.loading}" inert="${() => state.loading}"><h1 class="theme-maker-main-title">Theme Maker</h1>
      <div class="theme-maker-form"><div class="theme-maker-sub-widgets">
        ${card("colors", html`<div class="color-section">${Object.entries(COLORS).map(([key, label]) => html`<label class="color-label">
          <span>${() => label}</span><input type="color" aria-label="${() => label}" value="${() => {
            state.colors;
            return colorHex(draft.colors[key]);
          }}"
            @input="${event => {
              const hex = event.target.value;
              draft.colors[key] = { red: Number.parseInt(hex.slice(1, 3), 16), green: Number.parseInt(hex.slice(3, 5), 16),
                blue: Number.parseInt(hex.slice(5, 7), 16), alpha: 255 };
              changed();
            }}" /></label>`)}</div>`)}
        ${card("distance_icons", html`<p class="theme-guidance">Recommended image size: 250×250.</p>
          <div class="upload-section">${ASSETS.distance_icons.map(field => fileRow(field))}</div>`)}
        ${card("icons", html`<p class="theme-guidance">Home: 250×250. Settings: 169×104.</p>
          <div class="upload-section">${ASSETS.icons.map(field => fileRow(field))}</div>`)}
        ${card("sounds", html`<p class="theme-guidance">Preview supported sounds here. Files are converted for the device when used.</p>
          <div class="upload-section">${ASSETS.sounds.map(field => fileRow(field, true))}</div>`)}
        ${card("steering_wheel", html`<p class="theme-guidance">Recommended image size: 250×250.</p>${fileRow(ASSETS.steering_wheel[0])}`)}
        ${card("turn_signals", signalEditor())}
      </div><p class="theme-guidance">PNG, JPEG or GIF images; PNG/JPEG sequence frames. Up to 5 MiB per upload and 32 MiB per request.</p>
      <p class="theme-progress" role="status">${() => state.busy ? `${state.busy[0].toUpperCase()}${state.busy.slice(1)}...` : ""}</p>
      <div class="save-button-wrapper">
        <button class="apply-button" type="button" disabled="${() => !!state.busy}" @click="${() => chooseAction("apply")}">Apply to device</button>
        <button class="manage-themes-button" type="button" disabled="${() => !!state.busy}" @click="${() => act("loading", async () => {
          state.progress = "";

          await loadCatalog();
          if (!controller.signal.aborted) {
            manageThemes();
          }
        })}">Manage Themes</button>
        <button class="save-button" type="button" disabled="${() => !!state.busy}" @click="${() => chooseAction("save")}">Save on device</button>
        <button class="submit-button" type="button" disabled="${() => !!state.busy}" @click="${() => chooseAction("submit")}">Submit for community use</button>
      </div></div></div>`.key(state.loading ? "loading" : "loaded");
  }}</div>`(container);

  if (state.loading) {
    initialize();
  }

  return () => {
    controller.abort();
    clearTimeout(downloadTimer);
    finishDownloadWait?.();

    stopPlayback();
    for (const element of dialogs) {
      element.close();
    }

    previewUrls.forEach(url => URL.revokeObjectURL(url));
    previewUrls.clear();

    if (state.loading || state.error) {
      draft = null;
    }

    container.replaceChildren();
  };
}
