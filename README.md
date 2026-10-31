# iDotMatrix Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/tukies/iDotMatrix-HomeAssistant)](https://github.com/tukies/iDotMatrix-HomeAssistant/releases)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-yellow.svg)](https://buymeacoffee.com/tukie)

[Changelog](CHANGELOG.md) · [Contributors](CONTRIBUTORS.md)

A fully featured, modern Home Assistant integration for **iDotMatrix** pixel art displays. 

Connects directly to your device via Bluetooth (native or proxy) without any cloud dependencies. Unlock the full potential of your display with advanced animations, typography controls, and "Party Mode" features.

---

## Features

- **Instant Bluetooth Connectivity**: Supports native adapters and ESPHome Bluetooth Proxies for rock-solid connections.
- **Advanced Text Engine**: 
    - Full control over Font, Color, Speed, and Animation Mode.
    - **Pixel Fonts**: Bundled fonts include VT323, Press Start 2P, Rain DRM3, and classic BDF bitmap sets.
    - **Typography Controls**: Adjust letter spacing (horizontal/vertical), blur/sharpness, and font size.
- **Fun Text (Party Mode)**: 
    - Animates messages word-by-word with random bright colors.
    - Adjustable delay for perfect timing.
- **Autosize Perfect Fit**: 
    - Automatically scales text to fit the screen bounds, centering it for a clean look.
- **Clock Control**: 
    - Syncs time automatically.
    - Customizable 12h/24h formats, date display, and colors.
- **Designer Card (Layered Templates)**:
    - Build multi-layer faces using text + icon templates.
    - Save/load designs and auto-refresh with a trigger entity (e.g., `sensor.time`).
- **Icons**:
    - Render `mdi:` icons directly.
    - Use `/local/...png` or URL icons for custom sets. SVG requires Cairo (optional).
- **Weather Dashboard**:
    - Animated pixel-art weather display: condition icon, temperature, high/low, humidity and wind.
    - Sources data from any `weather.*` entity, individual sensors (local weather stations!), or a mix.
    - Auto-updates when conditions change.
- **Bitcoin Ticker**:
    - The classic Bitcoin logo with the live USD price below it.
    - Price colored by direction of the last move; optional 24h change row.
    - Auto-updates when the price sensor changes.
- **CO2 Gauge**:
    - Big ppm reading with a color-coded bar gauge and air-quality label (Good → Crit).
    - CO2 molecule icon changes color with severity; haze particles drift by when levels are high.
    - Auto-updates when the CO2 sensor changes.
- **Power Gauge**:
    - Whole-house power draw in watts with a color-coded bar gauge (0-5 kW).
    - Status label and lightning bolt shift green → yellow → orange → red with load.
    - Auto-updates (throttled to every 15s) as the power sensor changes.
    - Optional thermostat entities flag when the furnace or AC is behind a spike ("HEAT ON" / "AC ON").
- **Thermostat Status**:
    - Heating and cooling zones as two stacked panels: flame / snowflake icon, ON/IDLE/OFF, room temperature and setpoint.
    - Icons animate (flame flickers, snowflake pulses) while a zone is actively running.
    - Auto-updates when the climate entities change.
- **Sunrise / Sunset Arc**:
    - Horizon with the sun travelling an arc from sunrise to sunset; the moon takes the arc at night.
    - Sunrise and sunset times, daylight length, and a countdown to the next event.
    - Uses the home location from Home Assistant; refreshes every minute.
- **Moon Phase**:
    - Large moon disc with the real terminator curve, maria texture, and twinkling stars.
    - Phase name, illuminated percentage, and days until the next full or new moon.
    - Computed from the date, no entity needed; refreshes hourly.
- **Messages**:
    - One-shot notifications from any automation in five styles: card, alert, marquee, party, typewriter.
    - 24 built-in icons, solid or rainbow text, three fonts: house 5x7 pixel, Press Start 2P arcade, minimalist 3x5 tiny.
    - Restores whatever was showing before when the message expires; wakes a darkened panel.
- **Clock**:
    - Custom "pixel" face in the house style: big HH:MM with blinking colon, weekday, date, accent rule.
    - Custom "analog" face: minimal dial with accent ticks, smooth anti-aliased hands, pulsing center dot.
    - Or any of the device's 8 native firmware clock styles (zero BLE traffic once set).
- **Device Control**:
    - Turn On/Off, set Brightness, color, and screen size (16x16 / 32x32 / 64x64).

---

## Installation

### Option 1: HACS (Recommended)
1. Open HACS in Home Assistant.
2. Go to **Integrations** > **Triple Dots** > **Custom Repositories**.
3. Add `https://github.com/tukies/iDotMatrix-HomeAssistant` as an **Integration**.
4. Click **Download**.
5. Restart Home Assistant.

### Option 2: Manual
1. Download the `custom_components/idotmatrix` folder from this repository.
2. Copy it to your Home Assistant `config/custom_components/` directory.
3. Restart Home Assistant.

---

## Configuration

1. Go to **Settings** > **Devices & Services**.
2. Click **Add Integration** and search for **iDotMatrix**.
3. The integration will automatically discover nearby devices. Select your device.
    - *Note: Ensure your device is powered on and not connected to the phone app.*

---

## Lovelace Card (Designer)

