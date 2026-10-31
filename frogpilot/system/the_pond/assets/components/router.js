import { fetchJson } from "/assets/js/api.js";
import { mountSidebar, selectPage, updateAvailability } from "/assets/components/sidebar.js";

const pages = {
  "/": "home/home",
  "/dashcam_routes": "recordings/dashcam_routes",
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

const pairingForm = document.getElementById("pairing_form");
const pairingBoxes = [...pairingForm.querySelectorAll("input")];
const pairingMessage = document.getElementById("pairing_message");

const state = {
  availabilityController: undefined,
  cleanup: undefined,
  locked: true,
  pageVersion: 0,
  pairing: false,
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

function setLocked(value, reachable, pairing) {
  const changed = state.locked !== value;
  const pairingStarted = pairing && !state.pairing;
  state.locked = value;
  state.pairing = pairing;
  overlay.hidden = !value;
  pairingForm.hidden = !pairing;
  document.getElementById("app").inert = value;
  document.getElementById("menu_button").inert = value;

  const title = document.getElementById("lock_title");
  const message = document.getElementById("lock_message");
  if (pairing) {
    title.textContent = "Pair this browser";
    message.textContent = "Enter the 6-digit code shown next to “Manage Your Settings At” in the car's Navigation settings.";
  } else if (reachable) {
    title.textContent = "The Pond is locked while driving";
    message.textContent = "Shift into Park to use The Pond.";
  } else {
    title.textContent = "Can't reach your device";
    message.textContent = "The Pond will reconnect automatically when your device is available.";
  }

  if (pairingStarted) {
    for (const box of pairingBoxes) {
      box.value = "";
    }

    pairingMessage.textContent = "Turning pairing off and back on makes a new one.";
    pairingBoxes[0].focus();
  }

  if (!changed) {
    return;
  }

  if (value) {
    state.availabilityController?.abort();
    selectPage(location.pathname);
    leavePage();

    if (!pairing) {
      overlay.focus();
    }
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

    const pairing = !data.onroad && !data.paired;
    setLocked(data.onroad || pairing, true, pairing);
  } catch {
    setLocked(true, false, false);
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

for (let index = 0; index < pairingBoxes.length; index++) {
  const box = pairingBoxes[index];

  box.addEventListener("input", () => {
    box.value = box.value.replace(/\D/g, "").slice(0, 1);
    if (box.value && index < 5) {
      pairingBoxes[index + 1].focus();
    }
  });

  box.addEventListener("keydown", event => {
    if (event.key === "Backspace" && !box.value && index > 0) {
      pairingBoxes[index - 1].focus();
    }
  });

  box.addEventListener("paste", event => {
    const digits = event.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
    if (!digits) {
      return;
    }

    event.preventDefault();
    for (let digit = 0; digit < digits.length; digit++) {
      pairingBoxes[digit].value = digits[digit];
    }

    pairingBoxes[Math.min(5, digits.length)].focus();
  });
}

pairingForm.addEventListener("submit", async event => {
  event.preventDefault();

  let code = "";
  for (const box of pairingBoxes) {
    code += box.value;
  }

  if (code.length < 6) {
    pairingMessage.textContent = "Enter all 6 digits.";
    return;
  }

  const button = pairingForm.querySelector("button");
  button.disabled = true;

  try {
    await fetchJson("/api/pair", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) });
    pairingMessage.textContent = "Paired. Welcome to The Pond.";
  } catch (error) {
    pairingMessage.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

document.fonts.ready.then(checkDriving);
