# The Pond

The Pond is FrogPilot's web interface. Use it to browse recordings, set a navigation destination,
make themes, read logs, manage toggles and access the device tools from a phone or computer.

The manager starts it automatically. On the device, open `http://ThePond.local` or
`http://<device-ip>:8082`. The device advertises ThePond.local through mDNS and redirects port 80
to 8082. PC mode uses `http://localhost:8083` and doesn't install the redirect or advertise mDNS.

## Features

- Home shows driving statistics, storage usage and software information.
- Navigation manages Mapbox and AMap keys, searches destinations, previews routes, and saves favorites,
  Home and Work. Send Destination sends a destination to FrogPilot, which calculates its own route.
- Dashcam Routes plays available camera segments, combines footage for download, and manages route names,
  preservation and deletion. Up to five whole routes can have retention priority. Critical storage
  cleanup can still remove them. Bulk deletion keeps preserved routes unless explicitly included.
- Screen Recordings plays, downloads, renames and deletes completed captures from the on-device recorder.
- Theme Maker edits colors, images, sounds and signals. It previews assets and supports ordered signal
  frames. Load into editor, Save on device, Apply to device and Submit for community use are separate
  actions. Save and Apply change selected categories; unselected categories are retained.
- Tools view/copy/download error logs, stream or save tmux output, back up/restore/reset toggles, and
  export collected speed limits. Supported vehicles also expose door control and Toyota security keys.
- Tailscale installs and manages its own installation and provides the sign-in handoff. Installations
  managed elsewhere are left alone.

## Implementation

One threaded Flask application serves the API and local assets. The frontend uses browser ES modules,
vendored Arrow templates and a fixed page map. There's no frontend build step. Page modules export
`mount(container)` and return a cleanup function for their requests, streams, playback and previews.
Theme Maker intentionally keeps its editor draft across page navigation.

`DeviceState` owns the shared device operation locks. `MediaProcessor` owns media conversion,
worker limits, output locks and caches. Python imports stay at the top, with FrogPilot imports
in their own section; related declarations are grouped and alphabetized.

| File | Responsibility |
| --- | --- |
| `the_pond.py` | Application setup, request gates, response headers and startup |
| `device.py` | Device state, statistics, Params, toggles, doors and security keys |
| `discovery.py` | mDNS and the device port redirect |
| `logs.py` | Error logs and saved/live tmux output |
| `media.py` | Recordings, routes, previews, downloads and file ownership |
| `navigation.py` | Destinations, favorites and navigation keys |
| `tailscale.py` | Managed installation, sign-in handoff and removal |
| `themes.py` | Theme assets, selected-category save/apply and download handoff |
| `../../common/frogpilot_api.py` | Community submission and upload protocols |
| `helpers.py` | Shared request, name, path and origin checks |
| `assets/components/` | Shell and page modules/styles |
| `assets/js/` | Shared requests, formatting and notifications |

Mapbox GL, fonts, icons and Arrow are served locally. Map/search/routing still use Mapbox services.
Tailscale installation downloads official packages and verifies their checksum. Community theme
submission uses the existing FrogPilot API and its returned upload destinations.

## Access and driving state

The Pond has no separate login and uses HTTP. Any client that can reach its port can access it while
unlocked. Host, Origin/Referer and browser security headers limit browser-originated requests; they
aren't a substitute for controlling network access. Keep backups private because they contain settings.
Stored secret Mapbox/AMap and Toyota security key values aren't returned by their management pages.

The whole interface and feature API lock while driving, when Park isn't confirmed, or when device state
is unknown/stale. Offroad or confirmed Park allows general use. Only the shell, local application assets
and state check remain available while locked. Leaving a page or entering lockout stops its disposable
work; streamed feature responses also recheck state. Already-started file mutations settle safely.
Door commands and toggle resets require offroad state even in Park.

## Development

Run in an existing openpilot environment with:

```sh
python -m openpilot.frogpilot.system.the_pond.the_pond
```

Device operations affect Params, recordings, themes and system services. Use isolated temporary data
and replace hardware/external-service boundaries when testing. Browser checks should cover desktop and
mobile layouts, complete actions, page cleanup and driving transitions. Native checks are needed for
file locks, retention metadata, media conversion and the device consumers. The rewrite's verification
scripts are temporary and aren't installed as part of The Pond.