The integration auto-registers the card in Lovelace storage mode. If you use YAML mode or prefer manual setup:
- URL: `/idotmatrix/idotmatrix-card.js`
- Type: `JavaScript Module`

Add a card to your dashboard:
   ```yaml
   type: custom:idotmatrix-card
   title: iDotMatrix Designer
   ```
Set `Display Mode` on the device page to **Display design from the Card**.

---

## Usage Guide

### Display Mode
Pick what the device shows from the device page:
- **Entity**: `select.<device>_display_mode`
- **Options**: Display Text Field / Display design from the Card
- **Tip**: Entity IDs are per-device, e.g., `text.idm_3fb639_display_text`.

### Text Control
Control the scrolling text on your device using the `Display Text` entity.
- **Entity**: `text.<device>_display_text`
- **Actions**: Type any text to update the display immediately.
- **Settings**: Use the configuration entities (sliders/selects) to adjust:
    - **Font**: Choose from installed pixel-perfect fonts.
    - **Speed**: Scroll speed (1-100).
    - **Color**: Full RGB control via `light.<device>_panel_colour`.
    - **Spacing**: Tweak kerning with "Text Spacing".

### Fun Text (Party Mode)
Want to spice things up? Use the Fun Text entity!
- **Entity**: `text.<device>_fun_text`
- **How it works**:
    1. Enter a phrase like "HAPPY NEW YEAR".
    2. The display shows one word at a time (split on spaces).
    3. Each word gets a **random bright color** from a fixed palette.
    4. The last word remains on screen (no final full‑sentence render).
- **Control**: Adjust the delay between words with the **Fun Text Delay** slider (`number.<device>_fun_text_delay`).

### Autosize (Perfect Fit)
Stop guessing font sizes. Let the integration do the math.
- **Entity**: `switch.<device>_text_perfect_fit_autosize`
- **How it works**:
    - **ON**: The integration iteratively resizes your text (shrinking from max size) until it fits perfectly within the screen capabilities 
    - **OFF**: Standard scrolling or manual font size.

### Designer Card (Layers + Icons)
- Use the Designer card to build a layered face.
- Each layer supports:
  - **Template**: Jinja template for text
  - **Icon Template**: Jinja template that returns an icon string (e.g., `mdi:floor-lamp`)
  - **Icon Size**: Pixel size for the icon
  - **X/Y, font, spacing, blur, color**
- To combine icons and text, use separate layers and offset X/Y.

Examples:
- Icon based on entity state:
  ```
  {{ 'mdi:floor-lamp' if is_state('light.lamp', 'on') else 'mdi:floor-lamp-outline' }}
  ```
- Use an entity icon directly:
  ```
  {{ state_attr('light.lamp', 'icon') }}
  ```
- Custom PNG icon:
  ```
  /local/icons/alert.png
  ```

### Clock & Time
- **Sync Time**: Press `button.<device>_sync_time` to sync the device clock to Home Assistant's time.
- **Formats**: Toggle `select.<device>_clock_format` (12h/24h) and `switch.<device>_clock_show_date`.

### GIF Animations

Display animated GIFs on your device — single files or rotating carousels.

**Single GIF:**
```yaml
action: idotmatrix.display_gif
data:
  path: /config/www/idotmatrix/gifs/Pac-man.gif
```

**Carousel (folder of GIFs):**
```yaml
action: idotmatrix.display_gif
data:
  path: /config/www/idotmatrix/gifs
  rotation_interval: 10
```

- `path`: A single `.gif` file or a folder containing GIF files.
- `rotation_interval`: How many seconds each GIF displays before advancing (1-255, default 5). The device handles rotation natively in hardware.
- When given a folder, up to 12 random GIFs are uploaded as a batch and the device loops through them automatically.
- To stop a running carousel: call `idotmatrix.stop_gif_rotation`.

**Pixel Studio (sidebar panel):**

Admins get a **Pixel Studio** entry in the sidebar (also in the companion app, and behind the *Visit* button of the device page):

