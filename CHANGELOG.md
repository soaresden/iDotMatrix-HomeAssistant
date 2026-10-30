# Changelog

## [Unreleased]

### Added
- Workspace trash: 🗑 *Vider la corbeille* erases everything in it for good on every device (second tap); gallery GIFs stay.
- Pixel Studio collections (like Batocera's): custom lists of gallery GIFs picked from any folders, a GIF in as many as wanted. A 🗂 chip row in the gallery shows each one in its own order; the selection bar adds to one (a new name creates it) or removes from the one shown. An ensemble can take a collection's GIFs instead of a picked list, and follows it as it changes; deleting a collection leaves its ensembles a copy of the list.
- Hidden folders: 🙈 *Cacher* on a chosen folder takes it and its content out of sight everywhere (gallery, workspace, « Tous », collections) on every device; 👁 *Cachés* shows them again for the visit, and 👁 *Réafficher* puts one back for good.
- Pixel Studio editor: 🗑 *Clip* and 🗑 *Original* send the clip, or its original with all its clips, to the workspace trash (second tap, restorable); their GIFs stay in the gallery.
- Pixel Studio gallery and workspace: search, filters, folders and the selection bar stay in view under the status bar while scrolling.
- Pixel Studio editor: ready-made renders — ⚡ *Transfert rapide* (10 images/s, 64 colours, normal lightening), ⚖ *Équilibré* (15 images/s, 128 colours, light lightening) and 🎯 *Le plus fidèle* (every image, 256 colours, every pixel exact, so no trails) — plus two new settings, *Couleurs* and *Cadence max* (a frame-rate cap that keeps the length). 🧪 *Essais* makes the clip in every render into the gallery's « Essais » folder, with size and send time, and a ▶ to show each one on the display, to choose a compromise together. The 📜 log now describes each clip second by second: where the square sits in the source (pixels) and how much of the screen changes.
- Day schedule: a priority per time slot (haute / normale / basse) for routines that overlap. The highest priority wins, then the shortest slot, so an all-day routine is a background the others interrupt (it used to be whichever slot was listed first); the strip draws the slot that plays on top.
- Pixel Studio editor: the timeline's zoom buttons are now 🔍− then 🔍+.
- Pixel Studio 📜 *Journal* tab: everything the Pi and the browsers did, to copy (📋) or download (💾) and have it analysed. Each GIF made: the original (name, size, type, dimensions, length, working copy), the clip's settings, the frames extracted and how long the browser took, the upload to the Pi, then the encoding (frames in and out, colours, time) and how the GIF spends its bytes frame by frame (first frame, each later frame and the part of the screen it redraws). Each send to a display: waiting time, Bluetooth write mode, and per 4 KB packet the time writing and waiting for the display; each GIF shown also gets its size breakdown and gallery details. Routine changes, ⏭, screen on/off, *Optimiser* results, editor previews (summary) and the integration's warnings and errors too. The last 3000 entries survive restarts.
- Thumbnails of what a running routine shows next, on its row in the Routines tab and in the status bar. A routine driven by Home Assistant now draws its next 12 GIFs in advance (at random, 12 different ones, never the one on screen next); clicking one shows it now. A display carousel shows its 12 slots with the one it probably shows, estimated from when it started and the interval (the display never reports it).
- ⏭ *GIF suivant* on a running routine driven by Home Assistant (its row in the Routines tab and the status bar): shows the next GIF right away, or right after the one being sent, then the interval starts over. Not offered for the display's own carousel, which has no command to advance.
- Pixel Studio ⏳ tab: what the Pi is doing (sends to each display, now one after the other per display, gallery re-encodings, running routines) and what this browser is doing (clips going to the Pi, video conversions, files being read), each with a button to cancel: a waiting send is dropped, the one in progress stops before its next packet (the next send then clears the partial file first).
- Gallery ✨ *Optimiser* (selection bar, select all to do the whole gallery): re-encodes the chosen GIFs the way new ones are made — nearly identical frames merged, frames closer than ~30 ms folded together, later frames holding only what changed within the colour tolerance — without changing how long they last. A GIF is replaced only when at least 10 % lighter and at least one 4 KB Bluetooth packet shorter (otherwise nothing is left to gain without a visible loss, such as fewer colours or images or a shorter clip, and it is left alone); the old one is kept in `/media/idotmatrix/.backup`.
- Any folder can be deleted (two taps): its GIFs and originals go unfiled, nothing is erased.
- Pixel Studio ⚙ tab: this browser's name and its search folders. « Relier » (Atelier), 🔗 and ✎ (gallery) and *Relier tout* find originals there, subfolders included, by name and size or by the name a GIF's name starts with; a source already in the workspace is reused instead of being added twice.
- Every GIF sent to the gallery records who sent it (browser name and Home Assistant user), with an « envoyé depuis » filter in the gallery and the workspace.
- Always-visible checkboxes on gallery GIFs and workspace originals (no more selection mode), a 📁 button to file one item, and renaming a folder everywhere.
- Day schedule: an ON/OFF switch per routine (ON: runs by itself at its hours, all day by default; OFF: paused, hours kept); the strip is built from the routines that are ON and edits save on their own. Blocks are dragged to move them and by their edges to change their hours, and can keep to some days of the week; between blocks the screen is off by default. Switching the screen off by hand stops the running routine. The routine editor filters GIFs by folder.
- A store GIF is imported once: asking again uses the gallery's copy, and the store marks what is already in the gallery.
- **Pixel Studio** sidebar panel (admins): a browser-side workspace where any number of images, GIFs and videos (any size) are decoded, cropped with a square selector, trimmed and tuned against an instant LED preview, optionally mirrored live on the display, then pushed one by one or all at once. Only the screen-sized frames reach Home Assistant, which encodes the device GIF within the size budget into a gallery under `/media/idotmatrix` (send to display with progress, re-edit, favourites, delete). The device page links to it.
- Follow mode in Pixel Studio: the square crop can follow a moving character, from keyframes set by dragging the crop at any time or from an automatic analysis that finds what moves against the still background.
- Pixel Studio status bar, always visible: what the display shows (live preview), Bluetooth state, screen off, the running routine with a stop button, quick 🌙 screen-off / ☀️ screen-on buttons, the upload queue to Home Assistant (one clip at a time, with progress) and transfers to the display. Phone layout with a menu button, larger touch targets and a much faster LED preview.
- Several displays at once: each one gets its own Bluetooth connection (they used to share one, so with two displays everything went to the last one set up), and in Pixel Studio its own routine and day schedule. A display picker in the status bar chooses which one the Studio drives.
- Pixel Studio « Store » tab: browse the official iDotMatrix app's catalogue of ready-made animations by category, at the display's screen size, with each GIF's size, frame count, length and whether it plays as is; add one to the gallery or show it on the display. Home Assistant signs and decrypts the vendor's requests like the app (no account needed); they go to the display byte for byte like in the official app (about 15 KB, under a minute over Bluetooth); only GIFs of another size are resized and re-encoded.
- Day schedule ("table de montage") for routines: time blocks that start a routine or switch the screen off, drawn on a 24-hour strip.
- The Pixel Studio workspace is shared between browsers through Home Assistant (names, sizes and clip settings; media stay on each device). An original imported on another device shows where it came from and is relinked by adding the same file, matched by name and size. Deletions propagate.
- Nearly identical consecutive frames are merged into one (their delays add up), which keeps motion and timing while making GIFs lighter and faster to send; a Studio option turns it off.
- Gallery folders (labels kept with the gallery metadata, so files and routines are untouched), animated/still and original-format badges, search, type filter, and multi-select to file, favourite or delete many GIFs at once. Deleting asks for a second tap instead of a browser dialog, which browsers end up blocking.
- Folders in the Pixel Studio workspace too, shared with the gallery and between devices: « + Dossier » creates one (kept while empty), multi-select files originals, imports go into the selected folder and pushed clips land in their original's gallery folder.
- Pixel Studio workspace trash: deleted originals and clips (files included) wait 30 days in a « Corbeille » shared by every device, with restore; the button that cleared the whole workspace is gone.
- Pixel Studio keeps the original look by default (neutral tones, videos sampled at 25 fps); frames that start within 30 ms of the previous one are folded into it, so fast sources come down to about 30 fps with the same length. On wide screens the editor fits in the window, in three columns.
- Transfer progress names the file being sent, so a still queued behind a GIF no longer shows that GIF's progress.
- Bulk imports in Pixel Studio list every file at once (shared with other devices right away) and read them one at a time in the background, so dozens of videos no longer exhaust a phone's memory.
- Open Pixel Studio pages pick up workspace changes from other devices at once; reading imports and extracting a video show in the status bar; phones get a play button above the source.
- Store tab: whole categories load at once (no « load more »), thumbnails load as they scroll into view, favourites are kept in Home Assistant, and store GIFs loop. Store files are read to the end (they were sometimes cut short: « Incorrect padding », « not a GIF »).
- Changing a video's start or end while it is being extracted stops the previous extraction instead of competing with it.
- Video frames are cached by their place in the video: moving a clip's start or end only extracts the frames that are new (the window plus 120 frames around it are kept). New clips play as a boomerang by default, with a loop/boomerang button next to play.
- Live on the display sends the frame at once and streams stills while playing (Home Assistant keeps only the newest while one is sent); its status bar line clears when done. Phones get a pinned mini LED preview and pinch-to-zoom on the timeline with larger handles.
- Routines in Pixel Studio: rotate gallery GIFs every N seconds/minutes, random or in order, driven by Home Assistant (any number of GIFs, optional time window) or by the display's own carousel (up to 12 GIFs). Explicit carousels accept intervals beyond 255 s through the 16-bit field the Android app uses.
- `idotmatrix.convert_media` service: turns any image, GIF or video into a GIF sized and tuned for the display. Crop/fit to the screen, clip window, LED-friendly tone adjustments, and an automatic search over palette size, frame rate and clip length to stay under a byte budget. Optionally shows the result right away.
- `frames_to_gif` accepts per-frame durations, a palette size and optional dithering.
- `image.<device>_preview` entity: an animated, LED-style render of the last content sent to the display (GIFs, carousels, dashboards, designs, solid colours), shown on the device page and usable in any picture card. It is empty while the device draws content itself (native scrolling text, firmware clock faces).

### Changed
- Pixel Studio uses the whole screen width, and has fewer buttons in view: folder actions (new, rename, hide, delete, show hidden ones) and collection actions sit in a ⋯ menu at the end of their chip row, and each gallery card keeps ▶ and ★ with retouch, relink, file and delete in its own ⋯ menu.
- The card and the Pixel Studio panel are served without the month-long browser cache: an update showed only after a Home Assistant restart, even with Ctrl+F5. Browsers now check the file on each load (unchanged files answer 304).
- Routines tab: two clear modes, 📅 *Planning* (the strip decides) and ✋ *Manuel* (ensembles switched On/Off by hand), chosen at the top and shown in the status bar. An ensemble switched On by hand moves to Manuel and the planning waits until Planning is chosen again (it used to take over at its next slot, so a routine kept playing with the planning unticked). Routines are presented as ensembles of GIFs: their row only plays or stops them, and every slot of the day is listed under the strip with its own on/off.
- Sends to the display about twice as fast: the 509-byte writes of each 4 KB packet are handed to the Bluetooth stack all at once (in order) instead of one by one, which cost ~50 ms each on a Pi whatever the pause or the connection interval (both measured). A 734 KB GIF went from 107-116 s to 56 s with no packet lost.
- Editor previews (final size and exact rendering) are encoded one at a time: the editor waits for one before asking for the latest settings, and the Pi drops previews overtaken by a newer one. Each costs the Pi up to a minute, and six piling up had doubled the time of a send to the display.
- Sends to the display: a fast transfer that misses an answer is retried fast once, then falls back to acknowledged writes for that file only; the next file is fast again (acknowledged writes measured about 10 s per 4 KB packet against 0.6 s, and one miss used to slow every send until a restart). A warning written to the 📜 log no longer aborts the transfer that logged it. The send time shown before a transfer starts from 0.6 s per packet (was 11 s) and learns from real files.
- Faster uploads to the display: inside each 4 KB packet, the 509-byte writes go out every 20 ms without waiting for a Bluetooth reply, as in the Android app (the display still confirms every packet before the next). A packet the display never confirms, or a failed write, sends the file again from the start with confirmed writes, which that display keeps until Home Assistant restarts. Not yet measured on a real display.
- GIFs only send what changes: every frame after the first holds just the box that changed, unchanged pixels transparent (as in the official app's store GIFs), still one palette with black first. Pixel Studio's *Allègement* (normal by default) also keeps pixels whose colour barely moved, which makes video clips 2 to 3 times lighter and faster to send (measured on gallery GIFs: 1044 KB → 446 KB).
- Follow mode: *📍 Pointer* follows a point clicked on the subject at one or more moments (patch matching from frame to frame, both ways between clicks); resizing the square or the mouse wheel sets a zoom at that moment, gliding like the position. After a change the preview resumes at the moment being watched instead of the start.
- Videos the browser cannot read are converted much faster: when only the container is unknown (AVI, MKV, TS…) the stream is copied into an MP4 in seconds; otherwise the 360p copy skips the decoder's deblocking and keeps 30 fps. Relinking only attaches files: a video is converted when first used (or with « Convertir »), once, and the status shows its codec and size.
- Pixel Studio keeps GIFs at full quality (256 colours, every frame) since the gallery lives on Home Assistant; the size budget remains available to the `convert_media` service.
- Single GIF uploads no longer reset the panel first unless it is leaving carousel mode, so the previous content stays on screen during the transfer instead of the panel's gradient.

### Fixed
- The panel no longer shows its colour gradient for the whole first upload after every Home Assistant restart: whether a carousel runs on the display is now kept with its settings, and the reset that leaves carousel mode is only sent when one may be running.
- Pixel Studio on phones: importing many files at once no longer runs the browser out of memory (thumbnails were redrawn in parallel and every decoded original was kept), which reloaded the page back to the gallery. Decoded media is now released once drawn, and a reload reopens the same tab.
- GIF uploads larger than a couple of 4 KB packets were silently dropped by the panel (it showed its default gradient) while the upload reported success. Transfers now wait for the device after each packet, like the Android app, and report "not enough space" or invalid transfers as errors.

## [1.4.2] - 2026-10-12

### Added
- Optional custom logo filenames for the Bitcoin ticker, with default and missing-image fallbacks (#12).
- Bluetooth debug logs include dependency versions, connection routing, GATT discovery, cache recovery, write/chunk progress, and failure tracebacks. Documented how to enable and download logs for issue reports.

### Fixed
- Validate the iDotMatrix write characteristic before accepting a Bluetooth connection. Missing or unresolved GATT services now trigger one cache clear and fresh discovery; persistent failures report the discovered UUIDs instead of a `NoneType` error. Writes still avoid replaying partially completed transfers (#13).

### Upgrade notes
Update through HACS and restart Home Assistant. For connection failures, enable iDotMatrix debug logging, reproduce the problem, and download the full log as described in the README.

## [1.4.1] - 2026-10-12

### Fixed
- Fixed entity setup and Disconnect/Reconnect failing with `_schedule_refresh() missing 1 required positional argument: 'coroutine'` by keeping display task scheduling separate from Home Assistant's polling scheduler (#13).

- Removed the redundant Pillow manifest requirement to satisfy current Hassfest validation; Pillow is supplied by Home Assistant.

### Upgrade notes
Update through HACS and restart Home Assistant to load the connection fix.

## [1.4.0] - 2026-09-12

### Added
- Responsive card sections for Designer, all nine display modes, GIF carousels, and messages, including their stop actions.
- Connection controls, panel resolution selection, layer ordering, and all message styles, icons, fonts, colors, and duration options.
- Frontend regression tests and a local browser harness that uses the real Python preview renderer while simulating device writes.

### Fixed
- Prevented repeated or leaked template subscriptions, including edits, layer removal, late responses, and reconnects.
- Debounced preview rendering, rejected stale responses, and kept the last preview visible during refreshes.
- Removed the duplicate send button; actions now await completion, prevent duplicate submissions, and display errors inline.
- Made Designer preview and panel output use the same resolution. Sending a design selects Designer mode and preserves its explicit refresh trigger.
- Saved designs now retain resolution and refresh metadata, with compatibility for older saved designs.
- Corrected the card editor fields and documentation link, input labels, keyboard tabs, and mobile overflow.
- Bundled Lit locally so the card no longer requires an external CDN.
- Removed duplicate required-field keys from the CO₂ and power service descriptions.

### Upgrade notes
Update the integration, restart Home Assistant, and refresh your dashboard. The card resource version updates automatically. Existing card layers and saved designs remain supported. Dashboard modes and messages support 32×32 or 64×64; the Designer also supports 16×16.

Thank you again to **[Sean Carolan (@scarolan)](https://github.com/scarolan)** for the GIF and dashboard features this card now exposes, and to the original client contributors credited in [CONTRIBUTORS.md](CONTRIBUTORS.md).

## [1.3.0] - 2026-09-12

### Added
- Single GIF uploads and device-managed carousels of up to 12 GIFs, with controls in the Lovelace card.
- Animated weather, Bitcoin price, CO₂, household power, thermostat, sun, and moon dashboards.
- Pixel and analog clock faces, native firmware clock selection, and temporary messages that restore the previous dashboard.
- GIF optimization helper and expanded setup, automation, and Bluetooth proxy documentation.
- Automated runtime regression tests, renderer checks, and release version validation.

### Fixed
- Added explicit Disconnect/Reconnect buttons and release the Bluetooth connection when the integration is unloaded or disabled (#6).
- Added `idotmatrix.show_color` for native fullscreen color notifications (#7).
- Restored the previous multiline setting when Perfect Fit is switched off and moved multiline rendering off the event loop (#4).
- Avoid redundant image-mode commands and identical image uploads to reduce update blanking (#3).
- Normalize Bluetooth MAC addresses and reject duplicate manual/discovered entries, including older address formats; the original mass-duplication report remains unconfirmed (#5).
- Stopped dashboard refreshes can no longer queue an upload over a newly selected mode. Pending refresh tasks are owned and cancelled during unload.
- Legacy text, Designer, time-sync, and clock-date controls now serialize device writes with GIF uploads.
- GIF cancellation propagates correctly. Active shielded transfers are drained before their caller exits, and unload rejects queued transfers.
- Failed carousel setup commands abort the transfer; missing GIF paths and failed uploads report service errors.
- Non-finite sensor readings are treated as unavailable. Display services validate sizes, colors, durations, and sensor inputs.
- The carousel UI now respects the protocol's 1–255 second range.
- Lovelace resources handle the current Home Assistant data API, and the options flow no longer assigns to its read-only config-entry property (#9).
- Release version, integration manifest, and card version now consistently identify 1.3.0.

### Upgrade notes
- Update through HACS, restart Home Assistant, and refresh your dashboard browser.
- For CO₂ and power dashboards, provide your own `co2_entity` or `power_entity`. Thermostat dashboards require at least one of `heat_entity` or `cool_entity`; installation-specific defaults have been removed.
- Dashboard renderers support 32×32 and 64×64 output. Prepare uploaded GIFs at your panel's resolution; raw uploads preserve their original frames.
- Historical `v1.1`, `dev1.2`, and `dev1.3` tags retain their original contents, including the old `1.0.0` manifest. This release establishes consistent semantic versioning without rewriting published tags.
- Runtime tests use Home Assistant 2026.9.2 and simulated Bluetooth. Physical LED panels and ESPHome proxies were not exercised during this maintenance release.

### Thanks
A huge thank you to **[Sean Carolan (@scarolan)](https://github.com/scarolan)** for [PR #8](https://github.com/tukies/iDotMatrix-HomeAssistant/pull/8): GIF support, Bluetooth proxy work, the animated dashboard family, clocks, messages, and extensive documentation. This release builds on his substantial contribution, with maintainer fixes and regression coverage added during integration.

Thanks also to **[@derkalle4](https://github.com/derkalle4)** for the original Python iDotMatrix client, and **[@8none1](https://github.com/8none1)** for the reset-protocol discovery used by the client.

## [1.1] - 2026-01-19
- Added the Designer card, layered templates, saved designs, icons, and trigger-based refresh.
- Added the Text/Designer display-mode selector and development workflow improvements.

## [1.0.0] - 2025-12-31
- Initial public release of the Home Assistant integration.

[1.3.0]: https://github.com/tukies/iDotMatrix-HomeAssistant/compare/v1.1...v1.3.0
[1.1]: https://github.com/tukies/iDotMatrix-HomeAssistant/releases/tag/v1.1
[1.0.0]: https://github.com/tukies/iDotMatrix-HomeAssistant/releases/tag/v1.0.0

[1.4.0]: https://github.com/tukies/iDotMatrix-HomeAssistant/compare/v1.3.0...v1.4.0

[1.4.1]: https://github.com/tukies/iDotMatrix-HomeAssistant/compare/v1.4.0...v1.4.1

[1.4.2]: https://github.com/tukies/iDotMatrix-HomeAssistant/compare/v1.4.1...v1.4.2
