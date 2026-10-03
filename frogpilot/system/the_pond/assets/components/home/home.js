import { html, reactive } from "/assets/vendor/arrow.mjs";
import { fetchJson } from "/assets/js/api.js";

export function mount(container) {
  const controller = new AbortController();
  const state = reactive({ data: null, error: "" });
  const format = value => (value || 0).toLocaleString("en-US", { maximumFractionDigits: 0 });

  fetchJson("/api/stats", { signal: controller.signal }).then(data => {
    state.data = data;
  }).catch(error => {
    if (!controller.signal.aborted) {
      state.error = error.message;
    }
  });

  html`
    <h1>The Pond</h1>
    ${() => {
      if (state.error) {
        return html`<p class="error" role="alert">${() => state.error}</p>`;
      }

      const diskUsage = state.data?.diskUsage || [{ used: "0 GB", size: "0 GB", usedPercentage: 0 }];
      const driveStats = state.data?.driveStats;
      const softwareInfo = state.data?.softwareInfo;
      const fields = [
        ["Branch Name", softwareInfo?.branchName || "..."], ["Build", softwareInfo?.buildEnvironment || "..."],
        ["Commit Hash", softwareInfo ? html`
          <a href="${() => softwareInfo.commitUrl}" target="_blank" rel="noopener noreferrer">${() => softwareInfo.commitHash}</a>
        ` : "0".repeat(40)],
        ["Fork Maintainer", softwareInfo?.forkMaintainer || "..."], ["Update Available", softwareInfo?.updateAvailable || "..."],
        ["Version Date", softwareInfo?.versionDate || "..."],
      ];

      return html`
        <section class="drivingStats" aria-label="Driving statistics" aria-busy="${() => !state.data}">
          ${[["All Time", "all"], ["Past Week", "week"], ["FrogPilot", "frogpilot"]].map(([title, key]) => html`
            <div class="drivingStat">
              <h2>${() => title}</h2>
              <div><p>${() => format(driveStats?.[key].drives)}</p><p>drives</p></div>
              <div><p>${() => format(driveStats?.[key].distance)}</p><p>${() => driveStats?.[key].unit || "distance"}</p></div>
              <div><p>${() => format(driveStats?.[key].hours)}</p><p>hours</p></div>
            </div>
          `)}
        </section>
        <h2>Disk Usage</h2>
        <section class="diskUsage" aria-busy="${() => !state.data}">
          ${diskUsage.map(disk => html`
            <div class="disk">
              <p>${() => disk.used} used of ${() => disk.size}</p>
              <div class="progress" role="meter" aria-label="Disk space used" aria-valuemin="0" aria-valuemax="100"
                aria-valuenow="${() => parseFloat(disk.usedPercentage)}">
                <div class="bar" style="${() => `width: ${100 - Math.min(100, Math.max(0, parseFloat(disk.usedPercentage)))}%`}"></div>
              </div>
            </div>
          `)}
        </section>
        <h2>Software Info</h2>
        <section class="softwareInfo" aria-busy="${() => !state.data}"><div class="softwareGrid">
          ${fields.map(([label, value]) => html`<p><strong>${() => label}:</strong> ${() => value}</p>`)}
        </div></section>
      `.key(state.data ? "loaded" : "loading");
    }}
  `(container);

  return () => controller.abort();
}