- **Workspace**: browse or drop any number of images, GIFs and videos. They stay **in the browser** as *originals* (videos the browser cannot decode — AVI, WMV, old codecs... — become a light 360p working copy with ffmpeg.wasm, downloaded once from jsdelivr). Each original holds one or more *clips* — a time window, crop, speed and tones — listed beneath it, and each clip shows the GIF it produced on the Pi. Clips always render from their original, so re-editing never compounds quality loss; speed can be changed right from the list, and a changed clip is flagged until it is pushed again. Originals and clips are kept in the browser between visits, and their description (names, sizes, clip settings — not the media) is shared through Home Assistant: a video imported on the phone shows on the PC as *imported on téléphone*, and adding the same file there (matched by name and size) or *Relier* links it.
- **Editor**: drag the square to choose what to keep (resize it with the round handle), or pick *whole image* / *stretch*; for videos and animations drag the start and end handles of the timeline (the *here* buttons use the player position), set the sampled frame rate and the playback speed (the source plays at that speed too), choose loop or boomerang playback, and optionally let the crop follow a moving character (drag the square at a few moments to set keyframes, or let *Suivi auto* find what moves against the still background, or *📍 Pointer* then click the subject at one or more moments: it is followed from frame to frame); while following, the round handle or the mouse wheel on the square zooms at that moment and the zoom glides between moments. *Default settings* resets tones, speed and size without touching the crop or the clip window. Large sources are reduced by halves (each step averages every pixel, which keeps 4K sources clean) and a light sharpening restores edges once shrunk to a few LEDs. Brightness, contrast, saturation, gamma, sharpness and black level update the animated LED preview instantly; the final GIF (full quality: 256 colours, every frame, nearly identical frames merged unless turned off) and its sending time are computed by Home Assistant after a short pause. *Live on the display* mirrors the frame being edited on the panel once you stop changing things (a few seconds of Bluetooth delay).
- **Push to the Pi**: one item or the whole workspace. Clips queue up and are sent one at a time; only the screen-sized frames travel, and Home Assistant encodes the device GIF and stores it in `/media/idotmatrix`.
- **Gallery**: every GIF in `/media/idotmatrix`, newest first. ▶ sends it to the display (with progress), ✎ reopens its clip on the original (looked up in the search folders when this browser does not have it, else the GIF itself), 🔗 finds its original in the search folders and links it, 📁 files it, ★ marks favourites, 🗑 deletes it (tap twice). Each GIF shows who sent it (the browser's name and the Home Assistant user); folders, a search box, an animated/still filter, an « envoyé depuis » filter and badges with the original's format keep it tidy. Every GIF and original has a checkbox: ticking some opens a bar that files, favourites or deletes them at once. Folders are shared with the workspace: « + Dossier » creates one (even empty), ✎ Renommer renames the selected one everywhere; a clip pushed to the Pi lands in its original's folder, and files added while a folder is selected go into it.
- **⏳ (queue)**: what the Pi does (sends to the displays, one after the other per display; re-encodings; running routines) and what this browser does (clips going to the Pi, video conversions, files being read), each cancellable; a send in progress stops before its next packet.
- **⚙ (this browser)**: its name, kept with every original it imports and every GIF it sends, and its *search folders* (kept by Chrome or Edge on a computer, and by Brave once `brave://flags/#file-system-access-api` is enabled; other browsers choose a folder for the visit): « Relier », 🔗 and *Relier tout* look there, subfolders included, for originals — same name and size first, else the name a GIF's name starts with (`2025-05-01-190800_original_boomerang.gif` comes from `2025-05-01-190800.mp4`). A source already in the workspace is reused, never added twice.

- **Store**: the ready-made animations of the official iDotMatrix app, by its five categories (Quotidien, Émotions, Fêtes, Créatif, Pro), for the display's screen size. Each GIF shows its file size, frame count and length, and whether it goes to the panel as is (*✓ tel quel*, like the official app sends it) or must be resized and re-encoded (*↻ redimensionné*, only when it is not the screen's size: re-encoding full frames makes these GIFs 20 to 30 times heavier). *+ Galerie* copies it into the gallery, ▶ copies it and shows it on the display. Store items have no title, only a number (`store_23987`), a publication date and sometimes search tags; the filter searches those in the pages already loaded. Home Assistant talks to the vendor's server the way the app does (signed, AES-encrypted requests, presenting itself as the app's HTTP client) with no account; the vendor can change or close that at any time, and the tab then just shows the error.
- **Workspace list**: newest first, one compact line per original and per clip, with a search box and filters (clips to send, changed, already on the Pi; videos, GIFs, images) and foldable originals. ⬆ sends a clip to the gallery, ▶ shows it on the display (sending it first if needed).
- **Météo**: the time with the seconds ticking, the place's name, today's weather (icon, temperature, high and low, chance of rain) and 4 hours of your choice (every N hours or fixed hours), the next days, or sunrise and sunset, with a live LED preview. Up to 4 places take turns every 10 to 60 seconds; the clock's colour can be chosen and the brightness can follow the sun (day and night levels). By default Home Assistant's own weather entity (met.no's forecast); each place can be another weather entity, a zone, or a place typed in and geocoded with [Open-Meteo](https://open-meteo.com) (free, no key). Each minute one GIF holding the whole minute is sent (about 4.7 KB, two Bluetooth packets, ~1.2 s), never in the middle of another send: the display ticks the seconds and turns the places by itself. The forecast is fetched every 15 to 60 minutes. A weather view is a routine, so it can be switched on by hand or placed in the 📅 Planning for part of the day. Today's icon moves (rain falling, the sun's rays turning), and emoji typed in a place's name or in a message are drawn as small pixel pictures. The screens that take turns are filled by hand: « + » above the preview adds one, empty or from a preset (weather, saint of the day, special days, birthdays, a countdown to a date or the weekend, « N'oubliez pas » reminders with the agenda, notes, the word of the day, quotes, proverbs, useless facts, jokes…), and each part is placed, sized and outlined on its screen; each screen stays its own time and can keep to some hours. The built-in texts are in `custom_components/idotmatrix/texts_fr.json`, each with its source. While the view is on the display, every change goes there live. The same weather view exists as an Android app, **Pixel Météo** (see [`android/README.md`](android/README.md)), for a phone driving a display without Home Assistant.
- **Routines**: change what the display shows every N seconds or minutes, at random (never twice in a row) or in order, from a selection of gallery GIFs. *Driven by Home Assistant* allows any number of GIFs and an optional daily time window (each change is one Bluetooth upload); *display carousel* uploads up to 12 GIFs once and lets the display rotate them by itself, with intervals up to 18 hours like the Android app. The active routine resumes after a Home Assistant restart. Routines are *ensembles*: sets of GIFs with their order and interval, picked one by one or taken from a gallery *collection* (a custom list picked from any folders, kept in step). Two modes, chosen at the top of the tab and shown in the status bar: **📅 Planning**, where the 24-hour strip decides which ensemble plays and when (each slot starts an ensemble or switches the screen off, and the screen comes back on when an off slot ends), and **✋ Manuel**, where each ensemble's On/Off switch plays or stops it by hand. Switching an ensemble On by hand moves to Manuel: the planning keeps its slots but waits until Planning is chosen again. All slots are listed under the strip (+ *Plage d'ensemble*, + *Écran éteint*), each with its hours, days, priority and its own on/off; the day chips above the strip only show one day, and changes save on their own. Blocks are dragged to move them and by their edges to change their hours (15-minute steps). Between blocks the screen is off by default (*Hors plages : rien ne change* keeps what runs instead). When slots overlap, each one's priority (haute / normale / basse) decides, then the shortest wins, so an all-day routine is a background the others interrupt; the strip shows the slot that plays. A block can keep to some days of the week (a block crossing midnight belongs to the day it starts); the strip shows every day or one. Switching the screen off by hand stops the running routine. The routine editor filters the gallery by folder. A running routine shows its next GIFs as thumbnails (on its row and in the status bar). Driven by Home Assistant, the next 12 are drawn in advance: ⏭ shows the next one right away and clicking a thumbnail shows that one. For a display carousel the thumbnails are its 12 slots, with the one it probably shows estimated from the time (the display never reports it, and it can't be advanced from outside).
- **Collections and hidden folders**: in the gallery, 🗂 collections are custom lists of GIFs picked from any folders (a GIF can be in several), made and filled from the selection bar; 🙈 hides a folder and its content everywhere until 👁 shows it again.
- **📜 Journal**: everything the Pi and the browsers did, with timings, to copy or download and have it analysed: each GIF made (original file, clip settings, frames, encoding, bytes frame by frame), each send to a display (time per Bluetooth packet, write mode), routine changes and warnings. The last 3000 entries are kept across restarts.
- **Status bar**: always visible at the top — what the display shows, Bluetooth state, screen off, the running routine (with ⏭ next-GIF and stop buttons), quick 🌙 screen-off and ☀️ screen-on buttons, the upload queue to Home Assistant and transfers to the display.
- **Several displays**: each one keeps its own Bluetooth connection, routine and day schedule, so they run side by side. With more than one, the status bar's display picker chooses which one the Studio drives (sending, live preview, routines, schedule, screen buttons); the list also shows what each one runs. The gallery and the routine library are shared.

The editor offers ready-made renders (⚡ quick to send, ⚖ balanced, 🎯 most faithful, with no trails) and 🧪 *Essais*, which makes the clip in each of them into the gallery's « Essais » folder to compare on the display. GIFs only send what changes from one frame to the next (like the official app's store GIFs); older gallery GIFs get the same treatment with ✨ *Optimiser* in the gallery's selection bar (already optimal ones are left alone, replaced ones kept in `.backup`); the editor's *Allègement* also leaves pixels whose colour barely moved, which makes video clips 2 to 3 times lighter. The device can't report what it stores, so the gallery lives in Home Assistant. Sending is limited by Bluetooth speed: each 4 KB packet is confirmed by the display before the next one goes out. Inside a packet, the 509-byte writes are handed to the Bluetooth stack all at once without waiting for a reply (about 0.3 s per 4 KB packet on a Pi, roughly 13 KB/s); if the link loses some of them (seen through ESPHome proxies under load), the file is sent again from the start, fast once more, then with confirmed writes for that file only. Single uploads do not reset the panel first (only when leaving carousel mode), so the previous content stays on screen while the next one loads, as in the Android app. Each display has its own Bluetooth connection; an ESPHome Bluetooth proxy holds about three active connections by default.

