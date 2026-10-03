import { html } from "/assets/vendor/arrow.mjs";
import { fetchJson } from "/assets/js/api.js";

const sections = {
  Home: [["Home", "/", "house-fill"]],
  Navigation: [["Manage Keys", "/manage_navigation_keys", "key-fill"], ["Set Destination", "/set_navigation_destination", "globe-americas"]],
  Recordings: [["Dashcam Routes", "/dashcam_routes", "camera-reels"], ["Screen Recordings", "/screen_recordings", "record-circle"]],
  Tailscale: [["Tailscale", "/manage_tailscale", "wifi"]],
  Tools: [
    ["Download Speed Limits", "/download_speed_limits", "download"],
    ["Error Logs", "/manage_error_logs", "exclamation-triangle"],
    ["Lock/Unlock Doors", "/lock_or_unlock_doors", "door-closed"],
    ["Theme Maker", "/theme_maker", "palette-fill"],
    ["Tmux Log", "/manage_tmux", "terminal"],
    ["Toggles", "/manage_toggles", "toggle-on"],
    ["Toyota Security Keys", "/tsk_manager", "key-fill"],
  ],
};

export function mountSidebar(container) {
  html`
    <div id="sidebarUnderlay" class="hidden" @click="${() => toggleSidebar(false)}"></div>
    <nav id="sidebar" class="sidebar" aria-label="Main">
      <div>
        <div class="title">
          <img class="logo" src="/assets/images/main_logo.png" alt="FrogPilot logo">
          <div class="title_text sidebar_header">
            <p>The Pond</p>
            <a href="https://github.com/Aidenir" target="_blank" rel="noopener noreferrer">by Aidenir</a>
          </div>
        </div>
        <hr>
        ${Object.entries(sections).map(([section, links]) => html`
          <div class="sidebar_widget">
            <ul class="menu_section"><li>
              <span class="section-title">${() => section}</span>
              <ul>${links.map(([name, path, icon]) => html`
                <li hidden="${() => path === "/lock_or_unlock_doors" || path === "/tsk_manager"}">
                  <a class="menu-item-link" href="${() => path}"><i class="bi bi-${icon}" aria-hidden="true"></i><span>${() => name}</span></a>
                </li>
              `)}</ul>
            </li></ul>
          </div>
        `)}
      </div>
    </nav>
  `(container);

  document.getElementById("menu_button").addEventListener("click", () => {
    toggleSidebar(!document.getElementById("sidebar").classList.contains("visible"));
  });
}

export function toggleSidebar(visible) {
  document.getElementById("sidebar").classList.toggle("visible", visible);
  document.getElementById("sidebarUnderlay").classList.toggle("hidden", !visible);
  document.documentElement.classList.toggle("no_scroll", visible);

  const button = document.getElementById("menu_button");
  button.setAttribute("aria-expanded", String(visible));
  let label = "Open menu";
  if (visible) {
    label = "Close menu";
  }
  button.setAttribute("aria-label", label);
}

export function selectPage(path) {
  for (const link of document.querySelectorAll("#sidebar li a")) {
    const active = link.getAttribute("href") === path;
    link.parentElement.classList.toggle("active", active);
    if (active) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  }

  toggleSidebar(false);
}

export async function updateAvailability(signal) {
  const features = [["/api/doors_available", "/lock_or_unlock_doors"], ["/api/tsk_available", "/tsk_manager"]];

  await Promise.all(features.map(async ([url, path]) => {
    const data = await fetchJson(url, { signal });
    if (!signal.aborted) {
      document.querySelector(`#sidebar a[href="${path}"]`).parentElement.hidden = !data.result;
    }
  }));
}
