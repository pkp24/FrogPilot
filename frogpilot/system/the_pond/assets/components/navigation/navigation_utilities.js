import { fetchJson } from "/assets/js/api.js";

let mapboxLoading;

export function loadMapbox() {
  if (!mapboxLoading) {
    mapboxLoading = new Promise((resolve, reject) => {
      const stylesheet = document.createElement("link");
      stylesheet.rel = "stylesheet";
      stylesheet.href = "/assets/vendor/mapbox-gl/mapbox-gl.css";

      const script = document.createElement("script");
      script.src = "/assets/vendor/mapbox-gl/mapbox-gl.js";
      Promise.all([stylesheet, script].map(element => new Promise((resolve, reject) => {
        element.onload = resolve;
        element.onerror = reject;
      }))).then(() => {
        resolve(window.mapboxgl);
      }, () => {
        mapboxLoading = null;
        script.remove();
        stylesheet.remove();
        reject(new Error("The map library could not be loaded. Please retry."));
      });

      document.head.append(stylesheet, script);
    });
  }

  return mapboxLoading;
}

export async function fetchMapbox(path, token, query, signal) {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal.addEventListener("abort", cancel, { once: true });
  if (signal.aborted) {
    controller.abort();
  }

  const timeout = setTimeout(() => controller.abort(new Error("Mapbox did not respond. Please retry.")), 10000);

  try {
    const parameters = new URLSearchParams({ ...query, access_token: token });
    return await fetchJson(`https://api.mapbox.com/${path}?${parameters}`, { signal: controller.signal });
  } finally {
    clearTimeout(timeout);
    signal.removeEventListener("abort", cancel);
  }
}

export function coordinatesOf(value) {
  if (!value || [value.latitude, value.longitude].some(coordinate => typeof coordinate !== "number"
    && (typeof coordinate !== "string" || !coordinate.trim()))) {
    return null;
  }

  const latitude = Number(value.latitude);
  const longitude = Number(value.longitude);
  if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90 || !Number.isFinite(longitude) || longitude < -180 || longitude > 180) {
    return null;
  }

  return [longitude, latitude];
}

export function formatDistance(meters, metric) {
  if (metric) {
    if (meters >= 1000) {
      return `${(meters / 1000).toFixed(1)} km`;
    }

    return `${Math.round(meters)} m`;
  }

  if (meters >= 1609.344) {
    return `${(meters / 1609.344).toFixed(1)} mi`;
  }

  return `${Math.round(meters * 3.28084)} ft`;
}

export function formatDuration(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  if (hours) {
    return `${hours}h ${minutes} min`;
  }

  return `${minutes} min`;
}

export function formatArrival(seconds) {
  const arrival = new Date(Date.now() + seconds * 1000);
  const options = { hour: "numeric", minute: "2-digit" };
  if (seconds > 86400) {
    Object.assign(options, { month: "long", day: "numeric", year: "numeric" });
  }

  return arrival.toLocaleString([], options);
}

export function congestionGradient(route) {
  const colors = { low: "#2ecc71", moderate: "#f1c40f", heavy: "#e67e22", severe: "#e74c3c", unknown: "#2ecc71" };
  const congestion = route.legs?.flatMap(leg => leg.annotation?.congestion || []) || [];
  if (congestion.length < 2) {
    const color = colors[congestion[0]] || "#ccc";
    return ["interpolate", ["linear"], ["line-progress"], 0, color, 1, color];
  }

  const gradient = ["interpolate", ["linear"], ["line-progress"]];
  congestion.forEach((level, index) => gradient.push(index / (congestion.length - 1), colors[level] || "#999"));

  return gradient;
}

export function drawRoutes(map, routes, metric, onSelect) {
  const handlers = [];
  let popup;
  let selected = 0;

  function highlight(index) {
    selected = index;
    routes.forEach((route, current) => {
      const layer = `route-line-${current}`;
      map.setPaintProperty(layer, "line-width", current === index ? 5 : 3);
      map.setPaintProperty(layer, "line-opacity", current === index ? 1 : 0.5);
    });

    map.moveLayer(`route-line-${index}`);
  }

  function showDetails(event, route) {
    popup?.remove();

    const content = document.createElement("div");
    for (const [icon, label, value] of [
      ["🛣️", "Distance:", formatDistance(route.distance, metric)], ["⌛", "Duration:", formatDuration(route.duration)],
      ["🕗", "ETA:", formatArrival(route.duration)],
    ]) {
      const row = document.createElement("div");
      row.className = "tooltip-row";

      for (const text of [icon, label, value]) {
        const span = document.createElement("span");
        span.textContent = text;
        row.append(span);
      }

      content.append(row);
    }

    popup = new window.mapboxgl.Popup({ closeButton: false, closeOnClick: true, className: "route-tooltip", maxWidth: "none" })
      .setLngLat(event.lngLat).setDOMContent(content).addTo(map);
  }

  routes.forEach((route, index) => {
    const source = `route-${index}`;
    const layer = `route-line-${index}`;
    const hitLayer = `route-click-${index}`;

    map.addSource(source, { type: "geojson", lineMetrics: true, data: { type: "Feature", properties: {}, geometry: route.geometry } });
    map.addLayer({ id: layer, type: "line", source, layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-width": 3, "line-opacity": 0.5, "line-gradient": congestionGradient(route) } });
    map.addLayer({ id: hitLayer, type: "line", source, paint: { "line-width": 20, "line-opacity": 0 } });

    const events = {
      click: event => {
        event.preventDefault();
        highlight(index);
        onSelect(index);
        showDetails(event, route);
      },
      mouseenter: event => {
        map.getCanvas().style.cursor = "pointer";
        map.setPaintProperty(layer, "line-width", 5);
        map.setPaintProperty(layer, "line-opacity", 1);
        showDetails(event, route);
      },
      mouseleave: () => {
        map.getCanvas().style.cursor = "";
        popup?.remove();
        highlight(selected);
      },
    };

    for (const [event, handler] of Object.entries(events)) {
      map.on(event, hitLayer, handler);
      handlers.push([event, hitLayer, handler]);
    }
  });

  highlight(0);

  return {
    select: highlight,
    remove() {
      popup?.remove();
      for (const [event, layer, handler] of handlers) {
        map.off(event, layer, handler);
      }

      routes.forEach((route, index) => {
        for (const layer of [`route-click-${index}`, `route-line-${index}`]) {
          if (map.getLayer(layer)) {
            map.removeLayer(layer);
          }
        }

        if (map.getSource(`route-${index}`)) {
          map.removeSource(`route-${index}`);
        }
      });
    },
  };
}