**Converting images, GIFs and videos:**

`display_gif` sends files as-is, so they should already match the screen. `idotmatrix.convert_media` prepares any image, GIF or video (anything ffmpeg can decode — ffmpeg ships with Home Assistant OS) for the display:

```yaml
action: idotmatrix.convert_media
data:
  source: /media/uploads/cat.mp4
  start: 3.5
  end: 9
  display: true
```

- Crops (or `fit`s with black bars) to the configured screen size; `crop: [x, y, width, height]` keeps a region of the source, in fractions (`[0.25, 0, 0.5, 1]` is the middle half).
- Tunes colours for LEDs: a little extra contrast and saturation, and pixels darker than `black_level` are switched off instead of glowing faintly.
- Keeps the GIF under `max_kb` (default 96): palette size, then frame rate, then clip length are reduced until it fits. Identical consecutive frames are merged. `boomerang: true` plays the clip back and forth for a seamless loop.
- Dithering is off by default: on a 64x64 panel it shimmers and roughly halves the colours that fit in the same budget.
- Writes to `/media/idotmatrix/<name>_<size>.gif` unless `output` is set, and returns the path, size, frame count and the settings it settled on.

**Preview:**

The device can't be read back, so `image.<device>_preview` shows an LED-style render of the last content the integration sent: GIFs (the first one of a carousel), dashboards, messages, designs and solid colours, animated like on the panel. It appears on the device page and works in picture cards. It stays empty for content the device draws itself (native scrolling text and firmware clock faces) and after a restart until something new is sent.

