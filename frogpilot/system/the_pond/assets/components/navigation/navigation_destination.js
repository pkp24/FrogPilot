import { html, reactive } from "/assets/vendor/arrow.mjs";
import { fetchJson } from "/assets/js/api.js";
import { confirmDialog } from "/assets/components/modal.js";
import { showSnackbar } from "/assets/js/snackbar.js";
import { coordinatesOf, drawRoutes, fetchMapbox, formatArrival, formatDistance, formatDuration, loadMapbox } from "./navigation_utilities.js";

export function mount(container) {
  const controller = new AbortController();
  const state = reactive({ stage: "loading", error: "", mapError: "", ready: false, search: "", searching: false, suggestions: [], favorites: [],
    favoritesVisible: false, routeLoading: false, routeError: "", preview: 0, selected: 0, sent: false, busy: false });
  const sessionToken = crypto.randomUUID?.() || Math.random().toString(36).slice(2);

  let map;
  let token;
  let position;
  let metric = true;
  let previous = [];
  let selectedDestination;
  let routes = [];
  let routeLayers;
  let destinationMarker;
  let favoriteMarkers = [];

  let searchTimer;
  let searchController;
  let routeController;

  function releaseMap() {
    routeController?.abort();
    routeLayers?.remove();
    routeLayers = null;
    destinationMarker?.remove();
    destinationMarker = null;
    favoriteMarkers.forEach(marker => marker.remove());
    favoriteMarkers = [];

    map?.remove();
    map = null;
    state.ready = false;
  }

  function clearPreview() {
    routeController?.abort();
    routeLayers?.remove();
    routeLayers = null;
    destinationMarker?.remove();
    destinationMarker = null;

    routes = [];
    selectedDestination = null;
    state.routeLoading = false;
    state.routeError = "";
    state.sent = false;
    state.preview++;
  }

  async function mutate(url, method, data) {
    const options = { method };
    if (data) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(data);
    }

    return fetchJson(url, options);
  }

  async function action(operation) {
    if (state.busy || controller.signal.aborted) {
      return;
    }

    state.busy = true;

    try {
      await operation();
    } catch (error) {
      if (!controller.signal.aborted) {
        showSnackbar(error.message, "error");
      }
    } finally {
      state.busy = false;
    }
  }

  function showFavoriteMarkers() {
    favoriteMarkers.forEach(marker => marker.remove());
    favoriteMarkers = [];
    if (!map || !state.ready) {
      return;
    }

    for (const favorite of state.favorites) {
      const coordinates = coordinatesOf(favorite);
      if (!coordinates) {
        continue;
      }

      const element = document.createElement("button");
      element.className = "favorite-marker";
      element.type = "button";
      element.textContent = "❤️";
      let label = favorite.name || "Unnamed Location";
      if (favorite.is_home) {
        element.textContent = "🏠";
        label = `Home: ${label}`;
      } else if (favorite.is_work) {
        element.textContent = "💼";
        label = `Work: ${label}`;
      }
      element.setAttribute("aria-label", `Preview ${label}`);

      const popup = new window.mapboxgl.Popup({ offset: 25, closeButton: false }).setText(label);
      const marker = new window.mapboxgl.Marker(element).setLngLat(coordinates).setPopup(popup).addTo(map);

      element.addEventListener("click", event => {
        event.stopPropagation();
        popup.remove();
        chooseDestination(favorite);
      });
      element.addEventListener("mouseenter", () => {
        popup.setLngLat(coordinates).addTo(map);
      });
      element.addEventListener("mouseleave", () => popup.remove());

      favoriteMarkers.push(marker);
    }
  }

  async function loadFavorites() {
    const result = await fetchJson("/api/navigation/favorite", { signal: controller.signal });
    if (!controller.signal.aborted) {
      state.favorites = result.favorites.sort((left, right) => (left.name || "").localeCompare(right.name || ""));
      showFavoriteMarkers();
    }
  }

  async function editFavorite(favorite, operation) {
    await action(async () => {
      let result;
      if (operation === "remove") {
        const confirmed = await confirmDialog("Remove Favorite", `Remove ${favorite.name} from your favorites?`, { confirmText: "Remove", danger: true });
        if (!confirmed || controller.signal.aborted) {
          return;
        }

        result = await mutate("/api/navigation/favorite", "DELETE", { id: favorite.id });
      } else if (operation === "rename") {
        const name = await confirmDialog("Rename Favorite", `Rename ${favorite.name}:`, { confirmText: "Rename", inputValue: favorite.name });
        if (!name || name === favorite.name || controller.signal.aborted) {
          return;
        }

        result = await mutate("/api/navigation/favorite/rename", "POST", { id: favorite.id, name });
      } else {
        result = await mutate("/api/navigation/favorite/rename", "POST", { id: favorite.id, [operation]: !favorite[operation] });
      }

      if (!controller.signal.aborted) {
        await loadFavorites();
        showSnackbar(result.message, "success");
      }
    });
  }

  function currentFavorite() {
    if (!selectedDestination) {
      return null;
    }

    return state.favorites.find(favorite => Number(favorite.longitude) === selectedDestination.longitude
      && Number(favorite.latitude) === selectedDestination.latitude);
  }

  function toggleFavorite() {
    const favorite = currentFavorite();
    if (favorite) {
      editFavorite(favorite, "remove");
      return;
    }

    action(async () => {
      const result = await mutate("/api/navigation/favorite", "POST", { ...selectedDestination, routeId: state.selected ? `alt-${state.selected}` : "main" });
      if (!controller.signal.aborted) {
        await loadFavorites();
        showSnackbar(result.message, "success");
      }
    });
  }

  async function searchPlaces(value) {
    clearTimeout(searchTimer);
    searchController?.abort();
    clearPreview();

    const current = new AbortController();
    searchController = current;
    state.searching = true;
    state.routeError = "";

    try {
      const result = await fetchMapbox("search/searchbox/v1/suggest", token, {
        q: value, proximity: position.join(","), session_token: sessionToken, limit: 4,
      }, current.signal);

      if (!current.signal.aborted && !controller.signal.aborted) {
        state.suggestions = result.suggestions || [];
      }
    } catch (error) {
      if (!current.signal.aborted && !controller.signal.aborted) {
        state.routeError = error.message || "Search failed. Please retry.";
      }
    } finally {
      if (searchController === current) {
        state.searching = false;
      }
    }
  }

  function searchInput(event) {
    state.search = event.target.value;
    state.favoritesVisible = false;

    searchController?.abort();
    clearTimeout(searchTimer);
    clearPreview();

    const value = state.search.trim();
    state.suggestions = [];
    state.searching = false;
    if (!value) {
      state.suggestions = previous;
    } else if (value.length >= 3) {
      searchTimer = setTimeout(() => searchPlaces(value), 800);
    }
  }

  async function chooseDestination(suggestion, resume = false) {
    if (!state.ready || controller.signal.aborted) {
      return;
    }

    clearTimeout(searchTimer);
    searchController?.abort();
    clearPreview();

    const current = new AbortController();
    routeController = current;
    state.routeLoading = true;
    state.searching = false;
    state.favoritesVisible = false;
    state.suggestions = [];
    const name = suggestion.full_address || suggestion.name || suggestion.address || "Unnamed Location";
    state.search = name;

    try {
      let coordinates = coordinatesOf(suggestion);
      if (!coordinates) {
        coordinates = suggestion.geometry?.coordinates;
      }

      if (!coordinates) {
        let result;
        if (suggestion.mapbox_id) {
          result = await fetchMapbox(`search/searchbox/v1/retrieve/${encodeURIComponent(suggestion.mapbox_id)}`, token,
            { session_token: sessionToken }, current.signal);
        } else {
          result = await fetchMapbox("search/geocode/v6/forward", token, { q: name }, current.signal);
        }
        coordinates = result.features?.[0]?.geometry?.coordinates;
      }

      if (!Array.isArray(coordinates) || !coordinatesOf({ longitude: coordinates[0], latitude: coordinates[1] })) {
        throw new Error("Could not find this destination. Try another search.");
      }

      const result = await fetchMapbox(`directions/v5/mapbox/driving-traffic/${position.join(",")};${coordinates.join(",")}`, token,
        { geometries: "geojson", annotations: "congestion", overview: "full", alternatives: "true" }, current.signal);
      if (current.signal.aborted || controller.signal.aborted) {
        return;
      }

      routes = (result.routes || []).filter(route => Number.isFinite(route.distance) && Number.isFinite(route.duration)
        && route.geometry?.type === "LineString" && route.geometry.coordinates?.length >= 2);
      if (!routes.length) {
        throw new Error("No driving route found. Try a different destination.");
      }

      selectedDestination = { name, longitude: Number(coordinates[0]), latitude: Number(coordinates[1]) };
      destinationMarker = new window.mapboxgl.Marker().setLngLat(coordinates).addTo(map);
      routeLayers = drawRoutes(map, routes, metric, index => {
        state.selected = index;
      });
      state.selected = 0;
      state.sent = resume;
      state.preview++;

      const padding = Math.min(250, Math.max(40, Math.min(container.clientWidth, container.clientHeight) / 5));
      map.fitBounds([position, coordinates], { padding, duration: 1000 });
    } catch (error) {
      if (!current.signal.aborted && !controller.signal.aborted) {
        state.routeError = error.message || "Could not calculate the route. Please retry.";
      }
    } finally {
      if (routeController === current) {
        state.routeLoading = false;
      }
    }
  }

  function sendDestination() {
    const destination = { ...selectedDestination };
    action(async () => {
      const result = await mutate("/api/navigation", "POST", destination);
      if (!controller.signal.aborted) {
        if (selectedDestination?.longitude === destination.longitude && selectedDestination?.latitude === destination.latitude) {
          state.sent = true;
        }

        showSnackbar(result.message, "success");
        map.flyTo({ center: position, zoom: 18, pitch: 45, speed: 1, curve: 1 });
      }
    });
  }

  function cancelNavigation() {
    action(async () => {
      const result = await mutate("/api/navigation", "DELETE");
      if (!controller.signal.aborted) {
        clearPreview();
        state.search = "";
        state.suggestions = previous;
        map.flyTo({ center: position, zoom: 15, pitch: 45, speed: 1, curve: 1 });
        showSnackbar(result.message, "success");
      }
    });
  }

  async function initialize() {
    state.stage = "loading";
    state.error = "";
    state.mapError = "";

    clearPreview();
    releaseMap();

    try {
      const data = await fetchJson("/api/navigation", { signal: controller.signal });
      if (controller.signal.aborted) {
        return;
      }

      token = (data.mapboxPublic || "").trim();
      if (!token || !data.mapboxSecretSet) {
        state.stage = "keys";
        return;
      }

      position = coordinatesOf(data.lastPosition);
      if (!position) {
        state.stage = "position";
        return;
      }

      if (position[0] === 0 && position[1] === 0) {
        position = [30.221928335547232, 51.276824158421331]; // Chernobyl
      }

      metric = data.isMetric;
      previous = [];
      try {
        const destinations = JSON.parse(data.previousDestinations || "[]");
        if (Array.isArray(destinations)) {
          previous = destinations.map(destination => ({ name: destination.place_name || destination.name, geometry: destination.geometry }));
        }
      } catch {
        previous = [];
      }

      let existingDestination;
      try {
        existingDestination = JSON.parse(data.destination || "null");
      } catch {
        existingDestination = null;
      }

      const mapbox = await loadMapbox();
      if (controller.signal.aborted) {
        return;
      }

      state.stage = "ready";
      state.suggestions = previous;
      await Promise.resolve();
      if (controller.signal.aborted) {
        return;
      }

      mapbox.accessToken = token;
      map = new mapbox.Map({ container: container.querySelector("#map"), center: position, zoom: 15, pitch: 45,
        attributionControl: false, logoPosition: "bottom-right", style: "mapbox://styles/frogsgomoo/cmcfv151j000o01rcdxebhl76" });
      new mapbox.Marker().setLngLat(position).addTo(map);

      map.on("style.load", () => {
        if (!map.getSource("composite") || map.getLayer("add-3d-buildings")) {
          return;
        }

        const label = map.getStyle().layers.find(layer => layer.type === "symbol" && layer.layout?.["text-field"]);
        map.addLayer({ id: "add-3d-buildings", source: "composite", "source-layer": "building", type: "fill-extrusion", minzoom: 15,
          filter: ["==", "extrude", "true"], paint: { "fill-extrusion-color": "#aaa", "fill-extrusion-opacity": 0.6,
            "fill-extrusion-height": ["interpolate", ["linear"], ["zoom"], 15, 0, 15.05, ["get", "height"]],
            "fill-extrusion-base": ["interpolate", ["linear"], ["zoom"], 15, 0, 15.05, ["get", "min_height"]] } }, label?.id);
      });

      map.on("error", event => {
        if (controller.signal.aborted) {
          return;
        }

        if (!state.ready && (event.error?.status === 401 || event.error?.status === 403)) {
          state.error = "Mapbox rejected the public key. Check your public token and its permissions in Manage Navigation Keys.";
          state.stage = "keys";
          releaseMap();
          return;
        }

        state.mapError = "Some map data could not load. Check your connection or retry the map.";
      });

      map.on("load", () => {
        if (controller.signal.aborted) {
          return;
        }

        state.ready = true;
        state.mapError = "";
        map.resize();
        map.flyTo({ center: position, zoom: 18, pitch: 45, speed: 1, curve: 1 });
        showFavoriteMarkers();
        if (coordinatesOf(existingDestination)) {
          chooseDestination(existingDestination, true);
        }
      });

      try {
        await loadFavorites();
      } catch (error) {
        if (!controller.signal.aborted) {
          showSnackbar(`Could not load favorites: ${error.message}`, "error");
        }
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        state.error = error.message;
        state.stage = "error";
        releaseMap();
      }
    }
  }

  function suggestions() {
    return html`<div id="searchSuggestions">${() => {
      let entries = state.suggestions;
      if (state.favoritesVisible) {
        entries = state.favorites;
      }

      return entries.map(suggestion => html`<div class="suggestion-item">
      <button type="button" class="suggestion-select" disabled="${() => !state.ready || state.busy}"
        @click="${() => chooseDestination(suggestion)}">
        ${() => `${suggestion.is_home ? "🏠 " : suggestion.is_work ? "💼 " : ""}${suggestion.name || suggestion.address}`}
      </button>${() => state.favoritesVisible ? html`<div class="favorite-actions">
        <button type="button" class="${() => `home-favorite-button ${suggestion.is_home ? "active" : ""}`}"
          aria-label="${() => `${suggestion.is_home ? "Remove Home status from" : "Set Home to"} ${suggestion.name}`}"
          disabled="${() => state.busy}" @click="${() => editFavorite(suggestion, "is_home")}">🏠</button>
        <button type="button" class="${() => `work-favorite-button ${suggestion.is_work ? "active" : ""}`}"
          aria-label="${() => `${suggestion.is_work ? "Remove Work status from" : "Set Work to"} ${suggestion.name}`}"
          disabled="${() => state.busy}" @click="${() => editFavorite(suggestion, "is_work")}">💼</button>
        <button type="button" class="edit-favorite-button" aria-label="${() => `Rename ${suggestion.name}`}"
          disabled="${() => state.busy}" @click="${() => editFavorite(suggestion, "rename")}">✏️</button>
        <button type="button" class="remove-favorite-button" aria-label="${() => `Remove ${suggestion.name} from favorites`}"
          disabled="${() => state.busy}" @click="${() => editFavorite(suggestion, "remove")}">🗑️</button></div>` : ""}
    </div>`);
    }}</div>`;
  }

  function routeSummary() {
    const route = routes[state.selected];
    if (!route || !selectedDestination) {
      return "";
    }

    return html`<section class="navigation-summary-widget"><h2 class="navigation-summary-title">${() => selectedDestination.name}</h2>
      <div class="summary-row"><span class="emoji">🛣️</span><span>Distance:</span>
        <span>${() => formatDistance(routes[state.selected].distance, metric)}</span></div>
      <div class="summary-row"><span class="emoji">⌛</span><span>Duration:</span>
        <span>${() => formatDuration(routes[state.selected].duration)}</span></div>
      <div class="summary-row"><span class="emoji">🕗</span><span>ETA:</span>
        <span>${() => formatArrival(routes[state.selected].duration)}</span></div>
      ${routes.length > 1 ? html`<label class="navigation-alternatives">Route preview<select value="${() => state.selected}"
        @change="${event => {
          state.selected = Number(event.target.value);
          routeLayers.select(state.selected);
        }}">
        ${routes.map((alternative, index) => html`<option value="${() => index}">${() => `${index + 1}: ${formatDuration(alternative.duration)}`}</option>`)}
      </select></label>` : ""}
      <p>FrogPilot calculates its own route. Map alternatives are previews.</p>
      <p role="status">${() => state.sent ? "Destination sent to FrogPilot." : ""}</p>
      <div class="buttonCluster"><button class="directions" type="button" disabled="${() => state.busy || state.sent}"
        @click="${sendDestination}">Send Destination</button>
        <button class="cancel" type="button" disabled="${() => state.busy}" @click="${cancelNavigation}">Clear Navigation</button>
        <button class="favorite" type="button" disabled="${() => state.busy}" @click="${toggleFavorite}">
          ${() => currentFavorite() ? "💔 Remove Favorite" : "❤️ Add Favorite"}</button></div>
    </section>`;
  }

  html`<div class="navigation-container">${() => {
    if (state.stage === "ready" || state.stage === "loading") {
      return "";
    }

    let title = "Navigation Unavailable";
    let message = state.error;
    if (state.stage === "keys") {
      title = "Check Mapbox Keys";
      message = state.error || "Set valid public and secret Mapbox keys before using navigation.";
    } else if (state.stage === "position") {
      title = "Waiting for Location";
      message = "The map will be available after the device receives a GPS position.";
    }

    return html`<section class="keys-required-wrapper"><div class="keys-required-widget"><h1 class="keys-required-title">${() => title}</h1>
      <p class="keys-required-text" role="status">${() => message}</p>
      ${state.stage === "keys" ? html`<a href="/manage_navigation_keys" class="keys-required-button">Manage Navigation Keys</a>`
      : html`<button type="button" class="keys-required-button" @click="${initialize}">Retry</button>`}
    </div></section>`;
  }}<div class="map-wrapper" hidden="${() => state.stage !== "ready" && state.stage !== "loading"}" aria-busy="${() => !state.ready}">
    <div class="search-wrapper"><div class="search-controls">
    <input id="search-field" aria-label="Search for a destination" autocomplete="off" placeholder="Search places or addresses"
      value="${() => state.search}" disabled="${() => !state.ready || state.busy}" @input="${searchInput}" @keydown="${event => {
        if (event.key === "Enter" && state.search.trim().length >= 3) {
          event.preventDefault();
          searchPlaces(state.search.trim());
        }
      }}" />
    <button type="button" class="favorites-toggle-button" aria-pressed="${() => state.favoritesVisible}"
      disabled="${() => !state.ready || state.busy}" @click="${() => {
        clearTimeout(searchTimer);
        searchController?.abort();
        clearPreview();
        state.searching = false;

        state.favoritesVisible = !state.favoritesVisible;
        state.search = "";
        state.suggestions = previous;
      }}">❤️ Favorites</button></div><p class="navigation-privacy-note">Destination searches and routes are sent to Mapbox.</p>
    ${() => state.mapError ? html`<div class="navigation-summary-widget" role="alert">${() => state.mapError}
      <button type="button" @click="${initialize}">Retry map</button></div>` : ""}
    <div id="infobox">${() => {
      state.preview;
      if (!state.ready) {
        return "";
      }

      if (state.routeLoading || state.searching) {
        let message = "Searching";
        if (state.routeLoading) {
          message = "Calculating route";
        }
        return html`<div class="navigation-summary-widget navigation-loading" role="status" aria-label="${() => message}" aria-busy="true">
          <span>${() => state.search}</span><span>...</span></div>`;
      }

      if (state.routeError) {
        return html`<div class="navigation-summary-widget" role="alert">${() => state.routeError}</div>`;
      }

      if (selectedDestination) {
        return routeSummary();
      }

      if (state.favoritesVisible && !state.favorites.length) {
        return html`<div class="navigation-summary-widget">No favorites yet. Preview a destination to add one.</div>`;
      }

      if (state.suggestions.length || state.favoritesVisible) {
        return suggestions();
      }

      if (state.search.trim().length >= 3) {
        return html`<div class="navigation-summary-widget">No results found. Try a different search.</div>`;
      }

      return "";
    }}</div></div><div class="navigation-map" aria-label="Navigation map"
      aria-busy="${() => !state.ready}" inert="${() => !state.ready}">
      <div id="map"></div></div></div></div>`(container);

  initialize();

  return () => {
    controller.abort();
    clearTimeout(searchTimer);
    searchController?.abort();
    releaseMap();

    container.replaceChildren();
  };
}
