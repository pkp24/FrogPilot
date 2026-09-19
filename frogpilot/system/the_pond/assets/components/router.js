import { fetchJson } from "/assets/js/api.js";
import { mountSidebar, selectPage, updateAvailability } from "/assets/components/sidebar.js";

const pages = {
  "/": "home/home",
  "/dashcam_routes": "recordings/dashcam_routes",
  "/download_speed_limits": "tools/speed_limits",
  "/lock_or_unlock_doors": "tools/doors",
  "/manage_error_logs": "tools/error_logs",
  "/manage_navigation_keys": "navigation/navigation_keys",
  "/manage_tailscale": "tailscale/tailscale",
  "/manage_tmux": "tools/tmux",
  "/manage_toggles": "tools/toggles",
  "/screen_recordings": "recordings/screen_recordings",
  "/set_navigation_destination": "navigation/navigation_destination",
  "/theme_maker": "tools/theme_maker",
  "/tsk_manager": "tools/tsk_manager",
};

const content = document.getElementById("page");
const overlay = document.getElementById("driving_lock");

const state = {
  availabilityController: undefined,
  cleanup: undefined,
  locked: true,
  pageVersion: 0,
  stylesheets: new Map(),
};

mountSidebar(document.getElementById("navigation"));

function leavePage() {
  state.pageVersion++;
  if (state.cleanup) {
    const closePage = state.cleanup;
    state.cleanup = null;
    closePage();
  }

  for (const dialog of document.querySelectorAll("dialog[open]")) {
    dialog.close();
  }

  content.replaceChildren();
  content.removeAttribute("aria-busy");
}

async function showPage() {
  leavePage();
  selectPage(location.pathname);
  if (state.locked) {
    return;
  }

  const page = pages[location.pathname];
  if (!page) {
    content.textContent = "Page not found.";
    return;
  }

  content.setAttribute("aria-busy", "true");
  const version = state.pageVersion;

  try {
    if (!state.stylesheets.has(page)) {
      state.stylesheets.set(page, new Promise((resolve, reject) => {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = `/assets/components/${page}.css`;
        link.onload = resolve;
        link.onerror = () => {
          state.stylesheets.delete(page);
          link.remove();
          reject(new Error("Could not load page styles."));
        };
        document.head.append(link);
      }));
    }

    const [module] = await Promise.all([import(`/assets/components/${page}.js`), state.stylesheets.get(page)]);
    if (version !== state.pageVersion || state.locked) {
      return;
    }

    state.cleanup = module.mount(content);
  } catch (error) {
    if (version === state.pageVersion && !state.locked) {
      content.textContent = `Could not open this page: ${error.message}`;
    }
  } finally {
    if (version === state.pageVersion) {
      content.removeAttribute("aria-busy");
    }
  }
}

function setLocked(value, reachable) {
  const changed = state.locked !== value;
  state.locked = value;
  overlay.hidden = !value;
  document.getElementById("app").inert = value;
  document.getElementById("menu_button").inert = value;

  const title = document.getElementById("lock_title");
  const message = document.getElementById("lock_message");
  if (reachable) {
    title.textContent = "The Pond is locked while driving";
    message.textContent = "Shift into Park to use The Pond.";
  } else {
    title.textContent = "Can't reach your device";
    message.textContent = "The Pond will reconnect automatically when your device is available.";
  }

  if (!changed) {
    return;
  }

  if (value) {
    state.availabilityController?.abort();
    selectPage(location.pathname);
    leavePage();
    overlay.focus();
  } else {
    state.availabilityController = new AbortController();
    updateAvailability(state.availabilityController.signal).catch(error => {
      if (error.name !== "AbortError") {
        console.error("Could not check vehicle features", error);
      }
    });
    showPage();
  }
}

async function checkDriving() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1500);

  try {
    const data = await fetchJson("/api/onroad", { signal: controller.signal });
    if (typeof data.onroad !== "boolean") {
      throw new Error("Invalid device state");
    }

    setLocked(data.onroad, true);
  } catch {
    setLocked(true, false);
  } finally {
    clearTimeout(timeout);
    setTimeout(checkDriving, 1000);
  }
}

window.addEventListener("popstate", showPage);

document.addEventListener("click", event => {
  const link = event.target.closest("a[href]");
  if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || link.target || link.hasAttribute("download")) {
    return;
  }

  const url = new URL(link.href);
  if (url.origin !== location.origin || !pages[url.pathname]) {
    return;
  }

  event.preventDefault();
  if (state.locked) {
    return;
  }

  history.pushState(null, "", url);
  window.scrollTo(0, 0);
  showPage();
});

document.fonts.ready.then(checkDriving);