**Preparing GIFs by hand:**

The display is 64x64 pixels. Any standard GIF works — the device handles GIF89a, animated GIFs, transparency, and all standard features. For best results, resize your source GIFs to 64x64 before uploading to save transfer time:

```bash
# Requires: gifsicle (apt install gifsicle / brew install gifsicle)
# Resize all GIFs in a folder to 64x64
for gif in *.gif; do
  gifsicle --resize 64x64 -O3 "$gif" -o "optimized/$gif"
done
```

Larger files work fine — they just take longer to transfer over Bluetooth. A 60KB GIF takes roughly 10-15 seconds through a proxy.

**Automation examples:**

Start the GIF carousel on HA boot (with a 1-minute delay for Bluetooth to initialize):
```yaml
automation:
  - alias: "Start GIF Rotation on Boot"
    triggers:
      - trigger: homeassistant
        event: start
    actions:
      - delay: "00:01:00"
      - action: idotmatrix.display_gif
        data:
          path: /config/www/idotmatrix/gifs
          rotation_interval: 60
```

Restart the carousel every morning (in case it stopped overnight):
```yaml
  - alias: "Start GIF Rotation in Morning"
    triggers:
      - trigger: time
        at: "06:05:00"
    actions:
      - action: idotmatrix.display_gif
        data:
          path: /config/www/idotmatrix/gifs
          rotation_interval: 60
```

Watchdog — re-upload a fresh batch every hour to keep things interesting:
```yaml
  - alias: "GIF Rotation Watchdog"
    triggers:
      - trigger: time_pattern
        hours: "/1"
    actions:
      - action: idotmatrix.display_gif
        data:
          path: /config/www/idotmatrix/gifs
          rotation_interval: 60
```

### Weather Dashboard

`idotmatrix.show_weather` renders an animated weather dashboard entirely on the
fly — pixel-art condition icons (rotating sun rays, falling rain, lightning
flashes, twinkling stars), a big color-coded temperature, today's high/low,
humidity and wind — and uploads it as a looping GIF using the reliable
single-upload protocol.

Simplest form — everything from one weather entity (condition, temperature,
humidity, wind, and forecast high/low):

```yaml
action: idotmatrix.show_weather
data:
  weather_entity: weather.openweathermap
```

Mix and match sources. Sensor overrides win over the weather entity, so you can
take the condition/forecast from OpenWeatherMap but show the *actual*
temperature and humidity from a backyard weather station:

```yaml
action: idotmatrix.show_weather
data:
  weather_entity: weather.openweathermap
  temperature_entity: sensor.gw2000b_outdoor_temperature
  humidity_entity: sensor.gw2000b_humidity
```

The condition can also come from a text sensor. OpenWeatherMap description
strings like `broken clouds` or `light rain` are mapped to the right icon
automatically, and clear skies switch to a moon-and-stars icon after sunset:

```yaml
action: idotmatrix.show_weather
data:
  condition_entity: sensor.openweathermap_weather
  temperature_entity: sensor.gw2000b_outdoor_temperature
  humidity_entity: sensor.gw2000b_humidity
```

By default the dashboard **follows the weather**: it re-renders and re-uploads
whenever a source entity changes (debounced, and only when a displayed value
actually changes — a 0.1° wiggle won't touch the device). Forecast high/low is
refreshed every 15 minutes. Stop it with:

```yaml
action: idotmatrix.stop_weather
```

Options:

| Field | Description |
| --- | --- |
| `weather_entity` | Base `weather.*` entity (condition, temp, humidity, wind, forecast high/low). |
| `condition_entity` | Override the condition from a sensor (HA conditions or free text like "light rain"). |
| `temperature_entity` / `humidity_entity` / `wind_entity` | Override individual values, e.g. from a local station. |
| `high_entity` / `low_entity` | Override today's forecast high/low. |
| `pixel_size` | `64` (default, full dashboard) or `32` (compact layout). |
| `follow` | `true` (default) keeps it updated; `false` renders once. |

Starting weather mode stops any running GIF rotation, and calling
`idotmatrix.display_gif` stops weather mode — the two won't fight over the
display.

### Bitcoin Ticker

`idotmatrix.show_bitcoin` renders the classic Bitcoin logo with the
current USD price below it, kept alive by subtle animation: occasional
sparkle glints on the coin and dim ember particles drifting up behind it. The price is colored green or red by the direction
of its last move, and an optional second row shows the 24h change percentage.

```yaml
action: idotmatrix.show_bitcoin
data:
  price_entity: sensor.bitcoin_price
```

With a 24h change sensor:

```yaml
action: idotmatrix.show_bitcoin
data:
  price_entity: sensor.bitcoin_price
  change_entity: sensor.bitcoin_24h_change
```

Like weather mode it **follows the price** by default: updates are debounced
and only re-uploaded when the rounded dollar price actually changes. Stop with
`idotmatrix.stop_bitcoin`. The three display modes (GIF rotation, weather,
Bitcoin) are mutually exclusive — starting one stops the others.

| Field | Description |
| --- | --- |
| `price_entity` | Price sensor (default `sensor.bitcoin_price`). |
| `change_entity` | Optional 24h change % sensor. |
| `pixel_size` | `64` (default) or `32` (compact layout). |
| `follow` | `true` (default) keeps it updated; `false` renders once. |

### CO2 Gauge

`idotmatrix.show_co2` renders indoor air quality: a big ppm reading, a
status label (Good/OK/Fair/Poor/Bad/Crit) and a horizontal bar gauge scaled
0-2000 ppm that shifts green → yellow → orange → red as concentration rises.
The CO2 molecule icon (borrowed from the LaMetric icon set) changes color
with severity, and dim haze particles drift across when levels top 1000 ppm.

```yaml
action: idotmatrix.show_co2
data:
  co2_entity: sensor.living_room_co2
```

Updates are debounced by 30 seconds and skipped when the rounded ppm value
hasn't changed. Stop with `idotmatrix.stop_co2`.

| Field | Description |
| --- | --- |
| `co2_entity` | CO2 concentration sensor in ppm. |
| `pixel_size` | `64` (default) or `32` (compact layout). |
| `follow` | `true` (default) keeps it updated; `false` renders once. |

### Power Gauge

`idotmatrix.show_power` renders whole-house power usage: a big watts
reading, a status label (Low/Norm/Med/High/Peak/Max) and a horizontal bar
gauge scaled 0-5000 W that shifts green → yellow → orange → red as load
climbs. A white spark travels along the filled bar to suggest current flow.

```yaml
action: idotmatrix.show_power
data:
  power_entity: sensor.home_power
```

Because power sensors update near-continuously, updates are throttled to at
most one upload every 15 seconds, and tiny fluctuations (< 25 W) are ignored.
Stop with `idotmatrix.stop_power`. All display modes (GIF rotation, weather,
Bitcoin, CO2, power, thermostat, clock) are mutually exclusive — starting one
stops the others.

If `heat_entity` / `cool_entity` point at climate entities, the "WATTS"
caption is replaced by a flame and "HEAT ON", a snowflake and "AC ON", or
"HEAT+AC" whenever a thermostat reports that it is actively running, so a
load spike explains itself at a glance.

| Field | Description |
| --- | --- |
| `power_entity` | Total active power sensor in watts. |
| `heat_entity` | Optional heating climate entity used for the caption. |
| `cool_entity` | Optional cooling climate entity used for the caption. |
| `pixel_size` | `64` (default) or `32` (compact layout). |
| `follow` | `true` (default) keeps it updated; `false` renders once. |

### Thermostat Status

`idotmatrix.show_thermostat` renders a heating thermostat and a cooling
thermostat as two stacked panels. Each shows its icon (flame or snowflake),
a `HEAT` / `COOL` label, a status word (`ON`, `IDLE`, `OFF`, `FAN`), the
room temperature at double size and the setpoint beside it. While a zone is
actively heating or cooling its icon animates; idle zones dim to a muted
version of their color and switched-off zones go gray. Either entity may be
omitted to show a single centered panel.

```yaml
action: idotmatrix.show_thermostat
data:
  heat_entity: climate.heating
  cool_entity: climate.cooling
```

Reads the standard climate attributes (`hvac_action`, `current_temperature`,
`temperature`, falling back to `target_temp_low` / `target_temp_high` in
heat-cool mode). Updates are debounced by 5 seconds and skipped when nothing
visible changed. Stop with `idotmatrix.stop_thermostat`.

| Field | Description |
| --- | --- |
| `heat_entity` | Climate entity for the heating zone (top panel). |
| `cool_entity` | Climate entity for the cooling zone (bottom panel). |
| `pixel_size` | `64` (default) or `32` (compact icon + temperature list). |
| `follow` | `true` (default) keeps it updated; `false` renders once. |

### Sunrise / Sunset Arc

`idotmatrix.show_sun` draws a horizon line with an arc across the sky.
During the day the sun travels the arc from sunrise (left) to sunset
(right): the path already travelled glows warm, the rest is a dim dotted
trail, and the sun's color warms toward orange as it nears the horizon.
At night the moon takes the same arc from sunset to the next sunrise on a
blue trail with a few twinkling stars. Sunrise and sunset times sit under
the ends of the horizon, the daylight length runs along the top, and a
countdown to the next event ("SET 4H12M" / "RISE 9H05M") along the bottom.

```yaml
action: idotmatrix.show_sun
data:
  hour24: false
```

Times come from the home location configured in Home Assistant, so no
entity is needed. The display refreshes each minute and skips the upload
when nothing visible changed. Stop with `idotmatrix.stop_sun`.

| Field | Description |
| --- | --- |
| `hour24` | `true` (default) for 24-hour times, `false` for 12-hour. |
| `pixel_size` | `64` (default) or `32` (compact arc with the next event time). |
| `follow` | `true` (default) keeps it updated; `false` renders once. |

### Moon Phase

`idotmatrix.show_moon` renders the moon as a large disc whose lit portion
follows the real terminator curve for the current lunar age, drawn
supersampled for a smooth edge with a few darker maria for texture. The
phase name is stacked at the top (for example "WAXING" / "GIBBOUS"), and the
illuminated percentage and days until the next full or new moon run along
the bottom. Stars twinkle around the disc. In the southern hemisphere the
lit side is mirrored automatically.

```yaml
action: idotmatrix.show_moon
```

The phase is computed from the date using the mean synodic month, accurate
to within roughly half a day, so no entity is needed. It refreshes hourly
and uploads only when a visible value changes. Stop with
`idotmatrix.stop_moon`.

| Field | Description |
| --- | --- |
| `pixel_size` | `64` (default) or `32` (compact disc with the illumination). |
| `follow` | `true` (default) keeps it updated; `false` renders once. |

### Messages

`idotmatrix.show_message` pushes a one-shot message to the panel from any
automation. When the duration elapses, whatever was showing before comes
back on its own (a Photos carousel is re-uploaded, so expect a delay there).
If the panel was darkened, it is woken for the message and darkened again
afterwards. Calling it again while a message is showing replaces the message
but still restores the original display at the end.

```yaml
action: idotmatrix.show_message
data:
  message: Front door open
  icon: door
  style: card
  duration: 15
```

Styles:

| Style | Look |
| --- | --- |
| `card` | Icon on top, word-wrapped centered text below. Long text pages every 3 seconds with page dots. |
| `alert` | The card with a pulsing border in the icon's color and a blinking icon. |
| `marquee` | Ticker: the icon is pinned on the left and the text scrolls past it. |
| `party` | Homage to the original Fun Text: one word at a time, each in a random color, confetti everywhere. |
| `typewriter` | Characters appear one by one behind a blinking block cursor, phosphor green by default. Long text types out page by page. |

| Field | Description |
| --- | --- |
| `message` | Text to show. Newlines force line breaks. |
| `style` | One of the styles above (default `card`). |
| `icon` | Optional icon: `info`, `alert`, `check`, `cross`, `bell`, `heart`, `star`, `mail`, `door`, `package`, `drop`, `flame`, `snowflake`, `sun`, `moon`, `bolt`, `dog`, `car`, `timer`, `phone`, `home`, `gift`, `coffee`, `music`. |
| `color` | RGB text color. Defaults to white, or phosphor green for `typewriter`. |
| `rainbow` | Animated rainbow text. |
| `font` | `pixel` (5x7 house font), `arcade` (Press Start 2P, 8x8, with lowercase) or `tiny` (3x5 minimalist, 15 characters per line for dense messages). |
| `duration` | Seconds before the previous display is restored (default 15; `0` holds until `stop_message`). |
| `pixel_size` | `64` (default) or `32` (compact card; marquee still scrolls). |

`idotmatrix.stop_message` ends a message early and restores the previous
display.

### Clock

`idotmatrix.show_clock` displays a clock. The default `pixel` face is a
custom design rendered by the integration — big HH:MM in the pixel font
with a colon that blinks once a second (animated on the device via a tiny
2-frame GIF), the weekday up top in an accent color, and the date below.
Home Assistant re-uploads it once a minute (~1.5 KB, sub-second over BLE).

```yaml
action: idotmatrix.show_clock
```

Faces `0`-`7` switch to the device's built-in firmware clock styles
instead — the panel keeps time entirely on its own after a single command
(the integration syncs the device clock first):

```yaml
action: idotmatrix.show_clock
data:
  face: "3"
  color: [255, 180, 0]
```

Stop with `idotmatrix.stop_clock`. Clock mode is mutually exclusive with
the other display modes, same as the rest.

| Field | Description |
| --- | --- |
| `face` | `pixel` (default) or `analog` (custom rendered), or native style `0`-`7`. |
| `color` | Accent color (pixel/analog faces) / text color (native). |
| `hour24` | `true` (default) or `false` for 12h + AM/PM. |
| `show_date` | Show the date row (default `true`). |
| `pixel_size` | `64` (default) or `32` (compact pixel face). |
| `follow` | `true` (default) keeps the pixel face ticking; `false` renders once. |

### Bluetooth Proxy

This integration fully supports **ESPHome Bluetooth Proxies** and is the recommended setup for most users.

- If your Home Assistant server is far from the device, use a cheap ESP32 with ESPHome to extend range.
- The integration will automatically find and use the proxy with the best signal.
- **Recommended hardware**: Any ESP32 board running ESPHome with `bluetooth_proxy` enabled. The [M5Stack Atom Lite](https://esphome.github.io/bluetooth-proxies/) is a great compact option.
- File uploads first try unacknowledged writes, like the Android app (much faster). If the proxy drops some of them, the display never confirms that packet; the file is then resent with BLE Write Requests (with acknowledgment), slower but rock-solid, for that file only (the next file starts fast again). Commands always use acknowledged writes.

**Direct Bluetooth** is also supported. If your HA server has a Bluetooth adapter and is within range (~10m), the device will connect directly with faster transfer speeds.

---

## Troubleshooting

### Collecting Bluetooth debug logs

In **Settings → Devices & services → iDotMatrix**, open the three-dot menu and select **Enable debug logging**. Reproduce the problem by pressing **Reconnect** and repeating the failing action, then select **Disable debug logging** to download the log. See Home Assistant's [debug logging instructions](https://www.home-assistant.io/docs/configuration/troubleshooting/#debug-logs-and-diagnostics).

The integration's debug logs include dependency versions, connection attempts and cache settings, selected-device and last-advertisement sources, signal strength when available, the connected backend, discovered services and characteristic properties, write sizes and failed-chunk offsets, retry decisions, and exception tracebacks. These logs record transfer metadata rather than display payloads or raw advertisement data. The last advertisement source may differ from the adapter/proxy ultimately chosen by Home Assistant; the connected backend is logged separately.

For failures during Home Assistant startup, add this to the existing `logger` configuration in `configuration.yaml` and restart:

```yaml
logger:
  logs:
    custom_components.idotmatrix: debug
```

Include the downloaded log, integration version, panel model, and whether you use a local adapter or ESPHome proxy in the issue report. Capture the entire attempt through the final success or error, including any automatic retry. Before posting logs publicly, review them and redact device addresses, BlueZ paths, and adapter/proxy identifiers, using consistent replacements so attempts can still be correlated. Remove the YAML debug setting when finished.

**"Device unavailable" / "No backend found"**
- Ensure the device is **disconnected** from the mobile app. It can only talk to one controller at a time.
- If using a local adapter on macOS/Linux, ensure BlueZ is up to date.
- Restart the iDotMatrix device (unplug/replug).
- If using an ESPHome proxy, check that the proxy is online and within range of the display.

**GIF not displaying / screen goes blank**
- Power cycle the iDotMatrix device. A failed upload can leave it in a bad state.
- Ensure the GIF file exists at the path specified (paths are relative to the HA container).
- Place GIF files in `/config/www/idotmatrix/gifs/` for easy access.

**GIF uploads are slow**
- This is expected when using a Bluetooth proxy. Each BLE packet must round-trip through WiFi -> proxy -> BLE -> device and back. A 60KB file takes ~10-15 seconds.
- A log line « Fast transfer to … failed; resending with acknowledged writes » means the link lost unacknowledged writes; that file is resent fast once more, then with slower confirmed writes, and the next file starts fast again.
- For faster uploads, use a direct Bluetooth adapter on your HA server instead of a proxy.
- Pre-resize GIFs to 64x64 to minimize file size and transfer time.

**Icons not showing**
- For `mdi:` icons, make sure Home Assistant has internet access on first render (the font + metadata are fetched and cached in memory).
- For custom icons, use PNG URLs (`/local/...png` or `https://...png`).
- SVG URLs require Cairo; install it and restart if you need SVG rasterization.

**Designer card changes not showing**
- Hard-refresh the browser after updating `idotmatrix-card.js`.
- If you run `run_ha_dev.sh`, it rewrites `config/configuration.yaml` and uses port 8128.

---

<p align="center">
  Built with love by Tukies, based on great work of @derkalle4 who created python interface to communicate with iDotMatrix.<br>
  A big thank you to <a href="https://github.com/scarolan">Sean Carolan (@scarolan)</a> for contributing GIF uploads, BLE proxy improvements, animated dashboards, clocks, messages, and detailed setup documentation in <a href="https://github.com/tukies/iDotMatrix-HomeAssistant/pull/8">PR #8</a>.
</p>


## Maintenance controls and notifications

Use the device's **Disconnect** button to release Bluetooth for the phone app. Dashboard tracking stops and integration writes remain suspended until you press **Reconnect**. Disabling or unloading the integration also releases its Bluetooth connection after active writes finish.

For a fullscreen visual notification:

```yaml
action: idotmatrix.show_color
data:
  color: [255, 0, 0]
```

Send `[0, 0, 0]` for black, or select another display mode afterward. This uses the native fullscreen-color command.

**Text Perfect Fit** temporarily enables multiline rendering. Turning it off restores your previous multiline setting. If updating from an older release with stuck multiline text, turn Perfect Fit off once to return to scrolling text.

The Bluetooth client currently supports one active panel per Home Assistant instance. Address normalization and duplicate-entry checks protect repeated setup/discovery. Do not delete registry files to repair old duplicate devices; see the [historical issue audit](docs/ISSUE_AUDIT.md) for the remaining investigation.

## Card controls (1.4+)

The card has four sections: **Designer**, **Displays**, **GIFs**, and **Messages**. Displays exposes Clock, Weather, CO₂, Power, Thermostats, Bitcoin, Sun, Moon, and Solid color, with their stop/update controls. Panel connection controls are available below each section.

Choose the panel size before sending. Designer supports 16, 32, and 64 pixels; dashboards and messages support 32 and 64. Saved designs retain the panel size and explicit refresh entity. Sending a design switches the integration to Designer output.

Optional defaults can be stored in card configuration:

```yaml
type: custom:idotmatrix-card
title: Office display
screen_size: 64
default_view: displays
default_mode: weather
gif_path: /media/idotmatrix/gifs/
gif_interval: 10
display_options:
  weather:
    weather_entity: weather.home
    follow: true
  co2:
    co2_entity: sensor.living_room_co2
  clock:
    face: analog
    hour24: true
```

The card is bundled with its runtime; no external CDN is needed. After updating, restart Home Assistant and refresh your dashboard browser.

### Developing and testing the card

Edit `frontend/idotmatrix-card.js` and `frontend/card-model.js`, then run:

```sh
npm ci
npm test
npm run build
```

Commit the rebuilt `custom_components/idotmatrix/www/idotmatrix-card.js` with source changes. CI checks that the bundle is current. Third-party runtime licenses are included alongside the bundle.

For browser testing with the real Python preview renderer and simulated device writes:

```sh
PYTHONPATH=. .venv/bin/python scripts/card_dev_server.py
```

Open `http://127.0.0.1:8129`. The harness provides light/dark, width, and failure controls. It uses sample entities and temporary design data, not your live Home Assistant configuration or panel.
