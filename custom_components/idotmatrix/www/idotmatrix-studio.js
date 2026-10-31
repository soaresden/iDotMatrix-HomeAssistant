// Pixel Studio panel for the iDotMatrix integration.
//
// Everything heavy happens in the browser: videos, GIFs and images of any
// size are decoded locally, cropped, trimmed, resampled and tuned, with an
// instant LED preview. Several files can be prepared in a workspace; only
// the resulting screen-sized frames are pushed to Home Assistant, which
// encodes the device GIF at full quality and keeps it in a gallery.
// Plain web component: no build step.

const SLIDERS = [
  // key, label, min, max, step
  ["speed", "Vitesse ×", 0.25, 4, 0.05],
  ["brightness", "Luminosité", 0, 3, 0.05],
  ["contrast", "Contraste", 0, 3, 0.05],
  ["saturation", "Saturation", 0, 3, 0.05],
  ["gamma", "Gamma", 0.2, 3, 0.05],
  ["sharpen", "Netteté", 0, 2, 0.05],
  ["black_level", "Seuil du noir", 0, 80, 1],
];
const HINTS = {
  speed: "Vitesse de lecture du GIF final (et de l'aperçu de la source)",
  sharpen: "Rend les contours plus nets une fois l'image réduite à 64×64",
  black_level: "Les pixels plus sombres que ce seuil deviennent noirs (LED éteintes) au lieu de briller faiblement",
};
const DEFAULTS = {
  fit: "crop", crop: null, start: 0, end: null, fps: 25, speed: 1, brightness: 1, contrast: 1,
  saturation: 1, gamma: 1, sharpen: 0, black_level: 0, boomerang: true, dither: false,
  // The « Équilibré » render: judged perfect on the panel, and 4 KB packets now
  // go out in about 0.6 s, so 128 colours at 15 images/s send in a couple of minutes.
  fuzz: 8, colors: 128, max_fps: 15, merge_similar: true,
};
// « Allègement »: how far (per colour channel) a pixel may drift from what the panel shows
// before it is sent again. Video noise otherwise makes every frame a full one.
const FUZZ_LEVELS = [[0, "aucun (exact)"], [12, "léger"], [24, "normal"], [36, "fort"], [48, "très fort"]];
const COLOR_LEVELS = [256, 128, 64, 32, 16];
const FPS_CAPS = [[0, "comme la source"], [25, "25 / s"], [15, "15 / s"], [10, "10 / s"], [8, "8 / s"]];
// Ready-made renders, from the quickest send to the most faithful.
const RENDERS = [
  { key: "rapide", label: "⚡ Transfert rapide", max_fps: 10, colors: 64, fuzz: 24, merge_similar: true, dither: false,
    hint: "10 images/s, 64 couleurs, allègement normal : le plus léger et le plus rapide à envoyer, mais des traînées possibles" },
  { key: "equilibre", label: "⚖ Équilibré", max_fps: 15, colors: 128, fuzz: 8, merge_similar: true, dither: false,
    hint: "15 images/s, 128 couleurs, allègement léger" },
  { key: "fidele", label: "🎯 Le plus fidèle", max_fps: 0, colors: 256, fuzz: 0, merge_similar: false, dither: false,
    hint: "toutes les images, 256 couleurs, chaque pixel exact (aucune traînée) : le plus lourd" },
];
const RENDER_KEYS = ["max_fps", "colors", "fuzz", "merge_similar", "dither"];
const renderOf = (o) => RENDERS.find((r) => RENDER_KEYS.every((k) => (r[k] || 0) === ((k === "colors" ? o[k] ?? 256 : k === "fuzz" ? o[k] ?? DEFAULTS.fuzz
  : k === "merge_similar" ? o[k] !== false : o[k]) || 0)))?.key || "custom";
// Commands acting on one display: they go to the display picked in the status bar.
const PER_DISPLAY = new Set(["info", "display", "live", "routines", "routine_start", "routine_next", "routine_stop",
  "status", "screen", "schedule_save", "weather_preview", "store_list", "store_item", "store_import"].map((name) => `idotmatrix/studio/${name}`));
// The official app's store tabs (the server names them in Chinese, see gif_store.py).
const STORE_GROUPS = [["daily", "Quotidien"], ["emoji", "Émotions"], ["holiday", "Fêtes"], ["creative", "Créatif"], ["business", "Pro"]];
// The weather clock's minute sends (not files: no bar, no message for them).
const WEATHER_SEND = "météo";
const WEATHER_REFRESH = [[900, "15 min"], [1800, "30 min"], [3600, "1 h"]];
// Each part's sizes in meteo.py (SIZES): smallest, biggest.
// The parts a screen can have (meteo.py WEATHER_PARTS, PAGE_PARTS) and their names.
const WEATHER_PARTS = { clock: "Heure", seconds: "Secondes", date: "Date", name: "Ville", today: "Météo du jour", strip: "En bas",
  days: "Prochains jours", sun: "Lever / coucher",
  special: "Fêtes", birthdays: "Anniversaires", countdown: "Compte à rebours", reminders: "N'oubliez pas", notes: "Notes",
  saint: "Saint du jour", world_days: "Journées mondiales", agenda: "Agenda", thought: "Philosophie",
  humor: "Citations marrantes", proverb: "Dictons", fact: "Savoir inutile", motivation: "Courage", wellbeing: "Bien-être",
  word: "Mot du jour" };
const WEATHER_VIEW = ["clock", "seconds", "date", "name", "today", "strip"];
// « + »: an empty screen, or one already filled (meteo.py SCREEN_PRESETS), changed afterwards.
const WEATHER_PRESETS = [["empty", "Vide"], ["weather", "Météo"],
  ...Object.keys(WEATHER_PARTS).filter((k) => !WEATHER_VIEW.includes(k)).map((k) => [k, WEATHER_PARTS[k]])];
const WEATHER_SIZES = { clock: [1, 2], seconds: [1, 3], date: [1, 2], name: [1, 2], today: [1, 3], strip: [1, 2], days: [1, 2], sun: [1, 2] };
Object.keys(WEATHER_PARTS).forEach((k) => { WEATHER_SIZES[k] ||= [1, 3]; });
const WEATHER_DAYS = ["L", "M", "M", "J", "V", "S", "D"];
const PAGE_NAMES = { special: "jour spécial", agenda: "agenda", saint: "saint du jour", world_days: "journée mondiale",
  thought: "citation", proverb: "dicton", fact: "savoir inutile", motivation: "phrase motivante", humor: "pour rire",
  wellbeing: "bien-être" };
const ROUTINE_COLORS = ["#1e88e5", "#43a047", "#fb8c00", "#8e24aa", "#00acc1", "#e53935", "#6d4c41", "#3949ab"];
// Days of the week as the schedule numbers them (0 = Monday).
const WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const today = () => (new Date().getDay() + 6) % 7;
/** Whether a schedule block runs on `day` (no days: every day). */
const onDay = (block, day) => !block.days?.length || block.days.includes(day);
// An error as text: Home Assistant's are {code, message}, sometimes without a message.
const errorText = (err) => err?.message || err?.code || (typeof err === "object" ? JSON.stringify(err) : String(err));
const toMinutes = (hm) => { const [h, m] = hm.split(":").map(Number); return h * 60 + m; };
// Which schedule block wins an overlap, as on the server: highest priority,
// then the shortest (an all-day routine is a background), then the first listed.
const PRIORITIES = [[2, "⬆ haute"], [1, "normale"], [0, "⬇ basse"]];
const blockMinutes = (b) => ((toMinutes(b.to) - toMinutes(b.from) + 1440) % 1440) || 1440;
const outranks = (a, i, b, j) => ((b.priority ?? 1) - (a.priority ?? 1)) || (blockMinutes(a) - blockMinutes(b)) || (i - j);
const fromMinutes = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
const LIVE_INTERVAL_MS = 250;  // stills offered to the display while playing live (it takes what it can)
const VIDEO_SECONDS = 8;      // default clip length taken from a video
const FRAME_CACHE_EXTRA = 120;  // video frames kept outside the current window, for quick re-trims
const ANIMATED_SECONDS = 20;  // longest animation kept by default
const UNLIT = 28;             // colour of an unlit LED in the preview

const STYLE = `
  :host { display: block; min-height: 100vh; background: var(--primary-background-color);
    color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  .top { position: sticky; top: 0; z-index: 5; box-shadow: 0 2px 6px rgba(0,0,0,.25); }
  header { display: flex; align-items: center; gap: 12px; padding: 0 16px; height: 52px;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, var(--text-primary-color, #fff)); }
  header h1 { font-size: 20px; font-weight: 400; margin: 0; flex: 1; white-space: nowrap; }
  header .menu { display: none; background: none; border: 0; color: inherit; font-size: 22px; padding: 6px; cursor: pointer; }
  :host([narrow]) header .menu { display: block; }
  .tabs { display: flex; }
  .tabs button { background: none; border: 0; color: inherit; font: inherit; padding: 8px 12px; height: 52px;
    opacity: .7; cursor: pointer; border-bottom: 3px solid transparent; white-space: nowrap; }
  .tabs button.on { opacity: 1; border-color: currentColor; }
  .status { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 2px 12px;
    padding: 6px 16px; background: var(--card-background-color); border-bottom: 1px solid var(--divider-color); }
  .status .sprev { width: 44px; height: 44px; border-radius: 6px; background: #000; image-rendering: pixelated;
    grid-row: span 2; object-fit: contain; }
  .status .sprev.none { visibility: hidden; }
  .selbar[hidden] { display: none; }
  .status .sline { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 10px; min-width: 0; font-size: 14px; }
  .status .dsel { font: inherit; font-weight: 600; max-width: min(60vw, 320px); padding: 2px 4px; }
  .status .sline2 { font-size: 12px; color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .status .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 5px; background: #9e9e9e; }
  .status .dot.on { background: var(--success-color, #43a047); }
  .status .sacts { grid-row: span 2; display: flex; gap: 4px; }
  .status .upnext { grid-column: 1 / -1; }
  .upnext { display: flex; gap: 4px; overflow-x: auto; padding: 4px 0; scrollbar-width: thin; }
  .upnext:empty { display: none; }
  .upnext .th { flex: 0 0 auto; width: 32px; height: 32px; padding: 0; border: 2px solid transparent; border-radius: 5px;
    background: #000; cursor: default; position: relative; }
  .upnext button.th[data-upnext] { cursor: pointer; }
  .upnext .th img { width: 100%; height: 100%; image-rendering: pixelated; border-radius: 3px; display: block; }
  .upnext .th.now { border-color: var(--primary-color); }
  .upnext .th.est { border-style: dashed; }
  .upnext .th i { position: absolute; left: 1px; top: 0; font: 9px/1 sans-serif; font-style: normal; color: #fff; text-shadow: 0 0 2px #000; }
  .routine .upnext { padding: 0 0 6px 34px; }
  .modes { display: inline-flex; border: 1px solid var(--divider-color); border-radius: 10px; overflow: hidden; }
  .modebtn { border: 0; background: none; color: inherit; font: inherit; padding: 8px 16px; cursor: pointer; opacity: .7; }
  .modebtn.on { background: var(--primary-color); color: var(--text-primary-color, #fff); opacity: 1; }
  .modecard p { margin: 6px 0 0; }
  .srow.off { opacity: .5; }
  .logbar { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 8px; }
  .logrow { border-bottom: 1px solid var(--divider-color); padding: 4px 0; font-size: 13px; }
  .logrow summary { cursor: pointer; list-style: none; display: flex; gap: 8px; align-items: baseline; }
  .logrow summary::-webkit-details-marker { display: none; }
  .logrow .when { color: var(--secondary-text-color); font-variant-numeric: tabular-nums; flex: 0 0 auto; }
  .logrow .kind { flex: 0 0 auto; font-size: 11px; }
  .logrow.error summary, .logrow.warning summary { color: var(--error-color, #db4437); }
  .logrow pre { white-space: pre-wrap; word-break: break-all; font-size: 11px; margin: 4px 0 4px 24px;
    max-height: 320px; overflow: auto; background: var(--secondary-background-color); padding: 6px; border-radius: 6px; }
  .status .transfer, .status .jobs, .status .work { grid-column: 1 / -1; min-width: 0; }
  .status .transfer:empty, .status .jobs:empty, .status .work:empty { display: none; }
  .status .tline { display: flex; gap: 8px; align-items: center; font-size: 13px; padding-top: 4px; min-width: 0; }
  .status .tline .ellipsis { flex: 0 1 auto; max-width: 40%; }
  .status .tline progress { flex: 1 1 60px; min-width: 40px; height: 6px; }
  .pill { border-radius: 10px; padding: 1px 8px; font-size: 12px; background: var(--secondary-background-color); white-space: nowrap; }
  .pill.off { background: #263238; color: #cfd8dc; }
  main { padding: 16px; margin: 0 auto; box-sizing: border-box; }
  @media (max-width: 600px) {
    header { padding: 0 4px 0 8px; gap: 4px; }
    header h1 { display: none; }
    .tabs { flex: 1; justify-content: space-around; }
    .tabs button { padding: 8px 6px; }
    .status { padding: 6px 10px; gap: 2px 8px; }
    main { padding: 10px; }
    .controls label.slider { grid-template-columns: 84px 1fr 38px; gap: 6px; }
    .grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
  }
  @media (pointer: coarse) {
    .icon { min-width: 40px; min-height: 40px; }
    button.act { padding: 10px 14px; }
    button.act.small { padding: 8px 10px; }
    input[type=range] { height: 28px; }
  }
  .card { background: var(--card-background-color); border-radius: 12px; padding: 16px;
    border: 1px solid var(--divider-color); }
  button.act { background: var(--primary-color); color: var(--text-primary-color, #fff); border: 0;
    border-radius: 8px; padding: 8px 14px; font: inherit; cursor: pointer; }
  button.act.ghost { background: none; color: var(--primary-color); border: 1px solid var(--divider-color); }
  button.act:disabled { opacity: .5; cursor: default; }
  .bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px; }
  .grow { flex: 1; }
  .muted { color: var(--secondary-text-color); font-size: 13px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px; }
  .item { background: var(--card-background-color); border: 1px solid var(--divider-color);
    border-radius: 12px; overflow: hidden; display: flex; flex-direction: column; }
  .item img, .item canvas { width: 100%; aspect-ratio: 1; background: #000; image-rendering: pixelated; display: block; }
  .item .meta { padding: 8px 10px 4px; }
  .item .title { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .item .tools { display: flex; justify-content: space-between; padding: 4px 6px 8px; margin-top: auto; }
  .item { position: relative; }
  .item.selecting { cursor: pointer; }
  .item.selected { outline: 3px solid var(--primary-color); outline-offset: -3px; }
  .item .check { position: absolute; top: 4px; left: 4px; font-size: 22px; color: #fff; text-shadow: 0 0 3px #000;
    background: none; border: 0; padding: 2px 4px; cursor: pointer; opacity: .55; }
  .item .check:hover, .item.selected .check { opacity: 1; }
  .item .badges { display: flex; flex-wrap: wrap; gap: 4px; margin: 4px 0 2px; }
  .chips { display: flex; gap: 6px; overflow-x: auto; padding: 2px 0 10px; }
  details.menu { display: inline-flex; flex: 0 0 auto; }
  details.menu > summary { list-style: none; cursor: pointer; }
  details.menu > summary::-webkit-details-marker { display: none; }
  details.menu .menu-list { position: fixed; z-index: 30; display: flex; flex-direction: column; gap: 2px; min-width: 210px;
    padding: 6px; background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 10px;
    box-shadow: 0 8px 20px rgba(0,0,0,.4); }
  details.menu .menu-list button { justify-content: flex-start; text-align: left; white-space: nowrap; width: 100%; }
  details.menu .menu-list .muted { padding: 4px 8px; }
  .chips:empty { display: none; }
  .chip-btn { flex: none; border: 1px solid var(--divider-color); background: var(--card-background-color); color: inherit;
    border-radius: 16px; padding: 6px 12px; font: inherit; font-size: 13px; cursor: pointer; white-space: nowrap; }
  .chip-btn.on { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .chip-btn.on .muted { color: inherit; opacity: .8; }
  .chip-btn.ghost { border-style: dashed; color: var(--secondary-text-color); }
  .chip-input { flex: none; border: 1px solid var(--primary-color); border-radius: 16px; padding: 6px 12px; font: inherit;
    font-size: 13px; background: var(--card-background-color); color: inherit; }
  .orig .check { font-size: 20px; color: var(--primary-color); }
  .orig.selected .orow { background: var(--secondary-background-color); border-radius: 8px; }
  /* Search, filters, folders and the selection bar stay in view under the status bar (--top-h). */
  .filterbar { position: sticky; top: var(--top-h, 112px); z-index: 4; background: var(--primary-background-color);
    margin: -16px -16px 10px; padding: 10px 16px 4px; box-shadow: 0 6px 6px -6px rgba(0,0,0,.3); }
  @media (max-width: 600px) { .filterbar { margin: -10px -10px 8px; padding: 8px 10px 2px; } }
  .filterbar .chips { margin-bottom: 6px; }
  .selbar { z-index: 3; display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
    padding: 8px 10px; margin-bottom: 10px; border-radius: 10px; background: var(--card-background-color);
    border: 1px solid var(--primary-color); }
  button.act.danger, button.armed { background: var(--error-color, #db4437); color: #fff; border-color: transparent; }
  .icon { background: none; border: 0; color: var(--secondary-text-color); cursor: pointer;
    font-size: 18px; padding: 6px; border-radius: 8px; }
  .icon:hover { background: var(--secondary-background-color); }
  .icon:disabled { opacity: .3; cursor: default; background: none; }
  .icon.fav { color: #f5b400; }
  .drop { border: 2px dashed var(--divider-color); border-radius: 12px; padding: 24px 16px;
    text-align: center; margin-bottom: 16px; }
  .drop.over { border-color: var(--primary-color); background: var(--secondary-background-color); }
  .editor { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 16px; }
  /* minmax(0, …): a 1920 px video must not widen the column before it is sized. */
  @media (max-width: 800px) { .editor { grid-template-columns: minmax(0, 1fr); } }
  @media (min-width: 1100px) {
    .editor { grid-template-columns: minmax(0, 1.3fr) minmax(0, .9fr) minmax(0, 1fr); align-items: start; gap: 12px; }
    .editor .card { padding: 12px; }
    .editor .row { margin: 6px 0; }
    .editor .controls label.slider { margin: 3px 0; }
  }
  .ledmini, .ledmini[hidden] { display: none; }
  @media (max-width: 800px) {
    .ledmini { display: block; position: fixed; right: 10px; bottom: 10px; z-index: 6; width: 104px; height: 104px;
      border-radius: 8px; background: #000; box-shadow: 0 2px 10px rgba(0,0,0,.6); border: 1px solid var(--divider-color); }
    .ledmini[hidden] { display: none; }
  }
  .stagebar { display: none; gap: 8px; align-items: center; margin-bottom: 8px; }
  .stagebar .act { min-width: 56px; font-size: 18px; }
  @media (max-width: 800px) { .stagebar { display: flex; } }
  .stage { position: relative; display: inline-block; max-width: 100%; line-height: 0;
    background: #000; touch-action: none; }
  .stage img, .stage video, .stage canvas { display: block; max-width: 100%; }
  .crop { position: absolute; border: 2px solid #fff; box-shadow: 0 0 0 9999px rgba(0,0,0,.55);
    cursor: move; box-sizing: border-box; }
  .crop .handle { position: absolute; right: -9px; bottom: -9px; width: 18px; height: 18px;
    background: #fff; border-radius: 50%; cursor: nwse-resize; }
  .trim { position: relative; height: 34px; margin: 14px 8px 4px; border-radius: 6px; touch-action: none;
    background: var(--secondary-background-color); cursor: pointer; clip-path: inset(-12px 0 -12px 0); }
  .overview { position: relative; height: 10px; margin: 10px 8px 0; border-radius: 3px; cursor: pointer;
    background: var(--secondary-background-color); touch-action: none; }
  .overview .ov-sel { position: absolute; top: 0; bottom: 0; background: rgba(3, 169, 244, .45); }
  .overview .ov-view { position: absolute; top: -2px; bottom: -2px; border: 2px solid var(--primary-text-color);
    border-radius: 3px; box-sizing: border-box; pointer-events: none; }
  .overview .ov-head { position: absolute; top: -3px; bottom: -3px; width: 2px; background: #fff; pointer-events: none; }
  .trim .sel { position: absolute; top: 0; bottom: 0; background: rgba(3, 169, 244, .25);
    border-top: 2px solid var(--primary-color); border-bottom: 2px solid var(--primary-color); box-sizing: border-box; }
  .trim .h { position: absolute; top: -5px; bottom: -5px; width: 18px; margin-left: -9px; border-radius: 4px;
    background: var(--primary-color); cursor: ew-resize; }
  @media (pointer: coarse) {
    .trim { height: 46px; }
    .trim .h { width: 30px; margin-left: -15px; top: -8px; bottom: -8px; }
  }
  .trim .key.pin { transform: none; border-radius: 50%; background: #ff5252; }
  .stage.pointing, .stage.pointing * { cursor: crosshair !important; }
  .trim .key { position: absolute; top: 50%; width: 9px; height: 9px; margin: -5px 0 0 -5px; transform: rotate(45deg);
    background: #ffc107; border: 1px solid #000; pointer-events: none; }
  .trim .head { position: absolute; top: -8px; bottom: -8px; width: 3px; margin-left: -1px; background: #fff;
    box-shadow: 0 0 4px rgba(0,0,0,.8); border-radius: 2px; pointer-events: none; }
  .routine.active { border-color: var(--primary-color); }
  .sched { margin-bottom: 16px; }
  .day { position: relative; height: 44px; border-radius: 8px; overflow: hidden; cursor: copy; touch-action: manipulation;
    background: repeating-linear-gradient(90deg, var(--secondary-background-color) 0 calc(100% / 24 - 1px),
      var(--divider-color) calc(100% / 24 - 1px) calc(100% / 24)); }
  .day.disabled { opacity: .45; }
  .srow .days { display: inline-flex; gap: 2px; }
  .routine .rsched { padding: 2px 8px 8px 44px; display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
  .routine .rsched.off { opacity: .45; }
  .qrow { padding: 4px 0; border-bottom: 1px solid var(--divider-color); }
  .switch { display: inline-flex; align-items: center; cursor: pointer; flex: none; }
  .switch input { display: none; }
  .switch span { min-width: 38px; text-align: center; padding: 3px 6px; border-radius: 12px; font-size: 12px; font-weight: 600;
    background: var(--disabled-color, #9e9e9e); color: #fff; }
  .switch input:checked + span { background: var(--success-color, #43a047); }
  .srow .days button { min-width: 26px; padding: 2px 3px; border: 1px solid var(--divider-color); background: none;
    border-radius: 4px; font: inherit; font-size: 11px; color: var(--secondary-text-color); cursor: pointer; }
  .srow .days button.on { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; }
  .day.gapoff { background: repeating-linear-gradient(135deg, #263238 0 6px, #1e2a30 6px 12px); }
  .day .blk { cursor: grab; touch-action: none; }
  .day .blk .h { position: absolute; top: 0; bottom: 0; width: 9px; cursor: ew-resize; }
  .day .blk .h.l { left: 0; border-left: 3px solid rgba(255,255,255,.55); }
  .day .blk .h.r { right: 0; border-right: 3px solid rgba(255,255,255,.55); }
  .day .blk { position: absolute; top: 4px; bottom: 4px; border-radius: 6px; color: #fff; font-size: 12px; cursor: pointer;
    display: flex; align-items: center; justify-content: center; overflow: hidden; box-shadow: inset 0 0 0 1px rgba(0,0,0,.3); }
  .day .blk span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 0 4px; }
  .day .blk.off { background: #263238 !important; color: #cfd8dc; }
  .day .now { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: #ff5252; pointer-events: none; }
  .ticks { position: relative; height: 16px; margin: 2px 0 8px; font-size: 11px; color: var(--secondary-text-color); }
  .ticks span { position: absolute; transform: translateX(-50%); }
  .ticks span:first-child { transform: none; }
  .ticks span:last-child { transform: translateX(-100%); }
  .srow { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 4px 2px; border-top: 1px solid var(--divider-color); }
  .srow.flash { background: var(--secondary-background-color); }
  .srow select { flex: 1 1 150px; min-width: 0; }
  .swatch { width: 12px; height: 12px; border-radius: 3px; flex: none; }
  .routine-status { padding: 0 0 6px 34px; }
  .routine-editor .row b { margin-right: 4px; }
  .pick-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(92px, 1fr)); gap: 6px; max-height: 50vh; overflow: auto; }
  .pick { position: relative; display: flex; flex-direction: column; gap: 2px; padding: 4px; border-radius: 8px;
    border: 2px solid transparent; cursor: pointer; background: var(--secondary-background-color); }
  .pick.on { border-color: var(--primary-color); }
  .pick img { width: 100%; aspect-ratio: 1; image-rendering: pixelated; background: #000; border-radius: 4px; }
  .pick input { position: absolute; top: 6px; left: 6px; }
  .toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 6px; }
  .toolbar input[type=search] { flex: 1 1 160px; min-width: 120px; }
  main.over { outline: 2px dashed var(--primary-color); outline-offset: -8px; }
  .small { font-size: 12px; }
  .ellipsis { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ellipsis .title { font-weight: 500; margin-right: 8px; }
  #tree { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; }
  .orig { background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 10px; padding: 4px 8px; }
  .orow, .crow { display: flex; align-items: center; gap: 6px; min-height: 36px; }
  .othumb { width: 64px; height: 36px; background: #000; border-radius: 4px; flex: none; }
  .clips { margin: 2px 0 4px 34px; padding-left: 8px; border-left: 2px solid var(--divider-color); }
  .crow { border-top: 1px solid var(--divider-color); }
  .crow:first-child { border-top: 0; }
  .cthumb { width: 32px; height: 32px; background: #000; border-radius: 4px; flex: none; }
  .crow select { padding: 2px 4px; }
  .chip { font-size: 11px; color: var(--success-color, #43a047); white-space: nowrap; }
  .chip:empty { display: none; }
  .fold { padding: 2px 4px; font-size: 14px; }
  .icon { padding: 4px; font-size: 16px; }
  .act.small { padding: 4px 8px; font-size: 13px; }
  .icon.todo { color: var(--primary-color); }
  .warn { color: var(--warning-color, #ff9800); }
  @media (max-width: 600px) {
    .clips { margin-left: 8px; }
    .crow { flex-wrap: wrap; }
    .crow .ellipsis { flex: 1 1 60%; }
  }
  .controls label.slider { display: grid; grid-template-columns: 110px 1fr 44px; align-items: center;
    gap: 8px; font-size: 14px; margin: 6px 0; }
  .controls input[type=range] { width: 100%; }
  .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 8px 0; }
  .row label { display: flex; gap: 6px; align-items: center; }
  input[type=text], input[type=search], input[type=number], input[type=time], select { background: var(--secondary-background-color);
    color: inherit; border: 1px solid var(--divider-color); border-radius: 6px; padding: 6px 8px; font: inherit; }
  input[type=number] { width: 72px; }
  .preview { text-align: center; }
  .preview canvas { width: 100%; max-width: min(320px, max(180px, calc(100vh - 470px))); aspect-ratio: 1; background: #000; border-radius: 8px; }
  .stats { display: flex; flex-wrap: wrap; justify-content: center; gap: 6px 14px; margin-top: 8px; }
  .final { width: 48px; height: 48px; image-rendering: pixelated; vertical-align: middle; background: #000; }
  progress { width: 100%; height: 8px; }
  .error { color: var(--error-color, #db4437); }
  .ok { color: var(--success-color, #43a047); }
  .empty { text-align: center; padding: 32px 0; }
  .wgrid { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }
  /* The preview stays in view while the settings scroll; its parts are picked and dragged on it. */
  .wside { position: sticky; top: calc(var(--top-h, 0px) + 8px); z-index: 3; flex: none; width: min(256px, 100%);
    background: var(--card-background-color); padding-bottom: 4px; }
  .act.ghost.on { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .wled { width: 100%; aspect-ratio: 1; background: #000; border-radius: 8px; display: block; touch-action: none; cursor: pointer; }
  .wnums { gap: 3px; padding-bottom: 4px; }
  .wnums .chip-btn { padding: 1px 8px; font-size: 12px; }
  .wnums .chip-btn.pinned { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .wpick { text-decoration: underline dotted; cursor: pointer; margin-right: 6px; }
  .wpick.on { color: var(--primary-color); font-weight: 600; }
  .wnums { gap: 5px; }
  .wnums .chip-btn { min-width: 36px; min-height: 34px; font-size: 15px; font-weight: 600; justify-content: center; }
  .wnums .chip-btn.off { opacity: .45; }
  .woverlay { position: fixed; inset: 0; z-index: 40; background: rgba(0, 0, 0, .6); display: flex; align-items: center; justify-content: center; }
  .woverlay .box { background: var(--card-background-color); border-radius: 14px; padding: 16px; width: min(460px, 92vw); max-height: 86vh; overflow: auto; }
  .woverlay .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 10px 0; }
  .woverlay .grid .chip-btn { justify-content: center; padding: 10px 6px; }
  .woverlay .grid .first { border-color: var(--primary-color); }
  .wnums .plus { border-style: dashed; }
  .wpart { display: inline-flex; gap: 4px; align-items: center; }
  .wpart b { font-weight: 400; cursor: pointer; opacity: .7; }
  #wscreen input[type=number] { width: 60px; }
  @media (max-width: 600px) { .wside { width: 100%; } .wled { width: 160px; } }
  .wform { flex: 1 1 280px; min-width: 0; }
  .wform .row b { min-width: 64px; }
  .wform select { max-width: 100%; }
  .wprof { border: 1px solid var(--divider-color); border-radius: 10px; padding: 0 10px; margin: 8px 0; }
  .wform input[type=number] { width: 52px; }
  .wform input[type=color] { width: 36px; height: 28px; padding: 0; border: 0; background: none; }
`;

// ------------------------------------------------------------------ media

const esc = (text) => String(text).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const kb = (bytes) => `${(bytes / 1024).toFixed(1)} Ko`;
const duration = (seconds) => (seconds < 90 ? `~${Math.round(seconds)} s` : `~${Math.round(seconds / 60)} min`);
const VIDEO_EXT = /\.(avi|mp4|m4v|mov|mkv|webm|wmv|flv|mpe?g|3gp|ts|mts|m2ts|ogv|vob|divx|xvid|asf)$/i;
const IMAGE_EXT = /\.(gif|png|jpe?g|webp|bmp|avif|apng|ico|svg)$/i;
const clock = (seconds) => {
  const m = Math.floor(seconds / 60);
  const s = (seconds - m * 60).toFixed(1);
  return m ? `${m}:${s.padStart(4, "0")}` : `${s} s`;
};
const isVideo = (file) => file.type.startsWith("video/") || (!file.type && VIDEO_EXT.test(file.name));
const isImage = (file) => file.type.startsWith("image/") || (!file.type && IMAGE_EXT.test(file.name));

/**
 * Minimal GIF decoder: composited RGBA frames and their durations.
 * Browsers only expose animation frames (ImageDecoder) on HTTPS pages, and
 * Home Assistant is often reached over plain HTTP on the local network.
 */
function decodeGif(buffer) {
  const b = new Uint8Array(buffer);
  if (String.fromCharCode(...b.subarray(0, 3)) !== "GIF") throw new Error("not a GIF");
  const width = b[6] | (b[7] << 8);
  const height = b[8] | (b[9] << 8);
  let pos = 13;
  const readTable = (flags) => {
    const count = 2 << (flags & 7);
    const table = b.subarray(pos, pos + count * 3);
    pos += count * 3;
    return table;
  };
  const globalTable = b[10] & 0x80 ? readTable(b[10]) : null;
  const canvas = new Uint8ClampedArray(width * height * 4);
  const frames = [];
  let gce = { delay: 10, disposal: 0, transparent: -1 };
  while (pos < b.length) {
    const block = b[pos++];
    if (block === 0x3b) break;
    if (block === 0x21) {
      const label = b[pos++];
      if (label === 0xf9) {
        const packed = b[pos + 1];
        gce = { delay: b[pos + 2] | (b[pos + 3] << 8), disposal: (packed >> 2) & 7,
          transparent: packed & 1 ? b[pos + 4] : -1 };
      }
      while (b[pos]) pos += b[pos] + 1;
      pos++;
      continue;
    }
    if (block !== 0x2c) break;
    const fx = b[pos] | (b[pos + 1] << 8);
    const fy = b[pos + 2] | (b[pos + 3] << 8);
    const fw = b[pos + 4] | (b[pos + 5] << 8);
    const fh = b[pos + 6] | (b[pos + 7] << 8);
    const flags = b[pos + 8];
    pos += 9;
    const table = flags & 0x80 ? readTable(flags) : globalTable;
    const minCode = b[pos++];
    const chunks = [];
    while (b[pos]) { chunks.push(b.subarray(pos + 1, pos + 1 + b[pos])); pos += b[pos] + 1; }
    pos++;
    const data = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
    chunks.reduce((offset, c) => { data.set(c, offset); return offset + c.length; }, 0);
    const indices = lzwDecode(data, minCode, fw * fh);
    const previous = gce.disposal === 3 ? canvas.slice() : null;
    const rows = flags & 0x40 ? interlacedRows(fh) : Array.from({ length: fh }, (_, i) => i);
    for (let r = 0; r < fh; r++) {
      const y = fy + rows[r];
      if (y >= height) continue;
      for (let x = 0; x < fw && fx + x < width; x++) {
        const index = indices[r * fw + x];
        if (index === gce.transparent || !table || index * 3 >= table.length) continue;
        const o = (y * width + fx + x) * 4;
        canvas[o] = table[index * 3]; canvas[o + 1] = table[index * 3 + 1]; canvas[o + 2] = table[index * 3 + 2]; canvas[o + 3] = 255;
      }
    }
    frames.push({ data: new ImageData(canvas.slice(), width, height), ms: gce.delay > 1 ? gce.delay * 10 : 100 });
    if (gce.disposal === 2) {
      for (let y = fy; y < Math.min(height, fy + fh); y++) canvas.fill(0, (y * width + fx) * 4, (y * width + Math.min(width, fx + fw)) * 4);
    } else if (previous) {
      canvas.set(previous);
    }
    gce = { delay: 10, disposal: 0, transparent: -1 };
  }
  return { width, height, frames };
}

function interlacedRows(height) {
  const rows = [];
  for (const [start, step] of [[0, 8], [4, 8], [2, 4], [1, 2]]) for (let y = start; y < height; y += step) rows.push(y);
  return rows;
}

function lzwDecode(data, minCode, count) {
  const out = new Uint8Array(count);
  const clear = 1 << minCode;
  const prefix = new Uint16Array(4096);
  const suffix = new Uint8Array(4096);
  const stack = new Uint8Array(4097);
  let size = minCode + 1; let mask = (1 << size) - 1; let next = clear + 2;
  let old = -1; let first = 0; let bits = 0; let datum = 0; let n = 0;
  for (let i = 0; i < data.length && n < count;) {
    while (bits < size && i < data.length) { datum |= data[i++] << bits; bits += 8; }
    if (bits < size) break;
    let code = datum & mask;
    datum >>= size; bits -= size;
    if (code === clear) { size = minCode + 1; mask = (1 << size) - 1; next = clear + 2; old = -1; continue; }
    if (code === clear + 1) break;
    if (old === -1) { out[n++] = suffix[code] = code; old = first = code; continue; }
    const incoming = code;
    let top = 0;
    if (code >= next) { stack[top++] = first; code = old; }
    while (code > clear) { stack[top++] = suffix[code]; code = prefix[code]; }
    first = code < clear ? code : suffix[code];
    stack[top++] = first;
    while (top && n < count) out[n++] = stack[--top];
    if (next < 4096) { prefix[next] = old; suffix[next] = first; next++; }
    if (next > mask && size < 12) { size++; mask = (1 << size) - 1; }
    old = incoming;
  }
  return out;
}

// ffmpeg.wasm, for videos the browser cannot decode itself (AVI, WMV, old
// codecs...). Downloaded once from the CDN at pinned versions and kept in
// the browser cache; the conversion runs entirely in this browser.
const FFMPEG_CDN = "https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.12.15/dist/esm";
const FFMPEG_CORE_CDN = "https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.10/dist/esm";
const FFMPEG_WASM_BYTES = 32232419;  // ffmpeg-core.wasm 0.12.10, for download progress
const WORKING_COPY_HEIGHT = 360;
let ffmpegLoading = null;

/** Stop the video conversion in progress (« File » tab): its worker is dropped, a new one loads when needed. */
function stopConversions() {
  const loading = ffmpegLoading;
  ffmpegLoading = null;
  loading?.then((ffmpeg) => ffmpeg.terminate()).catch(() => {});
}

async function blobUrl(url, type, { transform, onProgress, size } = {}) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`téléchargement impossible (${response.status}) : ${url}`);
  if (transform) return URL.createObjectURL(new Blob([transform(await response.text())], { type }));
  // Content-Length is the compressed size when the CDN compresses: prefer the known size.
  const total = size || Number(response.headers.get("content-length")) || 0;
  const reader = response.body.getReader();
  const chunks = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    if (onProgress && total) onProgress(Math.min(1, loaded / total));
  }
  return URL.createObjectURL(new Blob(chunks, { type }));
}

function loadFFmpeg(onProgress) {
  ffmpegLoading ||= (async () => {
    // Browsers refuse cross-origin workers: rebuild ffmpeg.wasm's worker
    // (and the two modules it imports) from same-origin blob URLs.
    const constUrl = await blobUrl(`${FFMPEG_CDN}/const.js`, "text/javascript");
    const errorsUrl = await blobUrl(`${FFMPEG_CDN}/errors.js`, "text/javascript");
    const classWorkerURL = await blobUrl(`${FFMPEG_CDN}/worker.js`, "text/javascript", {
      transform: (src) => src.replaceAll('"./const.js"', JSON.stringify(constUrl)).replaceAll('"./errors.js"', JSON.stringify(errorsUrl)),
    });
    const coreURL = await blobUrl(`${FFMPEG_CORE_CDN}/ffmpeg-core.js`, "text/javascript");
    const wasmURL = await blobUrl(`${FFMPEG_CORE_CDN}/ffmpeg-core.wasm`, "application/wasm", { onProgress, size: FFMPEG_WASM_BYTES });
    const { FFmpeg } = await import(/* webpackIgnore: true */ `${FFMPEG_CDN}/index.js`);
    const ffmpeg = new FFmpeg();
    await ffmpeg.load({ classWorkerURL, coreURL, wasmURL });
    return ffmpeg;
  })();
  ffmpegLoading.catch(() => { ffmpegLoading = null; });
  return ffmpegLoading;
}

// Video codecs this browser plays once in an MP4 (HEVC only with its hardware decoder).
const REMUXABLE = ["h264", "vp9", "av1"];
// Stream copies bigger than this would not fit ffmpeg.wasm's memory: those are re-encoded.
const REMUX_MAX_BYTES = 900 * 1024 * 1024;

function playableCodec(codec) {
  if (REMUXABLE.includes(codec)) return true;
  return codec === "hevc" && Boolean(document.createElement("video").canPlayType?.('video/mp4; codecs="hvc1.1.6.L120.90"'));
}

/** Make a video this browser cannot read into an MP4 it can, without leaving the browser.
 *
 * Often only the container is the problem (AVI, MKV, TS…): the video stream is then
 * copied into an MP4, which takes seconds. Otherwise it is re-encoded small (360p,
 * 30 fps), skipping the decoder's deblocking: ffmpeg.wasm decodes on a single thread,
 * so decoding is most of the time and this makes it noticeably faster. */
async function browserWorkingCopy(file, onStatus) {
  const ffmpeg = await loadFFmpeg((done) => onStatus(`téléchargement de ffmpeg, une seule fois (${Math.round(done * 100)} %)`));
  const dir = `/in${Date.now()}`;
  const input = `${dir}/${file.name}`;
  const output = `${dir}.mp4`;
  let what = "";
  let label = "conversion";
  const logged = ({ message }) => {
    const stream = /Stream #0:\d+.*?Video: (\w+).*?, (\d{2,5})x(\d{2,5})/.exec(message || "");
    if (stream && !what) what = `${stream[1].toUpperCase()} ${stream[2]}×${stream[3]}`;
  };
  const progress = ({ progress: done }) => {
    if (done >= 0 && done <= 1) onStatus(`${label}${what ? ` (${what})` : ""} ${Math.round(done * 100)} %`);
  };
  const result = async () => {
    const data = await ffmpeg.readFile(output);
    await ffmpeg.deleteFile(output);
    return new File([data], `${file.name.replace(/\.[^.]+$/, "")}.mp4`, { type: "video/mp4" });
  };
  await ffmpeg.createDir(dir);
  // WORKERFS reads the file in place: no copy of a large video in memory.
  await ffmpeg.mount("WORKERFS", { files: [file] }, dir);
  ffmpeg.on("log", logged);
  ffmpeg.on("progress", progress);
  try {
    onStatus("lecture du format…");
    await ffmpeg.exec(["-hide_banner", "-i", input]);  // no output: only logs the streams
    const codec = (what.split(" ")[0] || "").toLowerCase();
    if (playableCodec(codec) && file.size <= REMUX_MAX_BYTES) {
      label = "copie sans réencodage";
      onStatus(`${label} (${what})…`);
      const code = await ffmpeg.exec(["-i", input, "-map", "0:v:0", "-c:v", "copy", "-an", "-movflags", "+faststart", output]);
      if (code === 0) {
        const copy = await result();
        try {
          releaseSource(await loadSource(copy));
          return copy;
        } catch (_err) { /* the browser still cannot read it: re-encode */ }
      }
    }
    label = "conversion";
    onStatus(`${label}${what ? ` (${what})` : ""}…`);
    const code = await ffmpeg.exec([
      "-skip_loop_filter", "all", "-i", input, "-map", "0:v:0", "-an",
      "-vf", `fps=30,scale=-2:'min(${WORKING_COPY_HEIGHT},ih)':flags=fast_bilinear`,
      "-c:v", "libx264", "-preset", "ultrafast", "-tune", "fastdecode", "-crf", "26", "-pix_fmt", "yuv420p",
      "-movflags", "+faststart", output,
    ]);
    if (code !== 0) throw new Error("ffmpeg n'a pas pu convertir cette vidéo");
    return await result();
  } finally {
    ffmpeg.off("log", logged);
    ffmpeg.off("progress", progress);
    await ffmpeg.unmount(dir).catch(() => {});
    await ffmpeg.deleteDir(dir).catch(() => {});
  }
}

/** Decode a file in the browser: still image, animation (frames) or video. */
async function loadSource(file) {
  const url = URL.createObjectURL(file);
  if (isVideo(file)) {
    const video = document.createElement("video");
    Object.assign(video, { muted: true, preload: "auto", playsInline: true, src: url });
    await new Promise((resolve, reject) => {
      video.onloadedmetadata = resolve;
      video.onerror = () => reject(new Error("vidéo illisible par ce navigateur"));
    });
    return { kind: "video", url, video, width: video.videoWidth, height: video.videoHeight,
      duration: video.duration, cache: null };
  }
  let frames = null;
  if ("ImageDecoder" in window && await ImageDecoder.isTypeSupported(file.type).catch(() => false)) {
    try {
      const decoder = new ImageDecoder({ data: await file.arrayBuffer(), type: file.type });
      await decoder.tracks.ready;
      await decoder.completed;
      const count = decoder.tracks.selectedTrack.frameCount;
      frames = [];
      for (let i = 0; i < count; i++) {
        const { image } = await decoder.decode({ frameIndex: i });
        const ms = image.duration ? Math.round(image.duration / 1000) : 100;
        frames.push({ bmp: await createImageBitmap(image), ms: ms > 0 ? ms : 100 });
        image.close();
      }
      decoder.close();
    } catch (_err) {
      frames = null;
    }
  }
  if (!frames && file.type === "image/gif") {
    const gif = decodeGif(await file.arrayBuffer());
    frames = await Promise.all(gif.frames.map(async (f) => ({ bmp: await createImageBitmap(f.data), ms: f.ms })));
  }
  if (!frames || !frames.length) {
    // No animation support here (or a still image): keep the first frame.
    frames = [{ bmp: await createImageBitmap(file), ms: 1000 }];
  }
  return { kind: frames.length > 1 ? "animated" : "image", url, frames,
    width: frames[0].bmp.width, height: frames[0].bmp.height,
    duration: frames.reduce((sum, f) => sum + f.ms, 0) / 1000 };
}

/** Free a decoded source: full-size bitmaps and video buffers add up fast on phones. */
function releaseSource(src) {
  for (const f of [...(src.frames || []), ...(src.frameCache?.frames.values() || [])]) f.bmp.close?.();
  if (src.video) {
    src.video.removeAttribute("src");
    src.video.load();
  }
  URL.revokeObjectURL(src.url);
}

/** What the workspace rows show about a source, kept once it is released. */
const sourceInfo = (src) => ({
  kind: src.kind, frames: src.frames?.length || 0, width: src.width, height: src.height, duration: src.duration,
});

function seek(video, time) {
  return new Promise((resolve) => {
    video.addEventListener("seeked", resolve, { once: true });
    video.currentTime = time;
  });
}

/** Source frames inside the clip window, at a working resolution. */
async function sourceFrames(src, o, size, maxFrames, onProgress) {
  if (src.kind === "image") return src.frames;
  const start = Math.max(0, o.start || 0);
  if (src.kind === "animated") {
    const end = o.end ?? start + ANIMATED_SECONDS;
    const picked = [];
    let t = 0;
    for (const frame of src.frames) {
      const begins = t;
      t += frame.ms / 1000;
      if (t > start && begins < end) picked.push(frame);
    }
    return thin(picked.length ? picked : src.frames.slice(0, 1), maxFrames);
  }
  const end = Math.min(src.duration, o.end ?? start + VIDEO_SECONDS);
  const fps = Math.max(1, Math.min(30, o.fps || DEFAULTS.fps));
  const count = Math.max(1, Math.min(maxFrames, Math.round((end - start) * fps)));
  const scale = Math.min(1, (size * 4) / Math.min(src.width, src.height));
  const resizeWidth = Math.max(1, Math.round(src.width * scale));
  const resizeHeight = Math.max(1, Math.round(src.height * scale));
  // Frames are kept by their place on a fixed grid of the video (frame k at
  // k / fps), so moving the start or the end by a second reuses everything
  // already extracted and only seeks to the frames that are new.
  const grid = `${fps}|${resizeWidth}x${resizeHeight}`;
  if (src.frameCache?.grid !== grid) src.frameCache = { grid, frames: new Map() };
  const cache = src.frameCache.frames;
  const first = Math.ceil(start * fps - 1e-6);
  const frames = [];
  for (let i = 0; i < count; i++) {
    const k = first + i;
    let frame = cache.get(k);
    if (!frame) {
      // Before every seek: a caller that no longer needs these frames (the
      // window was changed again) throws here, so only one extraction drives
      // the video at a time. What was extracted so far stays in the cache.
      if (onProgress) onProgress(i, count);
      await seek(src.video, Math.min(src.duration, k / fps));
      frame = { bmp: await createImageBitmap(src.video, { resizeWidth, resizeHeight, resizeQuality: "high" }),
        ms: Math.round(1000 / fps) };
      cache.set(k, frame);
    }
    frames.push(frame);
  }
  if (onProgress) onProgress(count, count);
  // Keep the window and some frames around it (phones have little memory):
  // the farthest go first. They are dropped, not closed: a clip being sent
  // may still be drawing them; the browser frees them once unused.
  const keep = count + FRAME_CACHE_EXTRA;
  if (cache.size > keep) {
    const last = first + count - 1;
    const distance = (k) => (k < first ? first - k : k > last ? k - last : 0);
    for (const k of [...cache.keys()].sort((a, b) => distance(b) - distance(a)).slice(0, cache.size - keep)) cache.delete(k);
  }
  return frames;
}

function thin(frames, maxFrames) {
  if (frames.length <= maxFrames) return frames;
  const step = Math.ceil(frames.length / maxFrames);
  const out = [];
  for (let i = 0; i < frames.length; i += step) {
    out.push({ bmp: frames[i].bmp, ms: frames.slice(i, i + step).reduce((s, f) => s + f.ms, 0) });
  }
  return out;
}

/** Crop / fit / stretch one source frame onto the square screen, then tune it. */
function renderFrame(source, o, size, ctx, t = 0) {
  return toneFrame(scaleFrame(source, o, size, ctx, t), o);
}

/** A keyframed value at time t: held before the first key and after the last, linear between. */
function interpolate(keys, t, field) {
  if (t <= keys[0].t) return keys[0][field];
  if (t >= keys[keys.length - 1].t) return keys[keys.length - 1][field];
  const after = keys.findIndex((k) => k.t >= t);
  const a = keys[after - 1];
  const b = keys[after];
  return a[field] + (b[field] - a[field]) * ((t - a.t) / Math.max(1e-6, b.t - a.t));
}

/**
 * Crop square at time t. With "follow" on, its centre glides between the
 * track points (keyframes, automatic tracking or a followed point) and its
 * size between the zoom keys (s: 1 = o.crop's size), always inside the image.
 */
function cropAt(o, t) {
  const crop = o.crop;
  const track = o.follow && o.track?.length ? o.track : null;
  const zoom = o.follow && o.zoom?.length ? o.zoom : null;
  if (!crop || (!track && !zoom)) return crop;
  const [x0, y0, w0, h0] = crop;
  const s = zoom ? Math.max(0.02, Math.min(interpolate(zoom, t, "s"), 1 / w0, 1 / h0)) : 1;
  const cx = track ? interpolate(track, t, "x") : x0 + w0 / 2;
  const cy = track ? interpolate(track, t, "y") : y0 + h0 / 2;
  const w = w0 * s;
  const h = h0 * s;
  return [Math.min(Math.max(0, cx - w / 2), 1 - w), Math.min(Math.max(0, cy - h / 2), 1 - h), w, h];
}

/** Insert or replace the zoom key at time t (sorted, 50 ms tolerance). */
/**
 * ✋ Suivi perso: the square held while the video plays. Keys in the stretch
 * just played through (from → to) give way to the new one; a jump (the loop
 * going back to the start) only replaces what sits at `to`.
 */
function recordKey(keys, from, to, values) {
  const jump = Math.abs(to - from) > 1;
  const [lo, hi] = [Math.min(from, to), Math.max(from, to)];
  // What sits at `to`, and what lies strictly between the last recorded moment and `to`
  // (that last moment itself stays: it is the previous step of the recording).
  const gone = (k) => Math.abs(k.t - to) <= 0.05 || (!jump && k.t > lo && k.t < hi && Math.abs(k.t - from) > 1e-6);
  return [...keys.filter((k) => !gone(k)), { t: to, ...values }].sort((a, b) => a.t - b.t);
}

function setZoom(zoom, t, s) {
  const keys = zoom.filter((k) => Math.abs(k.t - t) > 0.05);
  keys.push({ t, s });
  return keys.sort((a, b) => a.t - b.t);
}

/** Frames as small RGB arrays (width tw), for tracking. */
function framePixels(frames, tw) {
  const first = frames[0];
  const th = Math.max(8, Math.round((tw * first.height) / first.width));
  const ctx = makeCanvas(tw, th).getContext("2d", { willReadFrequently: true });
  const pixels = frames.map((bmp) => {
    ctx.clearRect(0, 0, tw, th);
    ctx.drawImage(bmp, 0, 0, tw, th);
    const d = ctx.getImageData(0, 0, tw, th).data;
    const rgb = new Uint8Array(tw * th * 3);
    for (let i = 0; i < tw * th; i++) {
      rgb[i * 3] = d[i * 4]; rgb[i * 3 + 1] = d[i * 4 + 1]; rgb[i * 3 + 2] = d[i * 4 + 2];
    }
    return rgb;
  });
  return { pixels, tw, th };
}

/**
 * Follow points clicked on the subject (`anchors`: [{i: frame, x, y}], x/y in
 * 0..1) through every frame: a small patch around the point is looked for in
 * the next frame near where it was, compared with both the clicked patch and
 * the last one found (the subject may turn; the clicked look keeps it from
 * drifting onto the background). Between two clicks both directions are
 * followed and blended, so the path meets every click.
 */
function trackPoint(pixels, tw, th, anchors, { radius = 6, search = 12 } = {}) {
  const n = pixels.length;
  const side = 2 * radius + 1;
  const clamp = (v, max) => Math.min(max, Math.max(0, v));
  const patch = (p, cx, cy) => {
    const out = new Int16Array(side * side * 3);
    let k = 0;
    for (let dy = -radius; dy <= radius; dy++) {
      const y = clamp(cy + dy, th - 1);
      for (let dx = -radius; dx <= radius; dx++) {
        const j = (y * tw + clamp(cx + dx, tw - 1)) * 3;
        out[k++] = p[j]; out[k++] = p[j + 1]; out[k++] = p[j + 2];
      }
    }
    return out;
  };
  const cost = (p, cx, cy, a, b, limit) => {
    let sum = 0;
    let k = 0;
    for (let dy = -radius; dy <= radius; dy++) {
      const y = clamp(cy + dy, th - 1);
      for (let dx = -radius; dx <= radius; dx++) {
        const j = (y * tw + clamp(cx + dx, tw - 1)) * 3;
        for (let c = 0; c < 3; c++, k++) {
          const v = p[j + c];
          sum += Math.abs(v - a[k]) + Math.abs(v - b[k]);
        }
      }
      if (sum >= limit) return sum;  // already worse than the best
    }
    return sum;
  };
  // Mean difference per channel and template above which the patch is lost: hold still.
  const lost = 45 * side * side * 3 * 2;
  const follow = (from, x, y, dir, until) => {
    const out = new Map();
    let cx = Math.round(x * (tw - 1));
    let cy = Math.round(y * (th - 1));
    const clicked = patch(pixels[from], cx, cy);
    let last = clicked;
    for (let i = from + dir; dir > 0 ? i <= until : i >= until; i += dir) {
      let best = Infinity;
      let bx = cx;
      let by = cy;
      for (let sy = Math.max(0, cy - search); sy <= Math.min(th - 1, cy + search); sy++) {
        for (let sx = Math.max(0, cx - search); sx <= Math.min(tw - 1, cx + search); sx++) {
          const c = cost(pixels[i], sx, sy, clicked, last, best);
          if (c < best) { best = c; bx = sx; by = sy; }
        }
      }
      if (best < lost) {
        cx = bx; cy = by;
        last = patch(pixels[i], cx, cy);
      }
      out.set(i, { x: cx / (tw - 1), y: cy / (th - 1) });
    }
    return out;
  };
  const keys = [...new Map(anchors.map((a) => [clamp(a.i, n - 1), a])).values()].sort((a, b) => a.i - b.i);
  const path = new Array(n);
  for (const a of keys) path[clamp(a.i, n - 1)] = { x: a.x, y: a.y };
  const first = keys[0];
  const last = keys[keys.length - 1];
  for (const [i, p] of follow(clamp(first.i, n - 1), first.x, first.y, -1, 0)) path[i] = p;
  for (const [i, p] of follow(clamp(last.i, n - 1), last.x, last.y, 1, n - 1)) path[i] = p;
  for (let k = 0; k + 1 < keys.length; k++) {
    const a = keys[k];
    const b = keys[k + 1];
    if (b.i - a.i < 2) continue;
    const forward = follow(a.i, a.x, a.y, 1, b.i - 1);
    const backward = follow(b.i, b.x, b.y, -1, a.i + 1);
    for (let i = a.i + 1; i < b.i; i++) {
      const f = (i - a.i) / (b.i - a.i);
      const p = forward.get(i);
      const q = backward.get(i);
      path[i] = { x: p.x * (1 - f) + q.x * f, y: p.y * (1 - f) + q.y * f };
    }
  }
  // A light smoothing (clicked frames stay exact) removes one-pixel jitter.
  const clicked = new Set(keys.map((a) => clamp(a.i, n - 1)));
  return path.map((p, i) => {
    if (clicked.has(i)) return p;
    const near = path.slice(Math.max(0, i - 1), i + 2);
    return { x: near.reduce((s, q) => s + q.x, 0) / near.length, y: near.reduce((s, q) => s + q.y, 0) / near.length };
  });
}

/** Insert or replace the track point at time t (sorted, 50 ms tolerance). */
function setKey(track, t, x, y) {
  const keys = track.filter((k) => Math.abs(k.t - t) > 0.05);
  keys.push({ t, x, y });
  return keys.sort((a, b) => a.t - b.t);
}

/**
 * Follow the moving subject: what differs from the background (per-pixel
 * median of the clip) forms blobs; keep the blob that is big and closest to
 * where the subject was, then smooth the path. Works when the background is
 * still (sprites walking across a scene); scrolling scenes need keyframes.
 */
function autoTrack(frames, times) {
  const first = frames[0];
  const tw = 96;
  const th = Math.max(8, Math.round((tw * first.height) / first.width));
  const ctx = makeCanvas(tw, th).getContext("2d", { willReadFrequently: true });
  // Colour, not brightness: an orange sprite on a blue sky has the same grey.
  const pixels = frames.map((bmp) => {
    ctx.clearRect(0, 0, tw, th);
    ctx.drawImage(bmp, 0, 0, tw, th);
    const d = ctx.getImageData(0, 0, tw, th).data;
    const rgb = new Uint8Array(tw * th * 3);
    for (let i = 0; i < tw * th; i++) {
      rgb[i * 3] = d[i * 4]; rgb[i * 3 + 1] = d[i * 4 + 1]; rgb[i * 3 + 2] = d[i * 4 + 2];
    }
    return rgb;
  });
  const step = Math.max(1, Math.floor(pixels.length / 31));
  const sample = pixels.filter((_, i) => i % step === 0);
  const background = new Uint8Array(tw * th * 3);
  const column = new Uint8Array(sample.length);
  for (let i = 0; i < background.length; i++) {
    sample.forEach((p, k) => { column[k] = p[i]; });
    background[i] = column.slice().sort()[column.length >> 1];
  }
  let previous = null;
  const points = pixels.map((p) => {
    const mask = new Uint8Array(tw * th);
    for (let i = 0; i < mask.length; i++) {
      const j = i * 3;
      const diff = Math.abs(p[j] - background[j]) + Math.abs(p[j + 1] - background[j + 1])
        + Math.abs(p[j + 2] - background[j + 2]);
      mask[i] = diff > 60 ? 1 : 0;
    }
    const blobs = [];
    const label = new Int32Array(tw * th).fill(-1);
    for (let i = 0; i < mask.length; i++) {
      if (!mask[i] || label[i] >= 0) continue;
      const stack = [i];
      label[i] = blobs.length;
      let n = 0; let sx = 0; let sy = 0;
      while (stack.length) {
        const j = stack.pop();
        const x = j % tw;
        const y = (j / tw) | 0;
        n++; sx += x; sy += y;
        for (const k of [j - 1, j + 1, j - tw, j + tw]) {
          if (k < 0 || k >= mask.length || label[k] >= 0 || !mask[k]) continue;
          if ((k === j - 1 && x === 0) || (k === j + 1 && x === tw - 1)) continue;
          label[k] = blobs.length;
          stack.push(k);
        }
      }
      if (n >= 3) blobs.push({ n, x: sx / n / tw, y: sy / n / th });
    }
    if (!blobs.length) return null;
    // The subject is the biggest moving thing; stay on the blob followed so
    // far only while it is still a major one (small wobbling props lose).
    const largest = blobs.reduce((best, b) => (b.n > best.n ? b : best));
    let pick = largest;
    if (previous) {
      const dist = (b) => Math.hypot(b.x - previous.x, b.y - previous.y);
      const near = blobs.filter((b) => b.n >= largest.n * 0.5).reduce((best, b) => (dist(b) < dist(best) ? b : best), largest);
      if (dist(near) < 0.15) pick = near;
    }
    previous = pick;
    return { x: pick.x, y: pick.y };
  });
  // Frames without motion keep the nearest known position.
  let last = points.find(Boolean) || { x: 0.5, y: 0.5 };
  const filled = points.map((p) => (last = p || last));
  const radius = 2;
  return filled.map((_, i) => {
    const near = filled.slice(Math.max(0, i - radius), i + radius + 1);
    return {
      t: times[i],
      x: near.reduce((s, p) => s + p.x, 0) / near.length,
      y: near.reduce((s, p) => s + p.y, 0) / near.length,
    };
  });
}

/** Crop / fit / stretch one source frame onto the square screen (no tones). */
function scaleFrame(source, o, size, ctx, t = 0) {
  const W = source.videoWidth || source.naturalWidth || source.width;
  const H = source.videoHeight || source.naturalHeight || source.height;
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, size, size);
  let sx = 0; let sy = 0; let sw = W; let sh = H; let dx = 0; let dy = 0; let dw = size; let dh = size;
  if (o.fit === "crop") {
    const [x, y, w, h] = cropAt(o, t) || centeredSquare(W, H);
    [sx, sy, sw, sh] = [x * W, y * H, w * W, h * H];
  } else if (o.fit === "fit") {
    const scale = Math.min(size / W, size / H);
    [dw, dh] = [W * scale, H * scale];
    [dx, dy] = [(size - dw) / 2, (size - dh) / 2];
  }
  drawScaled(ctx, source, [sx, sy, sw, sh], [dx, dy, dw, dh]);
  return ctx.getImageData(0, 0, size, size);
}

/** Tone a scaled frame for the LEDs, leaving the cached original untouched. */
function toneFrame(scaled, o) {
  const img = new ImageData(new Uint8ClampedArray(scaled.data), scaled.width, scaled.height);
  tone(img.data, o);
  if (o.sharpen) sharpen(img, o.sharpen);
  if (o.black_level > 0) blackLevel(img.data, o.black_level);
  return img;
}

/**
 * Upscaling (pixel art) keeps hard edges. Large reductions go down by
 * halves: a single big step skips most source pixels and looks noisy,
 * halving averages them all (the main quality issue with 4K sources).
 */
function drawScaled(ctx, source, [sx, sy, sw, sh], [dx, dy, dw, dh]) {
  let current = source;
  while (sw > dw * 2 && sh > dh * 2) {
    const w = Math.ceil(sw / 2);
    const h = Math.ceil(sh / 2);
    const step = makeCanvas(w, h);
    const g = step.getContext("2d");
    g.imageSmoothingQuality = "high";
    g.drawImage(current, sx, sy, sw, sh, 0, 0, w, h);
    [current, sx, sy, sw, sh] = [step, 0, 0, w, h];
  }
  ctx.imageSmoothingEnabled = sw > dw;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(current, sx, sy, sw, sh, dx, dy, dw, dh);
}

/** Unsharp mask on the tiny result: crisper edges once shrunk to a few LEDs. */
function sharpen(img, amount) {
  const { width: w, height: h, data: d } = img;
  const src = d.slice();
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      for (let c = 0; c < 3; c++) {
        let sum = 0;
        let n = 0;
        for (let yy = Math.max(0, y - 1); yy <= Math.min(h - 1, y + 1); yy++) {
          for (let xx = Math.max(0, x - 1); xx <= Math.min(w - 1, x + 1); xx++) { sum += src[(yy * w + xx) * 4 + c]; n++; }
        }
        const i = (y * w + x) * 4 + c;
        d[i] = src[i] + amount * (src[i] - sum / n);
      }
    }
  }
}

function blackLevel(d, level) {
  for (let i = 0; i < d.length; i += 4) {
    if (Math.max(d[i], d[i + 1], d[i + 2]) < level) d[i] = d[i + 1] = d[i + 2] = 0;
  }
}

function centeredSquare(W, H) {
  const side = Math.min(W, H);
  return [(W - side) / 2 / W, (H - side) / 2 / H, side / W, side / H];
}

/** LED tone adjustments, same formulas as media.py (Pillow ImageEnhance). */
function tone(d, o) {
  const n = d.length;
  if (o.brightness !== 1) for (let i = 0; i < n; i += 4) { d[i] *= o.brightness; d[i + 1] *= o.brightness; d[i + 2] *= o.brightness; }
  if (o.contrast !== 1) {
    let sum = 0;
    for (let i = 0; i < n; i += 4) sum += (d[i] * 299 + d[i + 1] * 587 + d[i + 2] * 114) / 1000;
    const mean = Math.round(sum / (n / 4));
    for (let i = 0; i < n; i += 4) for (let c = 0; c < 3; c++) d[i + c] = mean + (d[i + c] - mean) * o.contrast;
  }
  if (o.saturation !== 1) {
    for (let i = 0; i < n; i += 4) {
      const l = (d[i] * 299 + d[i + 1] * 587 + d[i + 2] * 114) / 1000;
      for (let c = 0; c < 3; c++) d[i + c] = l + (d[i + c] - l) * o.saturation;
    }
  }
  if (o.gamma !== 1) {
    const lut = Array.from({ length: 256 }, (_, v) => 255 * (v / 255) ** o.gamma);
    for (let i = 0; i < n; i += 4) { d[i] = lut[d[i]]; d[i + 1] = lut[d[i + 1]]; d[i + 2] = lut[d[i + 2]]; }
  }
}

function makeCanvas(width, height) {
  if (typeof OffscreenCanvas !== "undefined") return new OffscreenCanvas(width, height);
  return Object.assign(document.createElement("canvas"), { width, height });
}

/** Process a workspace item into screen frames: [{data: ImageData, ms}]. */
async function processItem(item, size, maxFrames, onProgress) {
  const raw = await sourceFrames(item.src, item.opts, size, maxFrames, onProgress);
  const o = item.opts;
  // Cropping and shrinking big sources is the slow part: keep the result
  // while only tones, speed or budget change.
  const times = [];
  let t = item.src.kind === "image" ? 0 : Math.max(0, o.start || 0);
  for (const f of raw) { times.push(t); t += f.ms / 1000; }
  const geometry = JSON.stringify([o.fit, o.crop, size, raw.length, o.start, o.end, o.fps, o.follow && o.track, o.follow && o.zoom]);
  if (item.scaled?.geometry !== geometry || item.scaled.raw[0] !== raw[0]) {
    const ctx = makeCanvas(size, size).getContext("2d", { willReadFrequently: true });
    item.scaled = { geometry, raw, times, frames: raw.map((f, i) => scaleFrame(f.bmp, o, size, ctx, times[i])) };
  }
  const speed = o.speed || 1;
  return raw.map((f, i) => ({ data: toneFrame(item.scaled.frames[i], o), ms: Math.max(20, Math.round(f.ms / speed)), t: times[i] }));
}

/** Draw one frame as round LEDs on a dark board. */
// The dot grid is drawn once per canvas size: an opaque sheet with round
// holes laid over the upscaled pixels. A frame then costs two image draws
// instead of one arc per LED, which keeps playback smooth on phones.
const ledMasks = new Map();
let ledPixels = null;

function ledMask(width, size) {
  const key = `${width}/${size}`;
  let mask = ledMasks.get(key);
  if (mask) return mask;
  mask = makeCanvas(width, width);
  const ctx = mask.getContext("2d");
  const cell = width / size;
  ctx.fillStyle = "#050505";
  ctx.fillRect(0, 0, width, width);
  ctx.globalCompositeOperation = "destination-out";
  ctx.beginPath();
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      ctx.moveTo((x + 0.5) * cell + cell * 0.42, (y + 0.5) * cell);
      ctx.arc((x + 0.5) * cell, (y + 0.5) * cell, cell * 0.42, 0, 2 * Math.PI);
    }
  }
  ctx.fill();
  ledMasks.set(key, mask);
  return mask;
}

function deviceLabel() {
  const ua = navigator.userAgent;
  if (/iPad|Tablet/i.test(ua)) return "tablette";
  if (/Android|iPhone|Mobile/i.test(ua)) return "téléphone";
  return "PC";
}

const DEVICE_NAME_KEY = "idotmatrix-studio-device";

/** This browser's name in the Studio (set in ⚙ Config), else its kind. Kept with
 * every original it imports and every GIF it sends. */
function deviceName() {
  try {
    return localStorage.getItem(DEVICE_NAME_KEY) || deviceLabel();
  } catch (_err) {
    return deviceLabel();
  }
}

const MEDIA_RE = /\.(gif|png|jpe?g|webp|bmp|apng|mp4|m4v|mov|webm|mkv|avi|wmv|flv|mpe?g|vob|ts|mts|m2ts|divx|3gp|asf)$/i;

/** A file name compared loosely: no extension, case, accents or separators (gallery slugs use "_"). */
const looseName = (name) => name.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "")
  .replace(/\.[a-z0-9]{2,5}$/, "").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");

/** The source file of `target` ({name, size?}) among `files` ([{name, size?}]): the same name
 * (same size first), else the same name with another extension, else the longest name `target`
 * starts with: « 2025-05-01-190800_original_boomerang.gif » comes from « 2025-05-01-190800.mp4 ». */
function matchSource(target, files, exact = false) {
  const media = files.filter((f) => MEDIA_RE.test(f.name));
  const lower = target.name.toLowerCase();
  const same = media.filter((f) => f.name.toLowerCase() === lower);
  if (same.length) return same.find((f) => target.size && f.size === target.size) || same[0];
  if (exact) return null;
  const stem = looseName(target.name);
  let best = null;
  for (const f of media) {
    const s = looseName(f.name);
    if (s && (s === stem || stem.startsWith(`${s}_`)) && (!best || s.length > looseName(best.name).length)) best = f;
  }
  return best;
}

/** Search folders of this browser: File System Access handles kept in their own database. */
function searchFolderStore(mode, run) {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("idotmatrix-studio-folders", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("folders", { keyPath: "id" });
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const tx = request.result.transaction("folders", mode);
      const op = run(tx.objectStore("folders"));
      tx.oncomplete = () => resolve(op.result);
      tx.onerror = () => reject(tx.error);
    };
  });
}

// Deleted originals and clips wait in the trash (their files too) this long.
const TRASH_DAYS = 30;
const TRASH = "__corbeille__";  // the trash's key among the folder filters

// Thrown out of a video extraction that a newer one replaced.
const STALE = new Error("superseded");

const MISSING = "L'original n'est pas sur cet appareil : « Relier » puis choisis le même fichier.";

function hhmm(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function drawLed(canvas, img) {
  const size = img.width;
  if (!ledPixels || ledPixels.width !== size) ledPixels = makeCanvas(size, size);
  const lit = new ImageData(size, size);
  const s = img.data;
  const d = lit.data;
  for (let i = 0; i < d.length; i += 4) {
    const on = Math.max(s[i], s[i + 1], s[i + 2]) >= UNLIT;
    d[i] = on ? s[i] : UNLIT; d[i + 1] = on ? s[i + 1] : UNLIT; d[i + 2] = on ? s[i + 2] : UNLIT; d[i + 3] = 255;
  }
  ledPixels.getContext("2d").putImageData(lit, 0, 0);
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(ledPixels, 0, 0, canvas.width, canvas.height);
  ctx.drawImage(ledMask(canvas.width, size), 0, 0, canvas.width, canvas.height);
}

/** Lay frames out as a square-ish grid PNG (canvases are capped at 32767 px). */
async function frameSheet(frames) {
  const size = frames[0].data.width;
  const columns = Math.ceil(Math.sqrt(frames.length));
  const canvas = document.createElement("canvas");
  canvas.width = size * columns;
  canvas.height = size * Math.ceil(frames.length / columns);
  const ctx = canvas.getContext("2d");
  frames.forEach((f, i) => ctx.putImageData(f.data, (i % columns) * size, Math.floor(i / columns) * size));
  return { blob: await new Promise((resolve) => canvas.toBlob(resolve, "image/png")), size, columns };
}

function stillPng(img) {
  const canvas = document.createElement("canvas");
  canvas.width = img.width;
  canvas.height = img.height;
  canvas.getContext("2d").putImageData(img, 0, 0);
  return canvas.toDataURL("image/png");
}

/** A PNG (data URL) as ImageData, for the LED preview. */
async function pngPixels(url) {
  const img = new Image();
  await new Promise((resolve, reject) => { img.onload = resolve; img.onerror = reject; img.src = url; });
  const ctx = makeCanvas(img.width, img.height).getContext("2d");
  ctx.drawImage(img, 0, 0);
  return ctx.getImageData(0, 0, img.width, img.height);
}

/**
 * Workspace kept in this browser (IndexedDB): the original files, and the
 * clips made from them (time window, crop, speed, tones...). Clips always
 * render from their original, so re-editing never loses quality; only the
 * finished GIFs reach the Pi.
 */
const studioStore = {
  db: null,
  open() {
    if (this.db) return Promise.resolve(this.db);
    return new Promise((resolve, reject) => {
      const request = indexedDB.open("idotmatrix-studio", 2);
      request.onupgradeneeded = (ev) => {
        const db = request.result;
        const originals = db.createObjectStore("originals", { keyPath: "id" });
        const clips = db.createObjectStore("clips", { keyPath: "id" });
        if (ev.oldVersion !== 1) return;
        // Version 1 kept one item per file: split each into an original and its clip.
        const legacy = request.transaction.objectStore("workspace");
        legacy.getAll().onsuccess = (e) => {
          for (const r of e.target.result) {
            originals.put({ id: `o${r.id}`, file: r.file, name: r.file?.name || r.title, created: r.created });
            clips.put({
              id: r.id, originalId: `o${r.id}`, title: r.title, opts: r.opts, created: r.created,
              pushed: r.status === "saved" ? r.replace : null, sizeBytes: r.size_bytes,
            });
          }
          db.deleteObjectStore("workspace");
        };
      };
      request.onsuccess = () => resolve((this.db = request.result));
      request.onerror = () => reject(request.error);
    });
  },
  async run(store, mode, action) {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(store, mode);
      const request = action(tx.objectStore(store));
      tx.oncomplete = () => resolve(request?.result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  },
  all(store) { return this.run(store, "readonly", (s) => s.getAll()); },
  put(store, record) { return this.run(store, "readwrite", (s) => s.put(record)); },
  remove(store, id) { return this.run(store, "readwrite", (s) => s.delete(id)); },
  async clear() {
    await this.run("originals", "readwrite", (s) => s.clear());
    await this.run("clips", "readwrite", (s) => s.clear());
  },
};

const TAB_KEY = "idotmatrix-studio-tab";
const newId = (prefix = "c") => `${prefix}${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];

// ------------------------------------------------------------------ panel

class IDotMatrixStudio extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.state = { tab: "gallery", items: [], favoritesOnly: false, transfer: null, status: null };
    this.originals = [];
    this.trash = { originals: [], clips: [] };  // deleted, restorable for TRASH_DAYS
    this.clips = [];
    this.folders = [];  // folders created by hand, even while empty
    this.current = null;
    this._renderSeq = 0;
    this._queue = [];  // clips waiting to be encoded on the Pi, first one in progress
    this._imports = [];  // files added but not read yet, read one at a time
    this._clientId = newId("p");  // this page, so it skips its own workspace events
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._init();
    else this._updatePreview();
  }

  // HA hides its sidebar on phones: the panel then shows its own menu button.
  set narrow(value) { this.toggleAttribute("narrow", !!value); }
  set panel(_value) {}

  async _init() {
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <div class="top">
        <header><button class="menu" title="Menu">☰</button><h1>Pixel Studio</h1>
          <nav class="tabs"><button data-tab="gallery">Galerie</button><button data-tab="store">Store</button><button data-tab="workspace">Atelier</button><button data-tab="routines">Routines</button><button data-tab="weather" title="L'heure et la météo de la journée sur le cadre">Météo</button><button data-tab="queue" title="Ce qui se passe sur le Pi et dans ce navigateur">⏳</button><button data-tab="log" title="Journal : tout ce qui s'est passé, à copier pour analyse">📜</button><button data-tab="config" title="Réglages de ce navigateur">⚙</button></nav>
        </header>
        <section class="status" title="État du cadre">
          <img class="sprev none" alt="">
          <div class="sline" id="sline1"><span><span class="dot"></span>Connexion…</span></div>
          <div class="sacts"></div>
          <div class="sline2" id="sline2"></div>
          <div class="upnext" id="supnext"></div>
          <div class="work"></div>
          <div class="jobs"></div>
          <div class="transfer"></div>
        </section>
      </div><main></main>`;
    this.shadowRoot.querySelector("nav").addEventListener("click", (ev) => {
      const tab = ev.target.closest("button[data-tab]");
      if (tab) this._show(tab.dataset.tab);
    });
    this.shadowRoot.querySelector(".menu").onclick = () => {
      this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
    };
    this.shadowRoot.querySelector(".sacts").onclick = (ev) => this._statusAction(ev);
    // ⋯ menus: one open at a time, placed under their button, closed by a click elsewhere or a scroll.
    const closeMenus = (except = null) => {
      for (const menu of this.shadowRoot.querySelectorAll("details.menu[open]")) if (menu !== except) menu.open = false;
    };
    this.shadowRoot.addEventListener("toggle", (ev) => {
      const menu = ev.target;
      if (!menu.matches?.("details.menu") || !menu.open) return;
      closeMenus(menu);
      const rect = menu.querySelector("summary").getBoundingClientRect();
      const list = menu.querySelector(".menu-list");
      list.style.top = `${rect.bottom + 4}px`;
      list.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - 230))}px`;
    }, true);
    this.shadowRoot.addEventListener("click", (ev) => {
      if (!ev.target.closest?.("details.menu")) closeMenus();
    });
    window.addEventListener("scroll", () => closeMenus(), { passive: true });
    // The filter bars stick right under the header and status bar, whose height varies.
    const top = this.shadowRoot.querySelector(".top");
    if (window.ResizeObserver) {
      this._topObserver = new window.ResizeObserver(() => this.style.setProperty("--top-h", `${top.offsetHeight}px`));
      this._topObserver.observe(top);
    }
    this.shadowRoot.querySelector("#supnext").onclick = (ev) => this._upNextClick(ev);
    this.shadowRoot.querySelector("#sline1").onchange = (ev) => {
      if (ev.target.matches(".dsel")) this._pickDisplay(ev.target.value);
    };
    try {
      this.info = await this._ws({ type: "idotmatrix/studio/info" });
      // The Store is an optional part of the integration: no module, no tab.
      if (!this.info.store) this.shadowRoot.querySelector('nav [data-tab="store"]')?.remove();
      this._unsub = await this._hass.connection.subscribeEvents(
        (ev) => this._onTransfer(ev.data), this.info.transfer_event);
      this._unsubRoutine = await this._hass.connection.subscribeEvents(
        (ev) => this._onRoutineStatus(ev.data), this.info.routine_event);
      this._unsubSchedule = await this._hass.connection.subscribeEvents(
        () => this._refreshStatus(), this.info.schedule_event);
      if (this.info.log_event) {
        this._unsubLog = await this._hass.connection.subscribeEvents((ev) => this._onLog(ev.data), this.info.log_event);
      }
      if (this.info.workspace_event) {
        this._unsubWorkspace = await this._hass.connection.subscribeEvents((ev) => {
          if (ev.data?.client === this._clientId) return;
          clearTimeout(this._workspaceTimer);
          this._workspaceTimer = setTimeout(() => this._refreshWorkspace(), 800);
        }, this.info.workspace_event);
      }
    } catch (err) {
      this._main().innerHTML = `<p class="error">${esc(err.message || err)}</p>`;
      return;
    }
    try {
      const byDate = (a, b) => a.created - b.created;
      this.originals = (await studioStore.all("originals")).sort(byDate).map((o) => ({ ...o, src: null }));
      this.clips = (await studioStore.all("clips")).sort(byDate).map((c) => ({
        ...c, status: "ready", src: null, frames: null, result: null, opts: { ...DEFAULTS, ...c.opts },
      }));
    } catch (_err) {
      this._noHistory = true;  // private browsing or storage disabled
    }
    await this._mergeRemoteWorkspace();
    this._splitTrash();
    let tab = null;
    try { tab = sessionStorage.getItem(TAB_KEY); } catch (_err) { /* storage off */ }
    this._show(["gallery", "store", "workspace", "routines", "weather", "queue", "config"].includes(tab) ? tab : "gallery");
    this._refreshStatus();
    this._statusTimer = setInterval(() => this._refreshStatus(), 30000);
  }

  _original(id) { return this.originals.find((o) => o.id === id); }
  _clipsOf(original) { return this.clips.filter((c) => c.originalId === original.id); }

  /** Decode a clip's original on first use (the history loads lazily). */
  async _source(clip) {
    const original = this._original(clip.originalId);
    if (!original?.file) throw new Error(MISSING);
    clip.src = await this._ensureSource(original);
    return clip.src;
  }

  /** Decode an original. A video this browser cannot play is first made into a
   * light copy, kept with the original so it is converted once, when first used. */
  async _ensureSource(original) {
    if (original.src) return original.src;
    if (!original.file) throw new Error(MISSING);
    const started = performance.now();
    try {
      original.src = await loadSource(original.file);
      this._logSource(original, started);
      return original.src;
    } catch (err) {
      if (!isVideo(original.file)) throw err;
    }
    Object.assign(original, { status: "busy", progress: "conversion…" });
    this._updateOriginalRow(original);
    const unreadable = { name: original.file.name, type: original.file.type, bytes: original.file.size };
    try {
      original.file = await browserWorkingCopy(original.file, (status) => {
        original.progress = status;
        this._updateOriginalRow(original);
      });
      original.src = await loadSource(original.file);
      original.needsCopy = false;
      this._logSource(original, started, unreadable);
    } finally {
      original.status = "ready";
      this._updateOriginalRow(original);
    }
    await this._persistOriginal(original);
    return original.src;
  }

  _clipRecord(clip) {
    return {
      id: clip.id, originalId: clip.originalId, title: clip.title, opts: clip.opts, created: clip.created,
      pushed: clip.pushed || null, dirty: !!clip.dirty, sizeBytes: clip.sizeBytes ?? null,
      updated: clip.updated || clip.created, trashed: clip.trashed || null,
    };
  }

  _originalRecord(o) {
    return {
      id: o.id, name: o.name, size: o.size ?? null, device: o.device || null, folder: o.folder || "",
      created: o.created, updated: o.updated || o.created, trashed: o.trashed || null,
    };
  }

  /** Save an original's description (its folder) without rewriting its file. */
  _saveOriginalMeta(o) {
    const record = this._originalRecord(o);
    this._sync("put_originals", record);
    if (this._noHistory) return;
    studioStore.run("originals", "readwrite", (s) => {
      const request = s.get(o.id);
      request.onsuccess = () => { if (request.result) s.put({ ...request.result, ...record }); };
    }).catch(() => {});
  }

  _persistClip(clip) {
    clip.updated = Date.now();
    clearTimeout(clip.persistTimer);
    clip.persistTimer = setTimeout(() => {
      const record = this._clipRecord(clip);
      this._sync("put_clips", record);
      if (!this._noHistory) studioStore.put("clips", record).catch(() => {});
    }, 400);
  }

  async _persistOriginal(original) {
    this._sync("put_originals", this._originalRecord(original));
    if (this._noHistory) return;
    try {
      await studioStore.put("originals", { ...this._originalRecord(original), file: original.file });
    } catch (_err) {
      original.notKept = true;  // storage full: kept for this visit only
    }
  }

  // The workspace's description (not its media) is shared through Home
  // Assistant, so a video imported on the phone shows up on the PC too.

  _sync(kind, value) {
    const p = (this._pendingSync ||= {
      put_originals: new Map(), put_clips: new Map(), delete_originals: new Set(), delete_clips: new Set(), clear: false,
      folders: null,
    });
    if (kind === "folders") {
      p.folders = [...value];
    } else if (kind === "clear") {
      p.clear = true;
      p.put_originals.clear();
      p.put_clips.clear();
    } else if (kind.startsWith("put_")) {
      p[kind].set(value.id, value);
    } else {
      p[kind].add(value);
    }
    clearTimeout(this._syncTimer);
    this._syncTimer = setTimeout(() => this._flushSync(), 600);
  }

  async _flushSync() {
    const p = this._pendingSync;
    this._pendingSync = null;
    if (!p) return;
    try {
      await this._ws({
        type: "idotmatrix/studio/workspace_sync", clear: p.clear, client: this._clientId,
        put_originals: [...p.put_originals.values()], put_clips: [...p.put_clips.values()],
        delete_originals: [...p.delete_originals], delete_clips: [...p.delete_clips],
        ...(p.folders ? { folders: p.folders } : {}),
      });
    } catch (_err) {
      // Offline: the next visit compares both sides and sends what is missing.
    }
  }

  /** Bring in what other browsers added, edited or deleted; send what only this one has. */
  async _mergeRemoteWorkspace() {
    let remote;
    try {
      remote = await this._ws({ type: "idotmatrix/studio/workspace" });
    } catch (_err) {
      return;
    }
    const deleted = new Set(remote.deleted || []);
    const forget = (store, id) => { if (!this._noHistory) studioStore.remove(store, id).catch(() => {}); };
    this.originals = this.originals.filter((o) => !deleted.has(o.id) || forget("originals", o.id));
    this.clips = this.clips.filter((c) => !deleted.has(c.id) && !deleted.has(c.originalId) || forget("clips", c.id));
    const remoteOriginals = new Map(remote.originals.map((r) => [r.id, r]));
    const remoteClips = new Map(remote.clips.map((r) => [r.id, r]));
    for (const o of this.originals) {
      const r = remoteOriginals.get(o.id);
      o.size ??= r?.size ?? o.file?.size ?? null;
      o.device ??= r?.device ?? deviceName();
      if (r && (r.updated || 0) > (o.updated || o.created || 0)) {
        // Filed in another folder from another device.
        Object.assign(o, { folder: r.folder || "", trashed: r.trashed || null, updated: r.updated });
        this._saveOriginalMeta(o);
      } else if (!r || (o.updated || o.created || 0) > (r.updated || 0)) {
        this._sync("put_originals", this._originalRecord(o));
      }
    }
    this.folders = remote.folders || [];
    for (const r of remote.originals) {
      if (!this._original(r.id)) this.originals.push({ ...r, file: null, src: null, missing: true, status: "ready" });
    }
    for (const c of this.clips) {
      const r = remoteClips.get(c.id);
      if (!r || (c.updated || 0) > (r.updated || 0)) this._sync("put_clips", this._clipRecord(c));
    }
    for (const r of remote.clips) {
      const local = this.clips.find((c) => c.id === r.id);
      const opts = { ...DEFAULTS, ...r.opts };
      if (!local) {
        this.clips.push({ ...r, opts, status: "ready", src: null, frames: null, result: null });
      } else if ((r.updated || 0) > (local.updated || 0)) {
        Object.assign(local, {
          title: r.title, opts, pushed: r.pushed, dirty: r.dirty, sizeBytes: r.sizeBytes, updated: r.updated, trashed: r.trashed || null,
        });
        if (!this._noHistory) studioStore.put("clips", this._clipRecord(local)).catch(() => {});
      }
    }
    const byDate = (a, b) => a.created - b.created;
    this.originals.sort(byDate);
    this.clips.sort(byDate);
  }

  // ------------------------------------------------------------------ trash
  // Deleting moves to the trash, shared by every device; nothing is lost
  // until TRASH_DAYS later.

  /** Another device changed the workspace: merge its changes in (trash included) and redraw. */
  async _refreshWorkspace() {
    this.originals.push(...this.trash.originals);
    this.clips.push(...this.trash.clips);
    await this._mergeRemoteWorkspace();
    this._splitTrash();
    if (this.state.tab === "workspace") this._renderTree();
  }

  /** Take trashed items out of the lists; delete for good the expired ones. */
  _splitTrash() {
    const expired = Date.now() - TRASH_DAYS * 86400000;
    const trash = { originals: [], clips: [] };
    for (const kind of ["originals", "clips"]) {
      this[kind] = this[kind].filter((x) => {
        if (!x.trashed) return true;
        if (x.trashed < expired) this._purge(kind, x);
        else trash[kind].push(x);
        return false;
      });
    }
    this.trash = trash;
  }

  _purge(kind, x) {
    this._sync(`delete_${kind}`, x.id);
    if (!this._noHistory) studioStore.remove(kind, x.id).catch(() => {});
  }

  _trashOriginal(original) {
    const now = Date.now();
    for (const c of this._clipsOf(original)) {
      c.trashed = now;
      this._persistClip(c);
      this.trash.clips.push(c);
    }
    Object.assign(original, { trashed: now, updated: now });
    this._saveOriginalMeta(original);
    this.trash.originals.push(original);
    this.clips = this.clips.filter((c) => c.originalId !== original.id);
    this.originals = this.originals.filter((o) => o !== original);
    this._wselected?.delete(original.id);
  }

  _trashClip(clip) {
    clip.trashed = Date.now();
    this._persistClip(clip);
    this.trash.clips.push(clip);
    this.clips = this.clips.filter((c) => c !== clip);
  }

  /** Put an original (with its clips) or a clip (with its original) back. */
  _restore(kind, item) {
    const original = kind === "originals" ? item : this.trash.originals.find((o) => o.id === item.originalId);
    const clips = kind === "originals" ? this.trash.clips.filter((c) => c.originalId === item.id) : [item];
    if (original) {
      Object.assign(original, { trashed: null, updated: Date.now() });
      this._saveOriginalMeta(original);
      this.trash.originals = this.trash.originals.filter((o) => o !== original);
      this.originals.push(original);
    }
    for (const c of clips) {
      c.trashed = null;
      this._persistClip(c);
      this.clips.push(c);
    }
    this.trash.clips = this.trash.clips.filter((c) => !clips.includes(c));
  }

  _trashTotal() { return this.trash.originals.length + this.trash.clips.length; }

  /** The trash as rows: originals (with their clips), then lone clips. */
  _trashHtml() {
    const day = (ts) => new Date(ts).toLocaleDateString();
    const row = (kind, x, label, sub) => `<div class="orig" data-kind="${kind}" data-id="${esc(x.id)}"><div class="orow">
        <div class="grow ellipsis"><span class="title">${esc(label)}</span>
          <span class="muted small">${sub} · supprimé le ${day(x.trashed)}, effacé pour de bon le ${day(x.trashed + TRASH_DAYS * 86400000)}</span></div>
        <button class="act small" data-tact="restore">↩ Restaurer</button>
        <button class="icon" data-tact="purge" title="Supprimer définitivement (toucher deux fois)">✕</button></div></div>`;
    const rows = [
      ...this.trash.originals.map((o) => [o.trashed, row("originals", o, o.name,
        `${this.trash.clips.filter((c) => c.originalId === o.id).length} clip(s)`)]),
      ...this.trash.clips.filter((c) => !this.trash.originals.some((o) => o.id === c.originalId))
        .map((c) => [c.trashed, row("clips", c, c.title, `clip de ${esc(this._original(c.originalId)?.name || "?")}`)]),
    ].sort((a, b) => b[0] - a[0]).map(([, html]) => html);
    return rows.length
      ? `<div class="toolbar"><span class="grow muted small">Restaure ce qui a été supprimé par erreur, sur tous tes appareils.</span>
          <button class="act ghost small" data-tact="restoreAll">↩ Tout restaurer</button>
          <button class="act small danger" data-tact="purgeAll" title="Efface définitivement tout ce qui est dans la corbeille, sur tous tes appareils (toucher deux fois) ; les GIF de la galerie restent">🗑 Vider la corbeille</button></div>${rows.join("")}`
      : `<div class="card empty muted">La corbeille est vide.</div>`;
  }

  _trashAction(button) {
    if (button.dataset.tact === "restoreAll") {
      for (const o of [...this.trash.originals]) this._restore("originals", o);
      for (const c of [...this.trash.clips]) this._restore("clips", c);
    } else if (button.dataset.tact === "purgeAll") {
      if (!this._armed(button, `Tout effacer (${this._trashTotal()}) ?`)) return;
      for (const c of this.trash.clips) this._purge("clips", c);
      for (const o of this.trash.originals) this._purge("originals", o);
      this.trash.clips = [];
      this.trash.originals = [];
    } else {
      const row = button.closest("[data-kind]");
      const kind = row.dataset.kind;
      const item = this.trash[kind].find((x) => x.id === row.dataset.id);
      if (!item) return;
      if (button.dataset.tact === "restore") {
        this._restore(kind, item);
      } else {
        if (!this._armed(button, "Effacer ?")) return;
        const clips = kind === "originals" ? this.trash.clips.filter((c) => c.originalId === item.id) : [];
        for (const c of clips) this._purge("clips", c);
        this._purge(kind, item);
        this.trash.clips = this.trash.clips.filter((c) => c !== item && !clips.includes(c));
        this.trash.originals = this.trash.originals.filter((o) => o !== item);
      }
    }
    if (!this._trashTotal()) this.state.filter.folder = null;
    this._renderWorkspace();
  }

  disconnectedCallback() {
    clearInterval(this._carouselTimer);
    this._topObserver?.disconnect();
    if (this._unsubLog) this._unsubLog();
    this._unsubLog = null;
    if (this._unsub) this._unsub();
    if (this._unsubRoutine) this._unsubRoutine();
    if (this._unsubSchedule) this._unsubSchedule();
    if (this._unsubWorkspace) this._unsubWorkspace();
    this._unsubWorkspace = null;
    this._unsub = this._unsubRoutine = this._unsubSchedule = null;
    clearInterval(this._statusTimer);
    clearTimeout(this._weatherTimer);
    this._stopPlayer();
  }

  _ws(msg) {
    if (this._entryId && PER_DISPLAY.has(msg.type) && msg.entry_id === undefined) msg = { ...msg, entry_id: this._entryId };
    return this._hass.callWS(msg);
  }

  /** Events of another display than the one picked (they all share the bus). */
  _otherDisplay(data) { return Boolean(data?.entry_id && this._entryId && data.entry_id !== this._entryId); }
  _main() { return this.shadowRoot.querySelector("main"); }
  get size() { return this.info.screen_size; }

  async _sign(path) {
    return (await this._ws({ type: "auth/sign_path", path, expires: 3600 })).path;
  }

  _show(tab) {
    clearInterval(this._queueTimer);
    clearTimeout(this._weatherTimer);
    this._stopPlayer();
    clearTimeout(this._encodeTimer);
    clearTimeout(this._liveTimer);
    this.state.tab = tab;
    if (tab !== "editor" && this._editing) {
      const edited = this._original(this._editing);
      this._editing = null;
      this._release(edited);
    }
    // A phone may reload the page (file picker, memory): come back to the same tab.
    try { sessionStorage.setItem(TAB_KEY, tab === "editor" ? "workspace" : tab); } catch (_err) { /* storage off */ }
    this.shadowRoot.querySelectorAll("nav button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
    if (tab === "gallery") this._renderGallery();
    else if (tab === "workspace") this._renderWorkspace();
    else if (tab === "routines") this._renderRoutines();
    else if (tab === "weather") this._renderWeather();
    else if (tab === "store") this._renderStore();
    else if (tab === "config") this._renderConfig();
    else if (tab === "queue") this._renderQueue();
    else if (tab === "log") this._renderLog();
    else this._renderEditor();
  }

  async _galleryItems() {
    const { items, collections = [], hidden_folders: hidden = [] } = await this._ws({ type: "idotmatrix/studio/gallery" });
    this.state.items = items;
    this.state.collections = collections;
    this.state.hiddenFolders = hidden;
    return items;
  }

  /** A folder hidden in the panel (its GIFs and originals leave « Tous » until 👁 shows them). */
  _hidden(folder) { return Boolean(folder) && (this.state.hiddenFolders || []).includes(folder); }

  /** Whether an entry of `folder` shows while `active` is the chosen folder. */
  _inSight(folder, active) { return this._showHidden || !this._hidden(folder) || (active !== null && active !== undefined && folder === active); }

  // ---------------------------------------------------------------- gallery

  async _renderGallery() {
    const main = this._main();
    const g = (this.state.galleryFilter ||= { q: "", folder: null, kind: "all", device: "*" });
    g.device ??= "*";
    this._selected ||= new Set();
    main.innerHTML = `<div class="filterbar"><div class="toolbar">
        <input type="search" id="gq" placeholder="Rechercher…" value="${esc(g.q)}">
        <select id="gkind" title="Type">
          <option value="all">Tout</option><option value="anim">Animations</option><option value="still">Images fixes</option></select>
        <select id="gdev" title="Envoyé depuis"></select>
        <button class="act ${this.state.favoritesOnly ? "" : "ghost"} small" id="fav"
          title="${this.state.favoritesOnly ? "Afficher toute la galerie" : "N'afficher que les favoris"}">${this.state.favoritesOnly ? "★" : "☆"} Favoris</button>
        <button class="act small" id="new">+ Ajouter</button>
      </div>
      <div class="chips" id="gfolders"></div>
      <div class="chips" id="gcols"></div>
      <div class="selbar" id="gselbar" hidden></div></div>
      <div class="grid"></div>`;
    main.querySelector("#gkind").value = g.kind;
    main.querySelector("#new").onclick = () => this._show("workspace");
    main.querySelector("#fav").onclick = () => { this.state.favoritesOnly = !this.state.favoritesOnly; this._renderGallery(); };
    main.querySelector("#gq").oninput = (ev) => { g.q = ev.target.value; this._drawGallery(); };
    main.querySelector("#gkind").onchange = (ev) => { g.kind = ev.target.value; this._drawGallery(); };
    main.querySelector("#gdev").onchange = (ev) => { g.device = ev.target.value; this._drawGallery(); };
    main.querySelector("#gfolders").onclick = (ev) => this._folderChipClick(ev, g.folder, (folder) => {
      g.folder = folder;
      if (folder !== null) g.collection = null;
      this._drawGallery();
    });
    main.querySelector("#gcols").onclick = (ev) => this._collectionChipClick(ev);
    main.querySelector(".grid").onclick = (ev) => this._galleryAction(ev);
    main.querySelector("#gselbar").onclick = (ev) => this._selectionAction(ev);
    await this._galleryItems();
    this._drawGallery();
  }

  _galleryShown() {
    const g = this.state.galleryFilter;
    const q = g.q.trim().toLowerCase();
    const collection = g.collection ? (this.state.collections || []).find((c) => c.id === g.collection) : null;
    if (g.collection && !collection) g.collection = null;
    // A collection shows its GIFs in its own order.
    const pool = collection ? collection.files.map((f) => this.state.items.find((i) => i.file === f)).filter(Boolean) : this.state.items;
    return pool.filter((i) => (!this.state.favoritesOnly || i.favorite)
      && (collection || g.folder === null || (i.folder || "") === g.folder)
      && this._inSight(i.folder, collection ? null : g.folder)
      && (g.kind === "all" || (g.kind === "anim") === (i.frames > 1))
      && (g.device === "*" || (i.device || "") === g.device)
      && (!q || `${i.title} ${i.source || ""}`.toLowerCase().includes(q)));
  }

  _drawGallery() {
    const main = this._main();
    const grid = main.querySelector(".grid");
    if (!grid) return;
    const items = this.state.items;
    const g = this.state.galleryFilter;
    main.querySelector("#gfolders").innerHTML = this._folderChips(g.collection ? undefined : g.folder, (i) => i.folder, items);
    main.querySelector("#gcols").innerHTML = this._collectionChips(g.collection);
    main.querySelector("#gdev").innerHTML = this._deviceOptions(items.map((i) => i.device), g.device);
    const shown = this._galleryShown();
    if (!shown.length) {
      grid.innerHTML = `<div class="card empty muted" style="grid-column: 1 / -1">${items.length
        ? "Rien ne correspond à ces filtres." : "La galerie est vide : ajoute des images, GIF ou vidéos depuis l'Atelier."}</div>`;
      this._drawSelectionBar();
      return;
    }
    grid.innerHTML = shown.map((item) => {
      const format = item.source && /\.([a-z0-9]{2,5})$/i.exec(item.source)?.[1].toUpperCase();
      const selected = this._selected.has(item.file);
      return `<div class="item ${selected ? "selected" : ""}" data-file="${esc(item.file)}">
        <button class="check" data-act="check" title="Sélectionner">${selected ? "☑" : "☐"}</button>
        <img alt="" loading="lazy">
        <div class="meta"><div class="title" title="${esc(item.title)}">${esc(item.title)}</div>
          <div class="badges"><span class="pill">${item.frames > 1 ? "🎞 Animé" : "🖼 Image fixe"}</span>
            ${format ? `<span class="pill" title="Format de l'original">${esc(format)}</span>` : ""}
            ${item.folder ? `<span class="pill">📁 ${esc(item.folder)}</span>` : ""}</div>
          <div class="muted small">${kb(item.size_bytes)} · ${item.frames} img · envoi ${duration(item.estimate_s)}</div>
          ${item.source ? `<div class="muted small ellipsis" title="Original">⤷ ${esc(item.source)}</div>` : ""}
          ${item.device || item.user ? `<div class="muted small ellipsis" title="Envoyé depuis">📤 ${esc([item.device, item.user].filter(Boolean).join(" · "))}</div>` : ""}</div>
        <div class="tools">
          <button class="icon" data-act="display" title="Afficher sur le cadre">▶</button>
          <button class="icon ${item.favorite ? "fav" : ""}" data-act="favorite" title="Favori">${item.favorite ? "★" : "☆"}</button>
          <details class="menu"><summary class="icon" title="Retoucher, relier, ranger, supprimer">⋯</summary><div class="menu-list">
            <button class="act ghost small" data-act="edit" title="Retoucher depuis l'original">✎ Retoucher</button>
            ${this._linkedClip(item) ? "" : `<button class="act ghost small" data-act="link" title="Retrouver l'original dans les dossiers de recherche (⚙)">🔗 Relier l'original</button>`}
            <button class="act ghost small" data-act="folder" title="Ranger dans un dossier">📁 Ranger</button>
            <button class="act ghost small" data-act="delete" title="Supprimer (toucher deux fois)">🗑 Supprimer</button>
          </div></details>
        </div>
      </div>`;
    }).join("");
    for (const el of grid.querySelectorAll(".item")) {
      const item = items.find((i) => i.file === el.dataset.file);
      this._sign(`${item.url}?v=${Math.round(item.modified)}`).then((url) => { el.querySelector("img").src = url; });
    }
    this._drawSelectionBar();
  }

  _drawSelectionBar() {
    const bar = this._main().querySelector("#gselbar");
    if (!bar) return;
    bar.hidden = !this._selected.size;
    if (!this._selected.size) return;
    const n = this._selected.size;
    bar.innerHTML = `<b>${n} sélectionné${n > 1 ? "s" : ""}</b>
      <button class="act ghost small" data-sel="all">Tout</button><button class="act ghost small" data-sel="none">Aucun</button>
      <span class="grow"></span>
      ${this._folderField("gmove")}
      <button class="act ghost small" data-sel="move" ${n ? "" : "disabled"} title="Ranger dans ce dossier (vide = sans dossier)">📁 Ranger</button>
      <input type="text" id="gcol" list="gcol-list" placeholder="Collection…" size="10" maxlength="60">
      <datalist id="gcol-list">${(this.state.collections || []).map((c) => `<option value="${esc(c.name)}">`).join("")}</datalist>
      <button class="act ghost small" data-sel="collect" title="Ajouter à cette collection (un nouveau nom la crée) ; un GIF peut être dans plusieurs collections">🗂 Ajouter</button>
      ${this.state.galleryFilter?.collection ? `<button class="act ghost small" data-sel="uncollect" title="Retirer de la collection affichée (le GIF reste dans la galerie)">➖ Retirer de la collection</button>` : ""}
      <button class="act ghost small" data-sel="fav" ${n ? "" : "disabled"}>★ Favoris</button>
      <button class="act ghost small" data-sel="lighten" ${n ? "" : "disabled"} title="Optimiser : fusionne les images quasi identiques, n'envoie que ce qui change, garde la durée. Un GIF n'est remplacé que s'il gagne au moins un paquet Bluetooth (sinon il n'y a rien à gagner sans perte visible : seuls moins de couleurs, moins d'images ou un clip plus court l'allégeraient) ; l'ancien est gardé dans .backup">✨ Optimiser</button>
      <button class="act small danger" data-sel="delete" ${n ? "" : "disabled"}>🗑 Supprimer</button>`;
  }

  // --------------------------------------------------------------- folders
  // Folders are labels shared by the gallery (GIFs on the Pi) and the
  // workspace (originals); empty ones made with « + Dossier » are kept too.

  _allFolders() {
    return [...new Set([...this.folders, ...this.originals.map((o) => o.folder), ...this.state.items.map((i) => i.folder)])]
      .filter(Boolean).sort((a, b) => a.localeCompare(b));
  }

  /** Chips: all, unfiled, each folder with its count, then « + Dossier ». */
  _folderChips(active, folderOf, entries) {
    const count = (f) => entries.filter((e) => (folderOf(e) || "") === f).length;
    const hidden = this._allFolders().filter((f) => this._hidden(f));
    const folders = this._allFolders().filter((f) => this._showHidden || !this._hidden(f) || f === active);
    // `active` undefined: a collection is shown, no folder chip is on.
    const chip = (key, label, n) => `<button class="chip-btn ${active !== undefined && String(active ?? "*") === key ? "on" : ""}" data-folder="${esc(key)}">${label} <span class="muted">${n}</span></button>`;
    const used = active && (this.originals.some((o) => o.folder === active) || this.state.items.some((i) => i.folder === active));
    const isHidden = active && active !== TRASH && this._hidden(active);
    return chip("*", "Tous", entries.filter((e) => this._inSight(folderOf(e), null)).length)
      + (folders.length ? chip("", "📂 Sans dossier", count("")) : "")
      + folders.map((f) => chip(f, `${this._hidden(f) ? "🙈" : "📁"} ${esc(f)}`, count(f))).join("")
      + `<details class="menu"><summary class="chip-btn ghost" title="Dossiers : créer, renommer, cacher, supprimer">⋯</summary><div class="menu-list">`
      + `<button class="act ghost small" data-newfolder title="Créer un dossier">+ Nouveau dossier</button>`
      + (active && active !== TRASH ? `<span class="muted small">Dossier « ${esc(active)} »</span>
        <button class="act ghost small" data-renamefolder title="Renommer ce dossier partout (galerie et atelier)">✎ Renommer</button>
        <button class="act ghost small" data-hidefolder title="${isHidden ? "Remettre ce dossier en vue partout"
          : "Cacher ce dossier et son contenu partout (galerie, atelier, « Tous ») ; 👁 les réaffiche"}">${isHidden ? "👁 Réafficher" : "🙈 Cacher"}</button>
        <button class="act ghost small" data-delfolder title="${used ? "Retire le dossier : son contenu passe « Sans dossier » (rien n'est effacé). Toucher deux fois"
          : "Ce dossier est vide"}">🗑 Supprimer</button>` : "")
      + (hidden.length ? `<button class="act ghost small" data-showhidden title="Les dossiers cachés et leur contenu n'apparaissent nulle part (ni dans « Tous ») tant qu'ils ne sont pas affichés">${this._showHidden ? "🙈 Masquer les dossiers cachés" : `👁 Afficher les dossiers cachés (${hidden.length})`}</button>` : "")
      + `</div></details>`;
  }

  /** Collections: custom lists of gallery GIFs picked from any folders (a GIF can be in several). */
  _collectionChips(active) {
    const collections = this.state.collections || [];
    const count = (c) => c.files.filter((f) => this.state.items.some((i) => i.file === f && this._inSight(i.folder, null))).length;
    return `<span class="muted small" title="Des listes faites à la main, piochées dans tous les dossiers ; un ensemble peut les utiliser">🗂 Collections</span>`
      + collections.map((c) => `<button class="chip-btn ${active === c.id ? "on" : ""}" data-col="${esc(c.id)}">🗂 ${esc(c.name)} <span class="muted">${count(c)}</span></button>`).join("")
      + `<details class="menu"><summary class="chip-btn ghost" title="Collections : créer, renommer, supprimer">⋯</summary><div class="menu-list">`
      + `<button class="act ghost small" data-newcol title="Nouvelle collection ; on y ajoute des GIF avec la sélection (🗂 Ajouter)">+ Nouvelle collection</button>`
      + (active ? `<button class="act ghost small" data-renamecol>✎ Renommer</button>
        <button class="act ghost small" data-delcol title="Supprime la collection, pas ses GIF ; un ensemble qui l'utilisait garde sa liste (toucher deux fois)">🗑 Supprimer</button>` : "")
      + `</div></details>`;
  }

  _collectionChipClick(ev) {
    const g = this.state.galleryFilter;
    const collection = (this.state.collections || []).find((c) => c.id === g.collection);
    const redraw = () => this._galleryItems().then(() => this._drawGallery());
    const save = (data) => this._ws({ type: "idotmatrix/studio/collection_save", ...data }).then(redraw,
      (err) => this._onTransfer({ state: "error", what: "Collection", message: errorText(err) }));
    const add = ev.target.closest("[data-newcol]");
    if (add) {
      this._inlineInput(add, { placeholder: "Nom de la collection" }, (name) => {
        if (!name) { this._drawGallery(); return; }
        const id = newId("k");
        g.collection = id;
        g.folder = null;
        save({ collection_id: id, name });
      });
      return;
    }
    const rename = ev.target.closest("[data-renamecol]");
    if (rename && collection) {
      this._inlineInput(rename, { value: collection.name }, (name) => {
        if (!name || name === collection.name) { this._drawGallery(); return; }
        save({ collection_id: collection.id, name });
      });
      return;
    }
    const remove = ev.target.closest("[data-delcol]");
    if (remove && collection) {
      if (!this._armed(remove, "Supprimer la collection ?")) return;
      g.collection = null;
      this._ws({ type: "idotmatrix/studio/collection_delete", collection_id: collection.id }).then(redraw);
      return;
    }
    const chip = ev.target.closest("[data-col]");
    if (chip) {
      g.collection = g.collection === chip.dataset.col ? null : chip.dataset.col;
      g.folder = null;
      this._drawGallery();
    }
  }

  /** Click in a chip row: `select(folder)` filters on it (null: everything). */
  _folderChipClick(ev, active, select) {
    if (ev.target.closest("[data-showhidden]")) {
      this._showHidden = !this._showHidden;
      select(this._showHidden || !this._hidden(active) ? active : null);
      return;
    }
    const hide = ev.target.closest("[data-hidefolder]");
    if (hide) {
      const hidden = !this._hidden(active);
      this._ws({ type: "idotmatrix/studio/folder_hidden", folder: active, hidden }).then((res) => {
        this.state.hiddenFolders = res.hidden_folders;
        // Hiding the folder on screen leaves it, unless the hidden ones are shown.
        select(hidden && !this._showHidden ? null : active);
      }, (err) => this._onTransfer({ state: "error", what: "Dossier", message: errorText(err) }));
      return;
    }
    const add = ev.target.closest("[data-newfolder]");
    if (add) {
      // An inline field rather than prompt(), which phones end up blocking.
      const input = Object.assign(document.createElement("input"), {
        className: "chip-input", placeholder: "Nom du dossier", size: 14, maxLength: 60,
      });
      (add.closest("details.menu") || add).replaceWith(input);
      input.focus();
      input.onkeydown = (e) => {
        if (e.key === "Escape") input.value = "";
        if (e.key === "Enter" || e.key === "Escape") input.blur();
      };
      input.onblur = () => {
        const name = input.value.trim();
        if (name && !this._allFolders().includes(name)) {
          this.folders.push(name);
          this._sync("folders", this.folders);
        }
        select(name || active);
      };
      return;
    }
    const rename = ev.target.closest("[data-renamefolder]");
    if (rename) {
      this._inlineInput(rename, { value: active, placeholder: "Nouveau nom" }, (name) => {
        if (!name || name === active) { select(active); return; }
        this._renameFolder(active, name).then(() => select(name),
          (err) => this._onTransfer({ state: "error", what: "Renommage impossible", message: errorText(err) }));
      });
      return;
    }
    const remove = ev.target.closest("[data-delfolder]");
    if (remove) {
      if (!this._armed(remove, "Sûr ? Le contenu reste, sans dossier")) return;
      // Its GIFs and originals go unfiled; nothing is deleted.
      this._renameFolder(active, "").then(() => {
        this.folders = this.folders.filter((f) => f && f !== active);
        this._sync("folders", this.folders);
        select(null);
      }, (err) => this._onTransfer({ state: "error", what: "Suppression impossible", message: errorText(err) }));
      return;
    }
    const chip = ev.target.closest("[data-folder]");
    if (chip) select(chip.dataset.folder === "*" ? null : chip.dataset.folder);
  }

  /** Rename a folder label on the originals, the gallery GIFs and the kept empty folders. */
  async _renameFolder(from, to) {
    if (this._hidden(from)) {
      // Renamed, a hidden folder stays hidden; deleted (to ""), it is no longer listed.
      const res = await this._ws({ type: "idotmatrix/studio/folder_hidden", folder: from, hidden: Boolean(to), rename: to || undefined });
      this.state.hiddenFolders = res.hidden_folders;
    }
    for (const o of this.originals) {
      if (o.folder !== from) continue;
      Object.assign(o, { folder: to, updated: Date.now() });
      this._saveOriginalMeta(o);
    }
    if (this.folders.includes(from)) {
      this.folders = [...new Set(this.folders.map((f) => (f === from ? to : f)))].filter(Boolean);
      this._sync("folders", this.folders);
    }
    for (const filter of [this.state.galleryFilter, this.state.filter]) {
      if (filter?.folder === from) filter.folder = to;
    }
    const files = this.state.items.filter((i) => i.folder === from).map((i) => i.file);
    if (files.length) {
      await this._ws({ type: "idotmatrix/studio/organize", files, folder: to });
      await this._galleryItems();
    }
  }

  /** An inline field in place of `anchor` (prompt() ends up blocked on phones);
   * `done` gets the trimmed text, or null when cancelled with Escape. */
  _inlineInput(anchor, { value = "", placeholder = "", list = [] }, done) {
    // From a ⋯ menu, the field takes the menu's place in its row: inside the
    // menu it vanished as the menu closed (focusing it scrolls the page).
    anchor = anchor.closest?.("details.menu") || anchor;
    const input = Object.assign(document.createElement("input"), {
      className: "chip-input", value, placeholder, size: 14, maxLength: 60,
    });
    if (list.length) {
      const datalist = Object.assign(document.createElement("datalist"), { id: newId("dl") });
      datalist.innerHTML = list.map((f) => `<option value="${esc(f)}">`).join("");
      input.setAttribute("list", datalist.id);
      anchor.after(datalist);
    }
    anchor.replaceWith(input);
    input.focus();
    let finished = false;
    const finish = (keep) => {
      if (finished) return;
      finished = true;
      done(keep ? input.value.trim() : null);
    };
    input.onkeydown = (e) => {
      if (e.key === "Enter") finish(true);
      if (e.key === "Escape") finish(false);
    };
    input.onblur = () => finish(true);
    input.onclick = (e) => e.stopPropagation();
  }

  /** Text field with the known folders as suggestions, for « Ranger ». */
  _folderField(id) {
    return `<input type="text" id="${id}" list="${id}-list" placeholder="Dossier…" size="10" maxlength="60">
      <datalist id="${id}-list">${this._allFolders().map((f) => `<option value="${esc(f)}">`).join("")}</datalist>`;
  }

  /** Two taps instead of confirm(): browsers end up blocking repeated dialogs. */
  _armed(button, label) {
    if (button.dataset.armed) return true;
    const original = button.innerHTML;
    button.dataset.armed = "1";
    button.classList.add("armed");
    button.innerHTML = label;
    setTimeout(() => {
      if (!button.isConnected) return;
      delete button.dataset.armed;
      button.classList.remove("armed");
      button.innerHTML = original;
    }, 3000);
    return false;
  }

  async _selectionAction(ev) {
    const button = ev.target.closest("button[data-sel]");
    if (!button) return;
    const files = [...this._selected];
    const shown = this._galleryShown().map((i) => i.file);
    try {
      switch (button.dataset.sel) {
        case "all": shown.forEach((f) => this._selected.add(f)); break;
        case "none": this._selected.clear(); break;
        case "move":
          await this._ws({ type: "idotmatrix/studio/organize", files, folder: this._main().querySelector("#gmove").value });
          await this._galleryItems();
          break;
        case "fav":
          await this._ws({ type: "idotmatrix/studio/organize", files, favorite: !files.every((f) => this.state.items.find((i) => i.file === f)?.favorite) });
          await this._galleryItems();
          break;
        case "collect": {
          const name = this._main().querySelector("#gcol").value.trim();
          if (!name) return;
          const known = (this.state.collections || []).find((c) => c.name === name);
          await this._ws({ type: "idotmatrix/studio/collection_save", collection_id: known?.id || newId("k"), name, add: files });
          await this._galleryItems();
          this._onTransfer({ state: "saved", message: `${files.length} GIF dans la collection « ${name} »` });
          break;
        }
        case "uncollect":
          await this._ws({ type: "idotmatrix/studio/collection_save", collection_id: this.state.galleryFilter.collection, remove: files });
          this._selected.clear();
          await this._galleryItems();
          break;
        case "lighten": {
          button.disabled = true;
          button.textContent = `✨ ${files.length} GIF…`;
          const { results } = await this._ws({ type: "idotmatrix/studio/lighten", files });
          const done = results.filter((r) => r.replaced);
          const before = done.reduce((s, r) => s + r.old, 0);
          const after = done.reduce((s, r) => s + r.new, 0);
          const frames = done.reduce((s, r) => s + r.frames_before - r.frames_after, 0);
          const optimal = results.filter((r) => !r.replaced && !r.error).length;
          const failed = results.filter((r) => r.error).length;
          this._onTransfer({ state: "saved", message: [
            done.length ? `${done.length} GIF optimisé(s) : ${kb(before)} → ${kb(after)}${frames ? `, ${frames} images en moins` : ""}` : "",
            optimal ? `${optimal} sans gain possible sans perte visible` : "",
            failed ? `${failed} illisible(s)` : "",
          ].filter(Boolean).join(" · ") || "rien à faire" });
          await this._galleryItems();
          break;
        }
        case "delete":
          if (!this._armed(button, `Supprimer ${files.length} GIF ?`)) return;
          await this._ws({ type: "idotmatrix/studio/organize", files, delete: true });
          this._selected.clear();
          await this._galleryItems();
          break;
        default:
      }
    } catch (err) {
      this._onTransfer({ state: "error", message: errorText(err) });
    }
    this._drawGallery();
  }

  async _galleryAction(ev) {
    const card = ev.target.closest(".item");
    if (!card) return;
    const file = card.dataset.file;
    const button = ev.target.closest("button[data-act]");
    if (!button) return;
    const item = this.state.items.find((i) => i.file === file);
    if (!item) return;
    try {
      switch (button.dataset.act) {
        case "check":
          if (this._selected.has(file)) this._selected.delete(file); else this._selected.add(file);
          this._drawGallery();
          break;
        case "link": {
          const clip = await this._linkGalleryItem(item);
          this._onTransfer(clip
            ? { state: "saved", message: `${item.title} : original relié (${this._original(clip.originalId)?.name})` }
            : { state: "error", what: "Original introuvable", message: await this._searchFolderHint() });
          this._drawGallery();
          break;
        }
        case "folder":
          this._inlineInput(button, { value: item.folder || "", placeholder: "Dossier (vide = aucun)", list: this._allFolders() },
            async (folder) => {
              if (folder !== null && folder !== (item.folder || "")) {
                await this._ws({ type: "idotmatrix/studio/organize", files: [file], folder });
                await this._galleryItems();
              }
              this._drawGallery();
            });
          break;
        case "display":
          await this._display(file);
          break;
        case "favorite":
          await this._ws({ type: "idotmatrix/studio/favorite", file, favorite: !item.favorite });
          item.favorite = !item.favorite;
          this._drawGallery();
          break;
        case "delete":
          if (!this._armed(button, "Supprimer ?")) return;
          await this._ws({ type: "idotmatrix/studio/delete", file });
          this.state.items = this.state.items.filter((i) => i !== item);
          this._drawGallery();
          break;
        case "edit":
          await this._editGalleryItem(item);
          break;
        default:
      }
    } catch (err) {
      this._onTransfer({ state: "error", message: errorText(err) });
    }
  }

  // ------------------------------------------------------------------ store
  // The official app's catalogue, through Home Assistant (the vendor's server
  // signs and encrypts everything). Records carry no title, only a file number
  // and sometimes search tags: the filter searches those, in the pages loaded.

  async _renderStore() {
    const main = this._main();
    const s = (this.state.store ||= { group: "daily", page: 0, pages: 1, total: 0, items: [], q: "", info: {}, error: "" });
    main.innerHTML = `<div class="chips" id="sgroups">
        <button class="chip-btn ${s.group === "favorites" ? "on" : ""}" data-group="favorites">★ Favoris</button>
        ${STORE_GROUPS.map(([key, label]) =>
          `<button class="chip-btn ${key === s.group ? "on" : ""}" data-group="${key}">${label}</button>`).join("")}</div>
      <div class="toolbar">
        <input type="search" id="sq" placeholder="Filtrer (n° ou mot-clé)…" value="${esc(s.q)}">
        <span class="muted small" id="scount"></span>
      </div>
      <div class="grid" id="sgrid"></div>`;
    main.querySelector("#sgroups").onclick = (ev) => {
      const chip = ev.target.closest("[data-group]");
      if (!chip || chip.dataset.group === s.group) return;
      Object.assign(s, { group: chip.dataset.group, page: 0, pages: 1, total: 0, items: [], error: "" });
      this._renderStore();
    };
    main.querySelector("#sq").oninput = (ev) => { s.q = ev.target.value; this._drawStore(); };
    main.querySelector("#sgrid").onclick = (ev) => this._storeAction(ev);
    if (!this._storeFavorites) await this._loadStoreFavorites();
    if (s.group === "favorites") {
      s.items = [...this._storeFavorites.values()];
      Object.assign(s, { page: 1, pages: 1, total: s.items.length });
      this._drawStore();
    } else if (!s.items.length && !s.error) {
      await this._loadStoreAll();
    } else {
      this._drawStore();
    }
  }

  async _loadStoreFavorites() {
    try {
      const { items } = await this._ws({ type: "idotmatrix/studio/store_favorites" });
      this._storeFavorites = new Map(items.map((i) => [i.url, i]));
    } catch (_err) {
      this._storeFavorites = new Map();
    }
  }

  /** Every page of the category, one after another, shown as they arrive. */
  async _loadStoreAll() {
    const s = this.state.store;
    const group = s.group;
    s.loading = true;
    this._drawStore();
    try {
      do {
        const page = await this._ws({ type: "idotmatrix/studio/store_list", group, page: s.page + 1 });
        if (s.group !== group) return;
        const known = new Set(s.items.map((i) => i.url));
        s.items.push(...page.items.filter((i) => !known.has(i.url)));
        Object.assign(s, { page: page.page, pages: page.total_pages, total: page.total, error: "" });
        if (this.state.tab === "store") this._drawStore();
      } while (s.page < s.pages && this.state.tab === "store");
    } catch (err) {
      if (s.group === group) s.error = err.message || String(err);
    } finally {
      if (s.group === group) s.loading = false;
    }
    if (this.state.tab === "store" && s.group === group) this._drawStore();
  }

  _drawStore() {
    const main = this._main();
    const grid = main.querySelector("#sgrid");
    if (!grid) return;
    const s = this.state.store;
    const q = s.q.trim().toLowerCase();
    const shown = s.items.filter((i) => !q || [i.name, ...(i.tags || [])].join(" ").toLowerCase().includes(q));
    const progress = s.loading && s.pages > 1 ? ` · chargement ${s.page}/${s.pages} pages…` : s.loading ? " · chargement…" : "";
    main.querySelector("#scount").textContent = s.items.length
      ? `${shown.length} / ${s.items.length}${s.total && s.group !== "favorites" ? ` sur ${s.total}` : ""}${progress}` : progress.replace(" · ", "");
    if (!shown.length) {
      grid.innerHTML = `<div class="card empty muted" style="grid-column: 1 / -1">${s.error
        ? `Le store ne répond pas : ${esc(s.error)}` : s.loading ? "Chargement du store…"
        : s.group === "favorites" ? "Aucun favori : touche ☆ sur une animation pour la retrouver ici."
        : s.items.length ? "Rien ne correspond." : "Rien dans cette catégorie pour cette taille d'écran."}</div>`;
      return;
    }
    // Redraw only the new cards: the ones already there keep their animation running.
    const drawn = new Map([...grid.querySelectorAll(".item")].map((el) => [el.dataset.url, el]));
    const wanted = new Set(shown.map((i) => i.url));
    for (const [url, el] of drawn) if (!wanted.has(url)) el.remove();
    grid.querySelector(".empty")?.remove();
    let previous = null;
    for (const item of shown) {
      let el = drawn.get(item.url);
      if (!el) {
        const holder = document.createElement("div");
        holder.innerHTML = this._storeCard(item);
        el = holder.firstElementChild;
      }
      if (previous ? previous.nextElementSibling !== el : grid.firstElementChild !== el) {
        if (previous) previous.after(el); else grid.prepend(el);
      }
      previous = el;
    }
    this._observeStoreThumbs();
  }

  /** Thumbnails load when their card comes near the screen (each goes through Home Assistant). */
  _observeStoreThumbs() {
    const s = this.state.store;
    if (typeof IntersectionObserver === "undefined") {
      this._loadStoreThumbs(s.items.filter((i) => !s.info[i.url]));
      return;
    }
    this._storeObserver ||= new IntersectionObserver((entries) => {
      const visible = entries.filter((e) => e.isIntersecting).map((e) => e.target);
      for (const el of visible) this._storeObserver.unobserve(el);
      const items = visible.map((el) => s.items.find((i) => i.url === el.dataset.url)).filter(Boolean);
      if (items.length) this._loadStoreThumbs(items);
    }, { rootMargin: "400px" });
    for (const el of this._main().querySelectorAll("#sgrid .item")) {
      if (!s.info[el.dataset.url]) this._storeObserver.observe(el);
    }
  }

  _storeCard(item) {
    const info = this.state.store.info[item.url];
    const loaded = info && info.src;
    const favorite = this._storeFavorites?.has(item.url);
    const facts = info?.error ? esc(info.error) : loaded
      ? `${kb(info.size_bytes)} · ${info.frames} img · ${(info.duration_ms / 1000).toFixed(1)} s` : "chargement…";
    const ready = loaded ? `<span class="pill" title="${info.device_ready
      ? "Envoyé tel quel, comme par l'app officielle"
      : "Pas à la taille de l'écran : sera redimensionné et réencodé (bien plus lourd)"}">${info.device_ready ? "✓ tel quel" : "↻ redimensionné"}</span>` : "";
    return `<div class="item" data-url="${esc(item.url)}">
      <img alt="" ${loaded ? `src="${info.src}"` : ""}>
      <div class="meta"><div class="title" title="${esc(item.name)}">${esc(item.name)}</div>
        <div class="badges"><span class="pill">${item.width}×${item.height}</span>${ready}
          ${(item.tags || []).map((t) => `<span class="pill">${esc(t)}</span>`).join("")}</div>
        <div class="muted small">${facts}</div>
        ${item.uploaded ? `<div class="muted small">publié le ${esc(item.uploaded)}</div>` : ""}</div>
      <div class="tools">
        <button class="icon" data-act="display" title="Afficher sur le cadre (et l'ajouter à la galerie)">▶</button>
        <button class="icon ${favorite ? "fav" : ""}" data-act="favorite" title="Favori">${favorite ? "★" : "☆"}</button>
        ${item.gallery ? `<span class="pill" title="${esc(item.gallery)}">✓ Dans la galerie</span>`
          : `<button class="act ghost small" data-act="add" title="Ajouter à la galerie">+ Galerie</button>`}
      </div>
    </div>`;
  }

  _redrawStoreCard(item) {
    const card = this.state.tab === "store"
      && [...this._main().querySelectorAll("#sgrid .item")].find((el) => el.dataset.url === item.url);
    if (card) card.outerHTML = this._storeCard(item);
  }

  /** Fetch thumbnails three at a time from a shared queue. */
  async _loadStoreThumbs(items) {
    const s = this.state.store;
    this._thumbQueue ||= [];
    for (const item of items) {
      if (s.info[item.url]) continue;
      s.info[item.url] = { pending: true };
      this._thumbQueue.push(item);
    }
    const worker = async () => {
      for (let item = this._thumbQueue.shift(); item; item = this._thumbQueue.shift()) {
        try {
          const { gif, ...info } = await this._ws({ type: "idotmatrix/studio/store_item", url: item.url });
          s.info[item.url] = { ...info, src: `data:image/gif;base64,${gif}` };
        } catch (err) {
          s.info[item.url] = { error: err.message || String(err) };
        }
        this._redrawStoreCard(item);
      }
    };
    this._thumbWorkers ||= 0;
    const spare = Math.min(3 - this._thumbWorkers, this._thumbQueue.length);
    await Promise.all(Array.from({ length: Math.max(0, spare) }, async () => {
      this._thumbWorkers += 1;
      try { await worker(); } finally { this._thumbWorkers -= 1; }
    }));
  }

  async _storeAction(ev) {
    const button = ev.target.closest("button[data-act]");
    const card = ev.target.closest(".item");
    if (!button || !card) return;
    const s = this.state.store;
    const item = s.items.find((i) => i.url === card.dataset.url);
    if (!item) return;
    if (button.dataset.act === "favorite") {
      const favorite = !this._storeFavorites.has(item.url);
      try {
        await this._ws({ type: "idotmatrix/studio/store_favorite", url: item.url, favorite, item: {
          name: item.name, width: item.width, height: item.height, format: item.format,
          tags: item.tags || [], uploaded: item.uploaded || "",
        } });
        if (favorite) this._storeFavorites.set(item.url, item); else this._storeFavorites.delete(item.url);
        if (s.group === "favorites" && !favorite) {
          s.items = s.items.filter((i) => i !== item);
          this._drawStore();
        } else {
          this._redrawStoreCard(item);
        }
      } catch (err) {
        this._onTransfer({ state: "error", what: "Favori impossible", message: errorText(err) });
      }
      return;
    }
    const display = button.dataset.act === "display";
    button.disabled = true;
    try {
      const result = await this._ws({ type: "idotmatrix/studio/store_import", url: item.url, title: item.name, display, device: deviceName() });
      item.gallery = result.file;
      if (display) this._onTransfer({ file: result.file, state: "started" });
      else if (result.existing) this._onTransfer({ state: "saved", message: `déjà dans la galerie : ${result.file}` });
      else this._onTransfer({ state: "saved", message: `${result.file} ajouté à la galerie (${kb(result.size_bytes)}${result.reencoded ? ", réencodé" : ""})` });
    } catch (err) {
      this._onTransfer({ state: "error", what: "Import impossible", message: errorText(err) });
    } finally {
      button.disabled = false;
    }
  }

  async _display(file) {
    await this._ws({ type: "idotmatrix/studio/display", file });
    this._onTransfer({ file, state: "started" });
  }

  /** Re-edit a gallery GIF from its original when this browser still has it. */
  async _editGalleryItem(item) {
    const clip = this._linkedClip(item) || await this._linkGalleryItem(item);
    if (clip) {
      await this._openEditor(clip);
      return;
    }
    if (!confirm("L'original de ce GIF n'est pas dans ce navigateur. Le retoucher à partir du GIF lui-même (qualité réduite) ?")) return;
    const url = await this._sign(`${item.url}?v=${Math.round(item.modified)}`);
    const blob = await (await fetch(url)).blob();
    const original = await this._addOriginal(new File([blob], item.file, { type: "image/gif" }), item.folder || "");
    const fromGif = this._clipsOf(original)[0];
    Object.assign(fromGif, { title: item.title, pushed: item.file });
    this._persistClip(fromGif);
    await this._openEditor(fromGif);
  }

  /** The workspace clip a gallery GIF was made from, when this browser has its original. */
  _linkedClip(item) {
    const clip = this.clips.find((c) => c.id === item.clip) || this.clips.find((c) => c.pushed === item.file);
    const original = clip && this._original(clip.originalId);
    return original && !original.missing && !original.trashed ? clip : null;
  }

  /** Find a gallery GIF's original in the search folders: relink the workspace's
   * copy from another device, or add it to the workspace linked to the GIF. */
  async _linkGalleryItem(item) {
    const known = this.clips.find((c) => c.id === item.clip) || this.clips.find((c) => c.pushed === item.file);
    const original = known && this._original(known.originalId);
    if (original?.missing) {
      const file = await this._findSource({ name: original.name, size: original.size }, true);
      if (!file || (original.size && file.size !== original.size)) return null;
      await this._relink(original, file);
      return known;
    }
    const file = await this._findSource({ name: item.source || item.title || item.file });
    if (!file) return null;
    // The same file already in the workspace gets a clip for this GIF: no twin original.
    const twin = this.originals.find((o) => !o.trashed && o.name === file.name && (!o.size || o.size === file.size));
    if (twin?.missing) await this._relink(twin, file);
    const clip = twin ? this._newClip(twin) : this._clipsOf(await this._addOriginal(file, item.folder || ""))[0];
    Object.assign(clip, { title: item.title, pushed: item.file });
    this._persistClip(clip);
    return clip;
  }

  // ----------------------------------------------------- search folders

  async _searchFolders() {
    try {
      return (await searchFolderStore("readonly", (store) => store.getAll())) || [];
    } catch (_err) {
      return [];  // no IndexedDB (private window…)
    }
  }

  /** Whether there is anywhere to look: kept folders, or one chosen for this visit. */
  async _hasSearchFolders() {
    return Boolean(this._visitSources?.length || (await this._searchFolders()).length);
  }

  async _searchFolderHint() {
    return (await this._hasSearchFolders())
      ? "aucun fichier de ce nom dans les dossiers de recherche"
      : "ajoute un dossier de recherche dans l'onglet ⚙";
  }

  /** Every media file under the search folders, read once per visit (↻ in ⚙ reads them again). */
  async _sourceIndex(refresh = false) {
    if (this._sources && !refresh) return this._sources;
    // Folders chosen for this visit only (browsers without folder handles: Brave, Firefox…).
    const files = [...(this._visitSources || [])];
    for (const root of await this._searchFolders()) {
      const handle = root.handle;
      if (await handle.queryPermission?.({ mode: "read" }) !== "granted"
          && await handle.requestPermission?.({ mode: "read" }) !== "granted") continue;
      const walk = async (dir, path, depth) => {
        for await (const entry of dir.values()) {
          if (entry.kind === "directory") {
            if (depth < 12) await walk(entry, `${path}/${entry.name}`, depth + 1);
          } else if (MEDIA_RE.test(entry.name)) {
            files.push({ name: entry.name, path: `${path}/${entry.name}`, handle: entry, size: null });
          }
        }
      };
      try {
        await walk(handle, root.name, 0);
      } catch (_err) { /* moved or unplugged: the others still count */ }
    }
    this._sources = files;
    return files;
  }

  /** The source file of `target` ({name, size?}) in the search folders, or null. */
  async _findSource(target, exact = false) {
    const index = await this._sourceIndex();
    const lower = target.name.toLowerCase();
    for (const f of index) {
      if (f.size === null && target.size && f.name.toLowerCase() === lower) f.size = (await f.handle.getFile()).size;
    }
    const hit = matchSource(target, index, exact);
    return hit ? hit.file || hit.handle.getFile() : null;
  }

  /** Relink every original missing here that the search folders hold (same name and size). */
  async _relinkAll() {
    let linked = 0;
    let missing = 0;
    for (const o of this.originals.filter((x) => x.missing && !x.trashed)) {
      missing += 1;
      const file = await this._findSource({ name: o.name, size: o.size }, true);
      if (!file || (o.size && file.size !== o.size)) continue;
      try {
        await this._relink(o, file);
        linked += 1;
      } catch (_err) { /* unreadable here: stays missing */ }
    }
    return { linked, missing };
  }

  async _renderConfig() {
    const main = this._main();
    const supported = typeof window.showDirectoryPicker === "function";
    main.innerHTML = `<div class="card">
        <b>Cet appareil</b>
        <div class="row"><input type="text" id="cdev" maxlength="40" value="${esc(deviceName())}" placeholder="${esc(deviceLabel())}">
          <span class="muted small grow">Nom gardé avec chaque original importé et chaque GIF envoyé depuis ce navigateur (filtre « envoyé depuis » de la galerie et de l'atelier).</span></div>
      </div>
      <div class="card" style="margin-top: 12px">
        <b>Dossiers de recherche</b>
        <p class="muted small">« Relier » et 🔗 y cherchent les originaux, sous-dossiers compris : même nom (et même taille) d'abord, sinon le nom dont part celui du GIF —
          « 2025-05-01-190800_original_boomerang.gif » retrouve « 2025-05-01-190800.mp4 ». Gardés dans ce navigateur ; il redemande l'accès une fois par visite.</p>
        <div id="croots"></div>
        ${supported ? "" : `<p class="error small">${this._folderAccessHelp()}
          En attendant, « 📂 Pour cette visite » lit un dossier et ses sous-dossiers jusqu'à la fermeture de la page.</p>`}
        <div class="row"><button class="act" id="cadd" ${supported ? "" : "hidden"}>+ Ajouter un dossier</button>
          <button class="act ${supported ? "ghost" : ""}" id="cvisit" title="Choisir un dossier lu jusqu'à la fermeture de la page">📂 Pour cette visite</button>
          <input type="file" id="cvisitInput" webkitdirectory multiple hidden>
          <button class="act ghost" id="crelink">🔗 Relier tout</button>
          <button class="act ghost" id="crescan" title="Relire les dossiers (fichiers ajoutés depuis)">↻</button>
          <span class="muted small grow" id="cinfo"></span></div>
      </div>`;
    const $ = (sel) => main.querySelector(sel);
    const info = (text) => { $("#cinfo").textContent = text; };
    const drawRoots = async () => {
      const roots = await this._searchFolders();
      $("#croots").innerHTML = roots.map((r) => `<div class="row"><span class="grow">📁 ${esc(r.name)}</span>
        <button class="icon" data-del="${esc(r.id)}" title="Ne plus chercher ici">✕</button></div>`).join("")
        + (this._visitRoots || []).map((name) => `<div class="row"><span class="grow">📂 ${esc(name)}
          <span class="muted small">· pour cette visite</span></span></div>`).join("")
        || `<p class="muted small">Aucun dossier.</p>`;
    };
    $("#cdev").onchange = (ev) => {
      const name = ev.target.value.trim();
      try {
        if (name && name !== deviceLabel()) localStorage.setItem(DEVICE_NAME_KEY, name);
        else localStorage.removeItem(DEVICE_NAME_KEY);
      } catch (_err) { /* storage off */ }
      ev.target.value = deviceName();
    };
    $("#croots").onclick = async (ev) => {
      const del = ev.target.closest("[data-del]");
      if (!del) return;
      await searchFolderStore("readwrite", (store) => store.delete(del.dataset.del));
      this._sources = null;
      drawRoots();
    };
    $("#cadd").onclick = async () => {
      try {
        const handle = await window.showDirectoryPicker({ id: "idotmatrix-sources", mode: "read" });
        await searchFolderStore("readwrite", (store) => store.put({ id: newId("d"), name: handle.name, handle }));
        this._sources = null;
        drawRoots();
      } catch (err) {
        if (err?.name !== "AbortError") info(err.message || String(err));
      }
    };
    $("#cvisit").onclick = () => $("#cvisitInput").click();
    $("#cvisitInput").onchange = (ev) => {
      const picked = [...ev.target.files].filter((f) => MEDIA_RE.test(f.name));
      const root = (ev.target.files[0]?.webkitRelativePath || "").split("/")[0] || "dossier";
      this._visitSources = [...(this._visitSources || []),
        ...picked.map((f) => ({ name: f.name, path: f.webkitRelativePath || f.name, size: f.size, file: f }))];
      this._visitRoots = [...new Set([...(this._visitRoots || []), root])];
      this._sources = null;
      ev.target.value = "";
      info(`${picked.length} fichier(s) média dans « ${root} »`);
      drawRoots();
    };
    $("#crescan").onclick = async () => {
      info("lecture des dossiers…");
      info(`${(await this._sourceIndex(true)).length} fichier(s) trouvés`);
    };
    $("#crelink").onclick = async () => {
      info("recherche…");
      const { linked, missing } = await this._relinkAll();
      info(missing ? `${linked} original(aux) relié(s) sur ${missing} absent(s) ici` : "aucun original ne manque dans ce navigateur");
    };
    drawRoots();
  }

  /** Why this browser cannot keep search folders, and how to allow it. */
  _folderAccessHelp() {
    const flags = navigator.brave ? "brave://flags" : "chrome://flags";
    if (!window.isSecureContext) {
      // The File System Access API only exists on secure pages (https or localhost).
      return `Cette page est en <b>http</b> (${esc(window.location.origin)}) : les navigateurs ne gardent un dossier que sur une page sécurisée.
        Pour l'autoriser quand même : ouvre <b>${flags}/#unsafely-treat-insecure-origin-as-secure</b>, mets « Enabled »,
        écris <b>${esc(window.location.origin)}</b> dans la case${navigator.brave ? ", active aussi <b>brave://flags/#file-system-access-api</b>" : ""}
        puis relance le navigateur. Ou ouvre Home Assistant en https.`;
    }
    if (navigator.brave) {
      return "Brave bloque l'accès aux dossiers par défaut : ouvre <b>brave://flags/#file-system-access-api</b>, mets « Enabled » et relance Brave.";
    }
    return "Ce navigateur ne sait pas garder un dossier (il faut Chrome, Edge ou Brave, sur ordinateur).";
  }

  // ------------------------------------------------------------------ queue
  // What is going on, on the Pi (sends to the displays, re-encodings, routines)
  // and in this browser (sends to the Pi, video conversions, files being read).

  async _renderQueue() {
    const main = this._main();
    main.innerHTML = `<div class="card"><b>Sur le Pi</b><div id="qpi"><p class="muted small">…</p></div></div>
      <div class="card" style="margin-top: 12px"><b>Dans ce navigateur</b><div id="qbrowser"></div></div>`;
    main.querySelector("#qpi").onclick = (ev) => this._queueAction(ev);
    main.querySelector("#qbrowser").onclick = (ev) => this._queueAction(ev);
    const refresh = async () => {
      if (this.state.tab !== "queue") return;
      try {
        this._piJobs = await this._ws({ type: "idotmatrix/studio/jobs" });
      } catch (err) {
        this._piJobs = { error: err.message || String(err) };
      }
      this._drawQueue();
    };
    clearInterval(this._queueTimer);
    this._queueTimer = setInterval(refresh, 1500);
    await refresh();
  }

  _drawQueue() {
    const pi = this._main().querySelector("#qpi");
    const browser = this._main().querySelector("#qbrowser");
    if (!pi || !browser) return;
    const row = (icon, text, detail, button = "") => `<div class="row qrow"><span class="grow">${icon} ${text}
      ${detail ? `<span class="muted small">· ${detail}</span>` : ""}</span>${button}</div>`;
    const cancel = (attr, title = "Annuler") => `<button class="icon" ${attr} title="${title}">✕</button>`;
    const { jobs = [], routines = [], error } = this._piJobs || {};
    const piRows = [
      ...jobs.map((j) => {
        const where = j.display ? ` → ${esc(j.display)}` : "";
        const progress = j.total ? ` ${j.sent || 0}/${j.total}` : "";
        if (j.kind === "display") {
          return row("📤", `${esc(j.label)}${where}`, j.state === "sending" ? `envoi au cadre${progress} paquets` : "en attente",
            cancel(`data-cancel-pi="${esc(j.id)}"`, j.state === "sending" ? "Arrêter avant le prochain paquet" : "Retirer de la file"));
        }
        if (j.kind === "lighten") return row("✨", `Optimisation de ${esc(j.label)}`, `${j.sent}/${j.total}`, cancel(`data-cancel-pi="${esc(j.id)}"`, "Arrêter après le GIF en cours"));
        return row("⚙", `Fabrication du GIF « ${esc(j.label)} »`, "sur le Pi (palette, allègement)");
      }),
      ...routines.map((r) => row("🔁", `Routine « ${esc(r.name)} »${r.display ? ` → ${esc(r.display)}` : ""}`,
        this._routineStatusText(r.status || {}), `<button class="icon" data-stop-routine="${esc(r.entry_id)}" title="Arrêter la routine">■</button>`)),
    ];
    pi.innerHTML = error ? `<p class="error small">${esc(error)}</p>` : piRows.join("") || `<p class="muted small">Rien en cours.</p>`;
    const [first, ...waiting] = this._queue;
    const converting = this.originals.filter((o) => o.status === "busy" && /conver|copie|format/i.test(o.progress || ""));
    const reading = this._imports.length;
    const browserRows = [
      ...(first ? [row("⇧", `« ${esc(first.clip.title)} » vers le Pi`, esc(first.phase || ""), cancel(`data-cancel-push="0"`, "Interrompre"))] : []),
      ...waiting.map((j, i) => row("⇧", `« ${esc(j.clip.title)} » vers le Pi`, "en attente", cancel(`data-cancel-push="${i + 1}"`, "Retirer de la file"))),
      ...converting.map((o) => row("🎞", esc(o.name), esc(o.progress), cancel(`data-cancel-convert="${esc(o.id)}"`, "Arrêter la conversion"))),
      ...(reading ? [row("⇩", `${reading} fichier(s) à lire`, "import en cours")] : []),
    ];
    browser.innerHTML = browserRows.join("") || `<p class="muted small">Rien en cours.</p>`;
  }

  async _queueAction(ev) {
    const button = ev.target.closest("button");
    if (!button) return;
    try {
      if (button.dataset.cancelPi) {
        await this._ws({ type: "idotmatrix/studio/job_cancel", job_id: button.dataset.cancelPi });
      } else if (button.dataset.stopRoutine) {
        await this._ws({ type: "idotmatrix/studio/routine_stop", entry_id: button.dataset.stopRoutine });
      } else if (button.dataset.cancelPush !== undefined) {
        this._cancelPush(this._queue[Number(button.dataset.cancelPush)]);
      } else if (button.dataset.cancelConvert) {
        stopConversions();
      }
    } catch (err) {
      this._onTransfer({ state: "error", what: "Annulation impossible", message: errorText(err) });
    }
    if (this.state.tab === "queue") this._renderQueue();
  }

  /** Take a clip out of the queue to the Pi; the one in progress is interrupted. */
  _cancelPush(job) {
    const index = this._queue.indexOf(job);
    if (index < 0) return;
    job.cancelled = true;
    if (index === 0) {
      this._xhr?.abort();
      return;
    }
    this._queue.splice(index, 1);
    Object.assign(job.clip, { status: "ready", progress: null });
    this._updateClipRow(job.clip);
    job.resolve(false);
    this._renderJobs();
  }

  /** Options of an « envoyé depuis » filter. */
  _deviceOptions(devices, selected) {
    const names = [...new Set(devices.filter(Boolean))].sort((a, b) => a.localeCompare(b));
    const option = (value, label) => `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${label}</option>`;
    return option("*", "Tous appareils") + names.map((n) => option(n, `📤 ${esc(n)}`)).join("")
      + (devices.some((d) => !d) ? option("", "Non noté") : "");
  }

  // -------------------------------------------------------------- workspace

  async _renderWorkspace() {
    const main = this._main();
    const f = this.state.filter ||= { q: "", status: "all", kind: "all", folder: null, device: "*" };
    f.device ??= "*";
    const missing = this.originals.filter((o) => o.missing && !o.trashed).length;
    this._wselected ||= new Set();
    const pending = this.clips.filter((c) => !c.pushed || c.dirty).length;
    main.innerHTML = `<div class="filterbar"><div class="toolbar">
        <button class="act" id="browse" title="Ajouter des images, GIF ou vidéos (ou glisse-les n'importe où sur la page)">+ Ajouter</button>
        <input type="file" id="file" accept="image/*,video/*,.avi,.mkv,.wmv,.flv,.mpg,.mpeg,.vob,.ts,.mts,.m2ts,.divx,.3gp,.asf" multiple hidden>
        <input type="search" id="q" placeholder="Filtrer…" value="${esc(f.q)}">
        <select id="fstatus" title="État des clips">
          <option value="all">Tous les clips</option><option value="todo">À envoyer</option>
          <option value="dirty">Modifiés</option><option value="pi">Sur le Pi</option></select>
        <select id="fkind" title="Type d'original">
          <option value="all">Tout</option><option value="video">Vidéos</option>
          <option value="gif">GIF</option><option value="image">Images</option></select>
        <select id="fdev" title="Importé depuis">${this._deviceOptions(this.originals.map((o) => o.device), f.device)}</select>
        ${missing ? `<button class="act ghost small" id="relinkAll" title="Chercher les originaux absents ici dans les dossiers de recherche (⚙)">🔗 Relier (${missing})</button>` : ""}
        <span class="grow"></span>
        <button class="act" id="pushAll" ${pending ? "" : "disabled"} title="Envoyer au Pi les clips nouveaux ou modifiés">⬆ Tout envoyer (${pending})</button>
        <button class="act ghost" id="redoAll" title="Refaire depuis leur source, en rendu Équilibré, les GIF déjà sur le Pi (ils remplacent les anciens)">♻ Refaire en Équilibré (${this._redoable().length})</button>
      </div>
      <div class="chips" id="wfolders"></div>
      <div class="muted small">${this.originals.length} original(aux) · ${this.clips.length} clip(s)${this._noHistory
        ? " · historique indisponible dans ce navigateur" : " · gardés dans ce navigateur, seuls les GIF finaux vont sur le Pi"}${f.folder && f.folder !== TRASH
        ? ` · les ajouts vont dans 📁 ${esc(f.folder)}` : ""}</div>
      <div class="selbar" id="wselbar" hidden></div></div>
      <div id="tree"></div>`;
    main.querySelector("#fstatus").value = f.status;
    main.querySelector("#fkind").value = f.kind;
    const input = main.querySelector("#file");
    main.querySelector("#browse").onclick = () => input.click();
    input.onchange = () => this._addFiles([...input.files]);
    main.ondragover = (ev) => { ev.preventDefault(); main.classList.add("over"); };
    main.ondragleave = (ev) => { if (ev.target === main) main.classList.remove("over"); };
    main.ondrop = (ev) => {
      ev.preventDefault();
      main.classList.remove("over");
      if (ev.dataTransfer.files.length) this._addFiles([...ev.dataTransfer.files]);
    };
    main.querySelector("#q").oninput = (ev) => { f.q = ev.target.value; this._renderTree(); };
    main.querySelector("#fstatus").onchange = (ev) => { f.status = ev.target.value; this._renderTree(); };
    main.querySelector("#fkind").onchange = (ev) => { f.kind = ev.target.value; this._renderTree(); };
    main.querySelector("#fdev").onchange = (ev) => { f.device = ev.target.value; this._renderTree(); };
    const relinkAll = main.querySelector("#relinkAll");
    if (relinkAll) {
      relinkAll.onclick = async () => {
        if (!(await this._hasSearchFolders())) { this._show("config"); return; }
        relinkAll.disabled = true;
        const { linked, missing: absent } = await this._relinkAll();
        this._onTransfer({ state: "saved", message: `${linked} original(aux) relié(s) sur ${absent}` });
        if (this.state.tab === "workspace") this._renderWorkspace();
      };
    }
    main.querySelector("#pushAll").onclick = () => this._pushAll();
    main.querySelector("#redoAll").onclick = (ev) => this._redoAll(ev.currentTarget);
    // The note about where imports go changes with the folder: redraw it all.
    main.querySelector("#wfolders").onclick = (ev) => this._folderChipClick(ev, f.folder, (folder) => {
      f.folder = folder;
      this._renderWorkspace();
    });
    main.querySelector("#wselbar").onclick = (ev) => this._workspaceSelection(ev);
    const tree = main.querySelector("#tree");
    tree.onclick = (ev) => this._workspaceAction(ev);
    tree.onchange = (ev) => this._workspaceChange(ev);
    this._renderTree();
    this._renderTransfer();
    try {
      await this._galleryItems();  // which clips are on the Pi
    } catch (_err) { /* the tree still works without it */ }
    for (const clip of this.clips) this._updateClipRow(clip);
    this._drawThumbs();
  }

  /** Newest first, filtered by text, clip state and original type. */
  _renderTree() {
    const tree = this._main().querySelector("#tree");
    if (!tree) return;
    const f = this.state.filter;
    const q = f.q.trim().toLowerCase();
    const kindOf = (o) => ((o.src || o.info)?.kind === "video" || isVideo(o.file) ? "video"
      : /gif$/i.test(o.file.type || o.name) ? "gif" : "image");
    const statusOk = (c) => f.status === "all" || (f.status === "todo" && !c.pushed)
      || (f.status === "dirty" && c.pushed && c.dirty) || (f.status === "pi" && c.pushed && !c.dirty);
    const chips = this._main().querySelector("#wfolders");
    chips.innerHTML = this._folderChips(f.folder, (o) => o.folder, this.originals);
    if (this._trashTotal()) {
      chips.insertAdjacentHTML("beforeend", `<button class="chip-btn ${f.folder === TRASH ? "on" : ""}" data-folder="${TRASH}"
        title="Ce qui a été supprimé, gardé ${TRASH_DAYS} jours">🗑 Corbeille <span class="muted">${this._trashTotal()}</span></button>`);
    }
    if (f.folder === TRASH) {
      this._main().querySelector("#wselbar").hidden = true;
      tree.innerHTML = this._trashHtml();
      return;
    }
    this._drawWorkspaceSelectionBar();
    const rows = [];
    for (const o of [...this.originals].sort((a, b) => b.created - a.created)) {
      if (f.folder !== null && (o.folder || "") !== f.folder) continue;
      if (!this._inSight(o.folder, f.folder)) continue;
      if (f.kind !== "all" && kindOf(o) !== f.kind) continue;
      if (f.device !== "*" && (o.device || "") !== f.device) continue;
      const nameHit = !q || o.name.toLowerCase().includes(q);
      const clips = this._clipsOf(o).sort((a, b) => b.created - a.created)
        .filter((c) => statusOk(c) && (nameHit || c.title.toLowerCase().includes(q)));
      if (!clips.length && (!nameHit || f.status !== "all")) continue;
      rows.push(this._originalHtml(o, clips));
    }
    tree.innerHTML = rows.join("") || `<div class="card empty muted">${this.originals.length
      ? "Rien ne correspond aux filtres." : "Ajoute des images, GIF ou vidéos : bouton « + Ajouter » ou glisser-déposer."}</div>`;
    for (const clip of this.clips) this._updateClipRow(clip);
    this._drawVisibleThumbs();
  }

  _originalHtml(o, clips) {
    const collapsed = this._collapsed?.has(o.id);
    const selected = this._wselected.has(o.id);
    const folder = o.folder && this.state.filter.folder === null ? `<span class="pill">📁 ${esc(o.folder)}</span> ` : "";
    return `<section class="orig ${selected ? "selected" : ""}" data-orig="${o.id}">
      <div class="orow">
        <button class="icon check" data-act="pick" title="Sélectionner">${selected ? "☑" : "☐"}</button>
        <button class="icon fold" data-act="fold" title="Replier / déplier">${collapsed ? "▸" : "▾"}</button>
        <canvas class="othumb" width="96" height="54"></canvas>
        <div class="grow ellipsis">${folder}${/\.([a-z0-9]{2,5})$/i.test(o.name) ? `<span class="pill">${esc(/\.([a-z0-9]{2,5})$/i.exec(o.name)[1].toUpperCase())}</span> ` : ""}<span class="title">${esc(o.name)}</span>
          <span class="muted small ostatus">${this._originalStatus(o)}</span></div>
        ${o.missing ? `<button class="act small" data-act="relink" title="Choisir ce même fichier sur cet appareil">📂 Relier</button>`
          : `${o.needsCopy && o.status !== "busy" ? `<button class="act ghost small" data-act="convert" title="Préparer maintenant une copie que ce navigateur sait lire">⚙ Convertir</button>` : ""}
            <button class="act ghost small" data-act="newclip" title="Tirer un nouveau clip de cet original">+ Clip</button>`}
        <button class="icon" data-act="folder" title="Ranger dans un dossier">📁</button>
        <button class="icon" data-act="delorig" title="Mettre l'original et ses clips à la corbeille (restaurable 30 jours)">✕</button>
      </div>
      <div class="clips" ${collapsed ? "hidden" : ""}>${clips.map((c) => this._clipHtml(c)).join("")
        || `<div class="muted small">Aucun clip.</div>`}</div>
    </section>`;
  }

  _clipHtml(c) {
    const speeds = SPEEDS.includes(c.opts.speed) ? SPEEDS : [...SPEEDS, c.opts.speed].sort((a, b) => a - b);
    return `<div class="clip crow" data-clip="${c.id}">
      <canvas class="cthumb" width="64" height="64"></canvas>
      <div class="grow ellipsis"><span class="title">${esc(c.title)}</span>
        <span class="muted small cstatus"></span></div>
      <select data-act="speed" class="small" title="Vitesse du clip">${speeds.map((v) => `<option value="${v}" ${v === c.opts.speed ? "selected" : ""}>×${v}</option>`).join("")}</select>
      <span class="chip fgif"></span>
      <button class="icon" data-act="edit" title="Éditer (depuis l'original)">✎</button>
      <button class="icon" data-act="push" title="Envoyer au Pi (dans la galerie, sans l'afficher)">⬆</button>
      <button class="icon" data-act="show" title="Afficher sur le cadre (l'envoie d'abord si besoin)">▶</button>
      <button class="icon" data-act="dup" title="Dupliquer le clip">⧉</button>
      <button class="icon" data-act="delclip" title="Mettre le clip à la corbeille (son GIF reste dans la galerie)">✕</button>
    </div>`;
  }

  _drawWorkspaceSelectionBar() {
    const bar = this._main().querySelector("#wselbar");
    bar.hidden = !this._wselected.size;
    if (!this._wselected.size) return;
    const n = this._wselected.size;
    bar.innerHTML = `<b>${n} original${n > 1 ? "aux" : ""}</b>
      <button class="act ghost small" data-sel="all">Tout</button><button class="act ghost small" data-sel="none">Aucun</button>
      <span class="grow"></span>
      ${this._folderField("wmove")}
      <button class="act small" data-sel="move" ${n ? "" : "disabled"} title="Ranger dans ce dossier (vide = sans dossier)">📁 Ranger</button>
      <button class="act ghost small" data-sel="trash" ${n ? "" : "disabled"} title="Mettre à la corbeille (restaurable ${TRASH_DAYS} jours)">🗑 Corbeille</button>`;
  }

  _workspaceSelection(ev) {
    const button = ev.target.closest("button[data-sel]");
    if (!button) return;
    const action = button.dataset.sel;
    if (action === "all") {
      for (const row of this._main().querySelectorAll("#tree .orig")) this._wselected.add(row.dataset.orig);
    } else if (action === "none") {
      this._wselected.clear();
    } else if (action === "move") {
      const folder = this._main().querySelector("#wmove").value.trim();
      for (const id of this._wselected) {
        const o = this._original(id);
        if (!o) continue;
        Object.assign(o, { folder, updated: Date.now() });
        this._saveOriginalMeta(o);
      }
      this._wselected.clear();
    } else if (action === "trash") {
      for (const id of [...this._wselected]) {
        const o = this._original(id);
        if (o) this._trashOriginal(o);
      }
      this._wselected.clear();
      this._renderWorkspace();
      return;
    }
    this._renderTree();
  }

  _originalStatus(o) {
    if (o.status === "busy") return esc(o.progress || "lecture…");
    if (o.status === "error") return `<span class="error">illisible : ${esc(o.error || "")}</span>`;
    if (o.needsCopy) return "🎞 format à convertir pour ce navigateur : fait à la première ouverture (ou « Convertir »), une seule fois";
    if (o.missing) {
      const icon = o.device === "PC" ? "💻" : "📱";
      return `${icon} importé sur ${esc(o.device || "un autre appareil")}, absent ici${o.size ? ` (${kb(o.size)})` : ""} : « Relier » ou ajoute le même fichier`;
    }
    const kept = o.notKept ? ` · <span class="error">non conservé (stockage plein)</span>` : "";
    const s = o.src ? sourceInfo(o.src) : o.info;
    if (!s) return `chargement…${kept}`;
    const kind = s.kind === "video" ? `vidéo ${clock(s.duration)}`
      : s.kind === "animated" ? `GIF animé, ${s.frames} images, ${clock(s.duration)}` : "image";
    return `${kind} · ${s.width}×${s.height}${kept}`;
  }

  _clipStatus(c) {
    if (c.status === "busy") return esc(c.progress || "traitement…");
    if (c.status === "error") return `<span class="error">${esc(c.error)}</span>`;
    const parts = [];
    const original = this._original(c.originalId);
    const s = original?.src || original?.info;
    const kind = c.src?.kind || s?.kind;
    if (kind && kind !== "image") {
      const start = c.opts.start || 0;
      const fallback = kind === "video" ? VIDEO_SECONDS : ANIMATED_SECONDS;
      const end = Math.min(s?.duration ?? Infinity, c.opts.end ?? start + fallback);
      parts.push(`${clock(start)} → ${Number.isFinite(end) ? clock(end) : "fin"}`);
    }
    if (c.opts.boomerang) parts.push("boomerang");
    const size = c.result?.size_bytes ?? c.sizeBytes;
    if (size) parts.push(kb(size));
    if (c.pushed && c.dirty) parts.push(`<span class="warn">modifié depuis l'envoi : ⬆ pour mettre à jour</span>`);
    else if (!c.pushed) parts.push("pas encore sur le Pi");
    return parts.join(" · ");
  }

  _updateClipRow(c) {
    const row = this.shadowRoot.querySelector(`.clip[data-clip="${c.id}"]`);
    if (row) {
      row.querySelector(".cstatus").innerHTML = this._clipStatus(c);
      row.querySelector('[data-act="push"]').classList.toggle("todo", !c.pushed || !!c.dirty);
      const item = c.pushed && this.state.items.find((i) => i.file === c.pushed);
      row.querySelector(".fgif").innerHTML = item
        ? `<span title="${esc(item.file)} · ${item.frames} images">sur le Pi · ${kb(item.size_bytes)}</span>` : "";
    }
    const pushAll = this.shadowRoot.querySelector("#pushAll");
    if (pushAll) {
      const pending = this.clips.filter((x) => !x.pushed || x.dirty).length;
      pushAll.textContent = `⬆ Tout envoyer (${pending})`;
      pushAll.disabled = !pending;
    }
  }

  _updateOriginalRow(o) {
    const el = this.shadowRoot.querySelector(`.orig[data-orig="${o.id}"] .ostatus`);
    if (el) el.innerHTML = this._originalStatus(o);
  }

  _drawVisibleThumbs() {
    for (const o of this.originals) {
      if (o.poster || o.src) this._drawOriginalThumb(o);
      for (const c of this._clipsOf(o)) if (c.thumb) {
        const canvas = this.shadowRoot.querySelector(`.clip[data-clip="${c.id}"] .cthumb`);
        if (canvas) drawLed(canvas, c.thumb);
      }
    }
  }

  async _drawOriginalThumb(o) {
    const canvas = this.shadowRoot.querySelector(`.orig[data-orig="${o.id}"] .othumb`);
    if (!canvas) return;
    if (!o.poster) {
      // A small copy: the decoded source is released once the row is drawn.
      const full = o.src.kind === "video" ? (await sourceFrames(o.src, { start: 0, end: 0.01 }, 64, 1))[0].bmp : o.src.frames[0].bmp;
      const scale = Math.min(1, (2 * canvas.width) / full.width, (2 * canvas.height) / full.height);
      o.poster = await createImageBitmap(full, {
        resizeWidth: Math.max(1, Math.round(full.width * scale)), resizeHeight: Math.max(1, Math.round(full.height * scale)),
        resizeQuality: "high",
      });
    }
    const first = o.poster;
    const ctx = canvas.getContext("2d");
    const scale = Math.min(canvas.width / first.width, canvas.height / first.height);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(first, (canvas.width - first.width * scale) / 2, (canvas.height - first.height * scale) / 2,
      first.width * scale, first.height * scale);
  }

  async _drawThumbs() {
    // One original at a time and one pass at a time, each source released
    // once drawn: a bulk import on a phone otherwise runs out of memory and
    // the page reloads.
    if (this._thumbing) {
      this._thumbAgain = true;
      return;
    }
    this._thumbing = true;
    try {
      do {
        this._thumbAgain = false;
        for (const o of [...this.originals]) {
          if (this.state.tab !== "workspace") return;
          if (o.status === "busy" || o.missing || !o.file) continue;
          const clips = this._clipsOf(o);
          if (o.poster && (o.src || o.info) && clips.every((c) => c.thumb)) continue;
          if (o.needsCopy) continue;
          try {
            if (!o.src) o.src = await loadSource(o.file);
          } catch (err) {
            if (isVideo(o.file)) o.needsCopy = true;  // converted when first used
            else o.status = "error";
            this._updateOriginalRow(o);
            continue;
          }
          this._updateOriginalRow(o);
          await this._drawOriginalThumb(o);
          for (const c of clips) {
            await this._drawClipThumb(c);
            this._updateClipRow(c);
          }
          this._release(o);
        }
      } while (this._thumbAgain);
    } finally {
      this._thumbing = false;
    }
  }

  /** Drop an original's decoded media, unless it is being edited or sent (`done`: the job finishing now). */
  _release(o, done = null) {
    if (!o?.src || o.id === this._editing || this._queue.some((j) => j !== done && j.clip.originalId === o.id)) return;
    o.info = sourceInfo(o.src);
    releaseSource(o.src);
    o.src = null;
    for (const c of this._clipsOf(o)) Object.assign(c, { src: null, scaled: null });
  }

  async _drawClipThumb(c) {
    const canvas = this.shadowRoot.querySelector(`.clip[data-clip="${c.id}"] .cthumb`);
    if (!canvas || c.status === "busy" || this._original(c.originalId)?.needsCopy) return;
    try {
      await this._source(c);
      const frames = c.frames || await processItem({ ...c, opts: { ...c.opts, end: (c.opts.start || 0) + 0.01 } }, this.size, 1);
      c.thumb = frames[0].data;
      drawLed(canvas, c.thumb);
    } catch (_err) { /* thumbnail is best effort */ }
  }

  /**
   * Add files in two steps: every row (name, size, folder, a first clip)
   * appears and reaches Home Assistant at once, then the files are read one
   * at a time in the background. Reading dozens of videos in one go made
   * phones run out of memory and reload the page.
   */
  async _addFiles(files) {
    const failed = [];
    const folder = this.state.filter?.folder === TRASH ? "" : this.state.filter?.folder || "";
    let created = Date.now();
    for (const file of files) {
      // The same file as an original imported elsewhere: link it instead of duplicating.
      const twin = this.originals.find((o) => o.missing && o.name === file.name && (!o.size || o.size === file.size));
      if (twin) {
        Object.assign(twin, { status: "busy", progress: "en attente…" });
        this._imports.push({ original: twin, file, relink: true });
        continue;
      }
      if (!isVideo(file) && !isImage(file)) {
        failed.push(`${file.name} : format non pris en charge (${file.type || "inconnu"})`);
        continue;
      }
      const original = {
        id: newId("o"), file, name: file.name, size: file.size, device: deviceName(), created: created++, folder,
        src: null, status: "busy", progress: "en attente…",
      };
      this.originals.push(original);
      this._newClip(original);
      this._sync("put_originals", this._originalRecord(original));
      this._imports.push({ original, file });
    }
    if (failed.length) this._onTransfer({ state: "error", what: "Import impossible", message: failed.join(" · ") });
    if (this.state.tab === "workspace") this._renderWorkspace();
    await this._runImports();
  }

  /** Read the added files one by one: decode, keep a copy, draw the thumbnails, free the memory. */
  async _runImports() {
    if (this._importing) return;
    this._importing = true;
    try {
      while (this._imports.length) {
        const { original, file, relink } = this._imports.shift();
        if (!this.originals.includes(original)) continue;  // put in the trash meanwhile
        const left = this._imports.length;
        this._importsDone = (this._importsDone || 0) + 1;
        const total = this._importsDone + left;
        this._setWork(`⇩ Import ${this._importsDone}/${total} : ${original.name}`, (this._importsDone - 1) / total);
        original.progress = `lecture…${left ? ` (${left} autre${left > 1 ? "s" : ""} en attente)` : ""}`;
        this._updateOriginalRow(original);
        try {
          await this._loadFile(original, file);
        } catch (err) {
          Object.assign(original, { status: "error", error: err.message || String(err), src: null });
          if (relink) original.file = null;
          this._updateOriginalRow(original);
          this._onTransfer({ state: "error", what: "Import impossible", message: `${file.name} : ${original.error}` });
          continue;
        }
        if (relink) Object.assign(original, { missing: false, size: file.size });
        original.info = sourceInfo(original.src);
        await this._persistOriginal(original);
        if (this.state.tab === "workspace") {
          this._updateOriginalRow(original);
          await this._drawOriginalThumb(original);
          for (const c of this._clipsOf(original)) {
            Object.assign(c, { src: original.src, frames: null });
            await this._drawClipThumb(c);
            this._updateClipRow(c);
          }
        }
        original.status = "ready";
        this._release(original);
        this._updateOriginalRow(original);
      }
    } finally {
      this._importing = false;
      this._importsDone = 0;
      this._setWork(null);
    }
  }

  async _addOriginal(file, folder = this.state.filter?.folder === TRASH ? "" : this.state.filter?.folder || "") {
    if (!isVideo(file) && !isImage(file)) throw new Error(`format non pris en charge (${file.type || file.name})`);
    const original = {
      id: newId("o"), file, name: file.name, size: file.size, device: deviceName(), created: Date.now(), folder,
      src: null, status: "busy", progress: "lecture…",
    };
    this.originals.push(original);
    if (this.state.tab === "workspace") this._renderWorkspace();
    try {
      await this._loadFile(original, file);
    } catch (err) {
      this.originals = this.originals.filter((x) => x !== original);
      throw err;
    }
    // First clip while the decoded source is surely there: once the original
    // is ready, drawing thumbnails may release it to save memory.
    this._newClip(original);
    original.status = "ready";
    await this._persistOriginal(original);
    return original;
  }

  async _loadFile(original, file) {
    original.file = file;
    try {
      original.src = await loadSource(file);
    } catch (err) {
      if (!isVideo(file)) throw err;
      // The browser cannot decode this video (AVI, WMV, old codecs...):
      // ffmpeg.wasm makes a light copy it can play, without leaving the browser.
      original.file = await browserWorkingCopy(file, (status) => {
        original.progress = status;
        this._updateOriginalRow(original);
      });
      original.src = await loadSource(original.file);
    }
  }

  /** Attach this device's copy of an original imported on another one. */
  async _relink(original, file) {
    if (original.size && file.size !== original.size
        && !confirm(`« ${file.name} » ne fait pas la même taille que l'original (${kb(file.size)} au lieu de ${kb(original.size)}). Le relier quand même ?`)) return;
    Object.assign(original, { status: "busy", progress: "lecture…" });
    this._updateOriginalRow(original);
    try {
      // Only attached: a video is read when shown, and converted (if this browser
      // needs it) when first used, so relinking many at once stays quick.
      Object.assign(original, { file, src: isVideo(file) ? null : await loadSource(file), needsCopy: false });
    } catch (err) {
      Object.assign(original, { status: "ready", file: null, src: null });
      this._updateOriginalRow(original);
      throw err;
    }
    Object.assign(original, { missing: false, status: "ready", size: file.size });
    await this._persistOriginal(original);
    for (const c of this._clipsOf(original)) Object.assign(c, { src: original.src, frames: null });
    if (this.state.tab === "workspace") this._renderWorkspace();
  }

  _newClip(original, from = null) {
    const count = this._clipsOf(original).length;
    const clip = {
      id: newId("c"), originalId: original.id, created: Date.now(), status: "ready", src: original.src,
      title: from ? `${from.title} (copie)` : `${original.name.replace(/\.[^.]+$/, "")}${count ? ` #${count + 1}` : ""}`,
      opts: from ? structuredClone(from.opts) : { ...DEFAULTS, crop: (original.src || original.info) ? centeredSquare((original.src || original.info).width, (original.src || original.info).height) : null },
      pushed: null, dirty: false, frames: null, result: null,
    };
    this.clips.push(clip);
    this._persistClip(clip);
    return clip;
  }

  async _workspaceAction(ev) {
    const trashButton = ev.target.closest("button[data-tact]");
    if (trashButton) {
      this._trashAction(trashButton);
      return;
    }
    const button = ev.target.closest("button[data-act]");
    if (!button) return;
    const act = button.dataset.act;
    const original = this._original(button.closest(".orig")?.dataset.orig);
    const clip = this.clips.find((c) => c.id === button.closest(".clip")?.dataset.clip);
    try {
      if (act === "pick") {
        if (this._wselected.has(original.id)) this._wselected.delete(original.id);
        else this._wselected.add(original.id);
        this._renderTree();
      } else if (act === "folder") {
        this._inlineInput(button, { value: original.folder || "", placeholder: "Dossier (vide = aucun)", list: this._allFolders() },
          (folder) => {
            if (folder !== null && folder !== (original.folder || "")) {
              Object.assign(original, { folder, updated: Date.now() });
              this._saveOriginalMeta(original);
            }
            this._renderTree();
          });
      } else if (act === "fold") {
        this._collapsed ||= new Set();
        if (this._collapsed.has(original.id)) this._collapsed.delete(original.id);
        else this._collapsed.add(original.id);
        this._renderTree();
      } else if (act === "relink") {
        const found = await this._findSource({ name: original.name, size: original.size }, true);
        if (found && (!original.size || found.size === original.size)) {
          await this._relink(original, found);
          return;
        }
        const input = Object.assign(document.createElement("input"), { type: "file" });
        input.onchange = () => {
          if (input.files[0]) this._relink(original, input.files[0]).catch((err) => alert(err.message || err));
        };
        input.click();
      } else if (act === "convert") {
        await this._ensureSource(original);
        this._release(original);
        this._renderTree();
        this._drawThumbs();
      } else if (act === "newclip") {
        await this._ensureSource(original);
        await this._openEditor(this._newClip(original));
      } else if (act === "delorig") {
        this._trashOriginal(original);
        this._renderTree();
      } else if (act === "edit") {
        await this._openEditor(clip);
      } else if (act === "push") {
        await this._push(clip, false);
      } else if (act === "show") {
        if (!clip.pushed || clip.dirty) await this._push(clip, true);
        else await this._display(clip.pushed);
      } else if (act === "dup") {
        this._newClip(original, clip);
        this._renderTree();
      } else if (act === "delclip") {
        this._trashClip(clip);
        this._renderTree();
      }
    } catch (err) {
      alert(err.message || err);
    }
  }

  /** Quick speed change from the list: re-send to update the GIF. */
  _workspaceChange(ev) {
    if (ev.target.dataset.act !== "speed") return;
    const clip = this.clips.find((c) => c.id === ev.target.closest(".clip").dataset.clip);
    clip.opts.speed = Number(ev.target.value);
    clip.frames = null;
    clip.result = null;
    if (clip.pushed) clip.dirty = true;
    this._persistClip(clip);
    this._updateClipRow(clip);
  }

  /** GIFs already on the Pi whose source is on this device and that are not « Équilibré » yet. */
  _redoable() {
    return this.clips.filter((c) => c.pushed && this._original(c.originalId)?.file && renderOf(c.opts) !== "equilibre");
  }

  /** Redo the gallery's GIFs from their sources with the « Équilibré » render (each replaces its old GIF). */
  _redoAll(button) {
    const render = RENDERS.find((r) => r.key === "equilibre");
    const clips = this._redoable();
    const elsewhere = this.clips.filter((c) => c.pushed && !this._original(c.originalId)?.file).length;
    if (!clips.length) {
      this._onTransfer({ state: "saved", message: `Rien à refaire ici${elsewhere ? ` (${elsewhere} GIF ont leur source sur un autre appareil : relie-la d'abord)` : ""}.` });
      return;
    }
    if (!this._armed(button, `Refaire ${clips.length} GIF ?`)) return;
    for (const clip of clips) {
      for (const key of RENDER_KEYS) clip.opts[key] = render[key];
      Object.assign(clip, { dirty: true, frames: null, result: null });
      this._persistClip(clip);
      this._push(clip, false);  // the queue takes them one at a time, replacing each old GIF
    }
    if (elsewhere) {
      this._onTransfer({ state: "saved", message: `${clips.length} GIF en file d'attente ; ${elsewhere} autres ont leur source sur un autre appareil (à relier pour les refaire).` });
    }
    this._renderTree();
  }

  async _pushAll() {
    await Promise.all(this.clips.filter((c) => !c.pushed || c.dirty).map((c) => this._push(c, false)));
    if (this.state.tab === "workspace") this._renderWorkspace();
  }

  /** Encode a clip on Home Assistant; with save it also goes to the gallery. */
  async _encode(clip, { save, display = false, onProgress = null }) {
    await this._source(clip);
    const cached = Boolean(clip.frames);
    let started = performance.now();
    const frames = clip.frames || await processItem(clip, this.size, this.info.max_frames, (i, n) => {
      clip.progress = `extraction ${i}/${n}`;
      this._updateClipRow(clip);
      if (onProgress) onProgress(`extraction ${i}/${n}`, 0.4 * (i / n));
    });
    clip.frames = frames;
    const extractMs = Math.round(performance.now() - started);
    const form = new FormData();
    started = performance.now();
    const sheet = await frameSheet(frames);
    const sheetMs = Math.round(performance.now() - started);
    form.append("sheet", sheet.blob, "frames.png");
    const meta = {
      durations: frames.map((f) => f.ms), size: sheet.size, columns: sheet.columns,
      options: { dither: clip.opts.dither, boomerang: clip.opts.boomerang, merge_similar: clip.opts.merge_similar !== false,
        fuzz: clip.opts.fuzz ?? DEFAULTS.fuzz, colors: clip.opts.colors || undefined, max_fps: clip.opts.max_fps || undefined },
      entry_id: this._entryId || undefined,
      // A preview: the Pi drops this editor's older ones still waiting.
      preview: save ? undefined : clip.id,
      // For the 📜 log: what was cut from what, and how long the browser took.
      log: save ? {
        clip: clip.title, original: this._sourceInfo(this._original(clip.originalId)),
        settings: this._clipSettings(clip.opts), render: renderOf(clip.opts),
        extracted: { frames: frames.length, length_ms: frames.reduce((n, f) => n + f.ms, 0), cached, ms: extractMs },
        seconds: this._clipSeconds(clip, frames),
        sheet: { bytes: sheet.blob.size, columns: sheet.columns, ms: sheetMs },
      } : undefined,
    };
    if (save) {
      Object.assign(meta, {
        title: clip.title, display, replace: clip.pushed || undefined,
        clip: clip.id, source: this._original(clip.originalId)?.name, device: deviceName(),
        folder: this._original(clip.originalId)?.folder || "",
      });
    }
    form.append("meta", JSON.stringify(meta));
    const posted = performance.now();
    let uploaded = null;
    const logged = (body) => {
      if (!save) return body;
      const total = Math.round(performance.now() - posted);
      const upload = uploaded === null ? null : Math.round(uploaded - posted);
      this._log("browser", `${clip.title} : planche de ${frames.length} images (${kb(sheet.blob.size)}) envoyée au Pi`
        + `${upload === null ? "" : ` en ${upload} ms`}, GIF de ${kb(body.size_bytes)} reçu après ${total} ms`,
      { clip: clip.title, upload_ms: upload, round_trip_ms: total, sheet_bytes: sheet.blob.size, gif_bytes: body.size_bytes,
        frames_out: body.frames, file: body.file });
      return body;
    };
    try {
      if (onProgress && this._hass.auth) {
        const { ok, status, body } = await this._postForm(form, (f) => {
          if (f < 1) onProgress(`envoi au Pi ${Math.round(f * 100)} %`, 0.4 + 0.45 * f);
          else {
            uploaded ??= performance.now();
            onProgress("le Pi fabrique le GIF (palette, allègement)…", null);
          }
        });
        if (!ok) throw new Error(body.message || `Erreur ${status}`);
        return logged(body);
      }
      const response = await this._hass.fetchWithAuth(this.info.encode_url, { method: "POST", body: form });
      const body = await response.json();
      if (!response.ok) throw new Error(body.message || `Erreur ${response.status}`);
      return logged(body);
    } catch (err) {
      if (save) this._log("error", `${clip.title} : envoi au Pi échoué (${err.message || err})`, { clip: clip.title });
      throw err;
    }
  }

  /** What an original is, for the log: file, kind, size on screen, length. */
  _sourceInfo(original) {
    if (!original) return null;
    const src = original.src || {};
    const first = src.frames?.[0]?.bmp;
    return {
      name: original.name, bytes: original.size ?? original.file?.size ?? null, type: original.file?.type || null,
      working_copy: original.file && original.file.name !== original.name
        ? { name: original.file.name, bytes: original.file.size } : null,
      kind: src.kind || null, width: src.width || first?.width || null, height: src.height || first?.height || null,
      duration_s: src.duration ? Math.round(src.duration * 100) / 100 : null,
      frames: src.frames ? src.frames.length : null,
      frames_ms: src.frames ? src.frames.reduce((n, f) => n + f.ms, 0) : null,
    };
  }

  /**
   * The clip second by second, for the log: where the square sits in the
   * source (pixels) and how much of the screen changes (motion).
   */
  _clipSeconds(clip, frames) {
    const src = clip.src || {};
    const first = src.frames?.[0]?.bmp;
    const W = src.width || first?.width || 0;
    const H = src.height || first?.height || 0;
    const seconds = [];
    let changed = 0;
    let compared = 0;
    let second = 0;
    const flush = (t) => {
      const crop = cropAt(clip.opts, t);
      const [x, y, w, h] = crop || [0, 0, 1, 1];
      seconds.push({ t: Math.round(t * 10) / 10, crop: W ? [Math.round(x * W), Math.round(y * H), Math.round(w * W), Math.round(h * H)] : null,
        motion: compared ? Math.round((1000 * changed) / compared) / 10 : 0 });
      changed = 0;
      compared = 0;
    };
    for (let i = 0; i < frames.length; i++) {
      const t = frames[i].t ?? 0;
      if (seconds.length === 0 && i === 0) second = Math.floor(t);
      if (Math.floor(t) > second) { flush(second); second = Math.floor(t); }
      if (i) {
        const a = frames[i - 1].data.data;
        const b = frames[i].data.data;
        for (let p = 0; p < b.length; p += 4) {
          compared += 1;
          if (Math.abs(a[p] - b[p]) + Math.abs(a[p + 1] - b[p + 1]) + Math.abs(a[p + 2] - b[p + 2]) > 24) changed += 1;
        }
      }
    }
    if (frames.length) flush(second);
    return { source_size: W ? [W, H] : null, per_second: seconds };
  }

  /** A clip's settings without the follow-mode keyframes (summarised). */
  _clipSettings(opts) {
    const { track, zoom, ...rest } = opts || {};
    return { ...rest, track_points: Array.isArray(track) ? track.length : track ? 1 : 0,
      zoom_points: Array.isArray(zoom) ? zoom.length : zoom ? 1 : 0 };
  }

  _logSource(original, started, unreadable = null) {
    const info = this._sourceInfo(original);
    const ms = Math.round(performance.now() - started);
    this._log("source", `Original ${info.name} lu : ${info.kind}, ${info.width}×${info.height}`
      + `${info.duration_s ? `, ${info.duration_s} s` : ""}${info.frames ? `, ${info.frames} images` : ""}, ${kb(info.bytes || 0)}`
      + `${unreadable ? ` (illisible tel quel : copie de travail ${kb(original.file.size)})` : ""} en ${ms} ms`,
    { ...info, ms, unreadable });
  }

  // ---------------------------------------------------------------- log

  /** Add a browser entry to the Pi's log (sent in small batches). */
  _log(kind, msg, data) {
    (this._logOut ||= []).push({ kind, msg: `${msg} · ${deviceName()}`.slice(0, 500), data });
    clearTimeout(this._logTimer);
    this._logTimer = setTimeout(() => {
      const entries = this._logOut.splice(0, 100);
      if (entries.length) this._ws({ type: "idotmatrix/studio/log_add", entries }).catch(() => {});
    }, 500);
  }

  _onLog(entry) {
    if (!this._logEntries) return;
    this._logEntries.push(entry);
    if (this.state.tab === "log") this._drawLog();
  }

  async _renderLog() {
    const main = this._main();
    main.innerHTML = `<div class="logbar">
        <select id="lkind" title="Afficher">
          <option value="">Tout</option><option value="encode">Encodages</option><option value="preview">Aperçus de l'éditeur</option><option value="transfer,display">Envois au cadre</option>
          <option value="routine">Routines</option><option value="source,browser">Navigateur</option>
          <option value="warning,error">Alertes et erreurs</option></select>
        <span class="grow muted small" id="lcount"></span>
        <button class="act ghost small" id="lcopy" title="Copier tout le journal pour le coller dans une conversation">📋 Copier</button>
        <button class="act ghost small" id="lsave" title="Enregistrer le journal dans un fichier texte">💾 Télécharger</button>
        <button class="act ghost small" id="lclear" title="Effacer le journal (toucher deux fois)">🗑 Vider</button></div>
      <p class="muted small">Tout ce que le Pi et les navigateurs ont fait : chaque GIF fabriqué (taille image par image, original, réglages),
        chaque envoi au cadre (temps par paquet), les routines et les alertes. Les 3000 dernières lignes sont gardées.</p>
      <div id="log"><p class="muted">…</p></div>`;
    const $ = (sel) => main.querySelector(sel);
    $("#lkind").value = this._logFilter || "";
    $("#lkind").onchange = (ev) => { this._logFilter = ev.target.value; this._drawLog(); };
    $("#lcopy").onclick = () => this._copyLog($("#lcopy"));
    $("#lsave").onclick = () => {
      const link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([this._logText()], { type: "text/plain" }));
      link.download = `pixel-studio-journal-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}.txt`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    };
    $("#lclear").onclick = async (ev) => {
      if (!this._armed(ev.currentTarget, "Vider ?")) return;
      await this._ws({ type: "idotmatrix/studio/log_clear" });
      this._logEntries = [];
      this._drawLog();
    };
    try {
      this._logEntries = (await this._ws({ type: "idotmatrix/studio/log" })).entries;
    } catch (err) {
      $("#log").innerHTML = `<p class="error">${esc(err.message || err)}</p>`;
      return;
    }
    this._drawLog();
  }

  _drawLog() {
    const list = this._main().querySelector("#log");
    if (!list) return;
    const kinds = (this._logFilter || "").split(",").filter(Boolean);
    const shown = (this._logEntries || []).filter((e) => !kinds.length || kinds.includes(e.kind));
    this._main().querySelector("#lcount").textContent = `${shown.length} ligne${shown.length > 1 ? "s" : ""}`;
    const icon = { pi: "🍓", browser: "💻" };
    list.innerHTML = shown.slice(-400).reverse().map((e) => `<details class="logrow ${esc(e.kind)}">
        <summary><span class="when">${new Date(e.t * 1000).toLocaleString()}</span>
          <span title="${e.source === "browser" ? "Navigateur" : "Pi"}">${icon[e.source] || "·"}</span>
          <span class="kind pill">${esc(e.kind)}</span><span class="grow">${esc(e.msg)}</span></summary>
        ${e.data ? `<pre>${esc(JSON.stringify(e.data, null, 1))}</pre>` : ""}</details>`).join("")
      || `<p class="muted">Rien pour l'instant.</p>`;
  }

  /** The whole log as text: one entry per line, its details as JSON below it. */
  _logText() {
    const head = [`Journal Pixel Studio — ${new Date().toISOString()}`,
      `Navigateur : ${deviceName()} · ${navigator.userAgent}`, `Écran du cadre : ${this.size}×${this.size}`, ""];
    return head.concat((this._logEntries || []).map((e) => `${new Date(e.t * 1000).toISOString()} [${e.source}] ${e.kind}: ${e.msg}`
      + (e.data ? `\n  ${JSON.stringify(e.data)}` : ""))).join("\n");
  }

  async _copyLog(button) {
    const text = this._logText();
    let done = false;
    try {
      await navigator.clipboard.writeText(text);
      done = true;
    } catch (_err) {
      // Home Assistant over plain http has no clipboard API: select and copy instead.
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      this.shadowRoot.appendChild(area);
      area.select();
      try { done = document.execCommand("copy"); } catch (_e) { done = false; }
      area.remove();
    }
    button.textContent = done ? "✓ Copié" : "Copie impossible : utilise Télécharger";
    setTimeout(() => { button.textContent = "📋 Copier"; }, 2500);
  }

  /** POST the frames with upload progress (fetch cannot report it). */
  async _postForm(form, onUpload) {
    const auth = this._hass.auth;
    if (auth.expired) await auth.refreshAccessToken();
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      this._xhr = xhr;
      xhr.onabort = () => reject(new Error("annulé"));
      xhr.open("POST", this.info.encode_url);
      xhr.setRequestHeader("Authorization", `Bearer ${auth.data.access_token}`);
      xhr.responseType = "json";
      xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) onUpload(ev.loaded / ev.total); };
      xhr.upload.onload = () => onUpload(1);
      xhr.onload = () => resolve({ ok: xhr.status < 300, status: xhr.status, body: xhr.response || {} });
      xhr.onerror = () => reject(new Error("Le Pi ne répond pas"));
      xhr.send(form);
    });
  }

  /**
   * Queue a clip for the Pi, which encodes one GIF at a time. Resolves with
   * its success once its turn has run; queuing it twice keeps one turn.
   */
  _push(clip, display) {
    const queued = this._queue.find((j) => j.clip === clip);
    if (queued) {
      queued.display ||= display;
      return queued.done;
    }
    const job = { clip, display, phase: "en attente", frac: 0 };
    job.done = new Promise((resolve) => { job.resolve = resolve; });
    this._queue.push(job);
    clip.status = "busy";
    clip.progress = "en attente…";
    this._updateClipRow(clip);
    this._renderJobs();
    if (!this._queueRunning) this._runQueue();
    return job.done;
  }

  async _runQueue() {
    this._queueRunning = true;
    while (this._queue.length) {
      const job = this._queue[0];
      job.resolve(await this._pushNow(job));
      this._queue.shift();
      this._renderJobs();
    }
    this._queueRunning = false;
  }

  /** What the browser itself is busy with (reading imports, extracting a video), shown in the status bar. */
  _setWork(label, frac = null) {
    const el = this.shadowRoot.querySelector(".status .work");
    if (!el) return;
    if (!label) { el.innerHTML = ""; return; }
    el.innerHTML = `<div class="tline"><span class="ellipsis">${esc(label)}</span>
      <progress max="1" ${frac === null ? "" : `value="${frac}"`}></progress></div>`;
  }

  _renderJobs() {
    if (this._jobsFrame) return;
    this._jobsFrame = setTimeout(() => {
      this._jobsFrame = null;
      const el = this.shadowRoot.querySelector(".status .jobs");
      if (!el) return;
      const [job, ...waiting] = this._queue;
      if (!job) { el.innerHTML = ""; return; }
      const value = job.frac === null ? "" : `value="${job.frac}"`;
      el.innerHTML = `<div class="tline" title="${esc(this._queue.map((j) => j.clip.title).join("\n"))}">
        <span class="ellipsis">⇧ ${esc(job.clip.title)}</span><progress max="1" ${value}></progress>
        <span class="small">${job.phase}${waiting.length ? ` · +${waiting.length} en attente` : ""}</span></div>`;
    }, 60);
  }

  async _pushNow(job) {
    const { clip, display } = job;
    clip.status = "busy";
    clip.progress = "préparation…";
    this._updateClipRow(clip);
    const onProgress = (phase, frac) => {
      if (job.cancelled) throw new Error("annulé");
      Object.assign(job, { phase, frac });
      clip.progress = phase;
      this._updateClipRow(clip);
      this._renderJobs();
    };
    onProgress("préparation…", 0);
    try {
      clip.result = await this._encode(clip, { save: true, display, onProgress });
      Object.assign(clip, { pushed: clip.result.file, dirty: false, sizeBytes: clip.result.size_bytes });
      this._persistClip(clip);
      this._onTransfer(display
        ? { file: clip.result.file, state: "started" }
        : { file: clip.result.file, state: "saved", message: `« ${clip.title} » est dans la galerie du Pi (${kb(clip.result.size_bytes)}). ▶ pour l'afficher.` });
      await this._galleryItems().catch(() => {});
      clip.status = "ready";
    } catch (err) {
      clip.status = "error";
      clip.error = err.message || String(err);
      this._onTransfer({ file: clip.title, state: "error", message: `${clip.title} : ${clip.error}` });
    } finally {
      if (clip.status === "busy") clip.status = "ready";  // never leave a row stuck
      clip.progress = null;
      this._updateClipRow(clip);
      this._release(this._original(clip.originalId), job);
    }
    return clip.status !== "error";
  }

  // ---------------------------------------------------------------- editor

  async _openEditor(w) {
    this._editing = w.originalId;  // keeps its decoded source while it is open
    this._pointing = false;
    try {
      await this._source(w);
    } catch (err) {
      this._editing = null;
      alert(err.message || err);
      return;
    }
    // Clips made while their file was still waiting to be read have no crop yet.
    if (!w.opts.crop) w.opts.crop = centeredSquare(w.src.width, w.src.height);
    // The clip as it was, for « Envoyer en nouveau clip » to put back.
    this._opened = { opts: structuredClone(w.opts), title: w.title, dirty: !!w.dirty };
    this.current = w;
    this._show("editor");
  }

  _renderEditor() {
    const w = this.current;
    this._view = null;
    const o = w.opts;
    const main = this._main();
    this.shadowRoot.querySelectorAll("nav button").forEach((b) => b.classList.toggle("on", b.dataset.tab === "workspace"));
    const sliders = SLIDERS.map(([key, label, min, max, step]) => `
      <label class="slider" title="${HINTS[key] || ""}">${label}<input type="range" data-key="${key}" min="${min}" max="${max}" step="${step}" value="${o[key]}">
      <span data-out="${key}">${o[key]}</span></label>`).join("");
    const timed = w.src.kind !== "image";
    const video = w.src.kind === "video";
    main.innerHTML = `<div class="editor">
      <div class="card">
        ${timed ? `<div class="stagebar"><button class="act" id="playTop" title="Lecture / pause">⏸</button>
          <button class="act ghost bounce" title="Lecture en boucle ou en aller-retour (boomerang)"></button>
          <span class="muted small">La barre de temps et les réglages sont plus bas</span></div>` : ""}
        <div class="stage"></div>
        <div class="row">
          <select id="fit">
            <option value="crop">Recadrer (carré)</option>
            <option value="fit">Image entière (bandes noires)</option>
            <option value="stretch">Étirer</option>
          </select>
          <span class="muted" id="hint">Déplace le carré ; la poignée ronde ou la molette le redimensionne (en suivi : un zoom à ce moment).</span>
        </div>
        ${timed ? `<div class="row" id="followRow">
          <label title="Le carré change de position au fil du temps pour suivre le sujet"><input type="checkbox" id="follow" ${o.follow ? "checked" : ""}> Suivre</label>
          <label title="Lance la vidéo et déplace ou redimensionne le carré pendant qu'elle joue : chaque instant traversé retient sa position et sa taille"><input type="checkbox" id="manualFollow" ${o.manual ? "checked" : ""}> ✋ Suivi perso</label>
          <button class="act ghost small" id="autoTrack" title="Repère ce qui bouge par rapport au décor et cale le carré dessus">🎯 Suivi auto</button>
          <button class="act ghost small" id="pinPoint" title="Clique ensuite sur le sujet dans l'image, à un ou plusieurs moments : il est suivi d'une image à l'autre">📍 Pointer</button>
          <button class="act ghost small" id="clearKeys" title="Effacer toutes les positions du suivi">Effacer</button>
          <span class="muted small" id="keysInfo"></span>
        </div>` : ""}
        ${timed ? `<div class="overview" id="overview" title="Vue d'ensemble : clique ou glisse pour déplacer le zoom">
            <div class="ov-sel"></div><div class="ov-view"></div><div class="ov-head"></div></div>
          <div class="trim" id="trim" title="Tire les poignées pour choisir le début et la fin. Molette : zoom, Maj + molette : défiler">
            <div class="sel"></div><div class="head"></div>
            <div class="h" data-edge="start"></div><div class="h" data-edge="end"></div></div>
          <div class="row muted">
            <span>Vue <b id="viewOut"></b></span><span class="grow"></span>
            <button class="act ghost" id="zoomOut" title="Dézoomer">🔍−</button>
            <button class="act ghost" id="zoomIn" title="Zoomer autour de la tête de lecture">🔍+</button>
            <button class="act ghost" id="zoomSel" title="Cadrer la vue sur la partie sélectionnée">Sélection</button>
            <button class="act ghost" id="zoomAll" title="Voir toute la vidéo">Tout</button>
          </div>
          <div class="row muted">
            <span>Début <b id="startOut"></b></span><span>Fin <b id="endOut"></b></span><span>Durée <b id="lenOut"></b></span>
            <span class="grow"></span>
            <button class="act ghost" id="play" title="Lecture / pause (un clic sur la barre se place à cet instant)">⏸</button>
            <button class="act ghost bounce" title="Lecture en boucle ou en aller-retour (boomerang)"></button>
            <button class="act ghost" id="setStart" title="Début à la position de la tête de lecture">⇤ ici</button>
            <button class="act ghost" id="setEnd" title="Fin à la position de la tête de lecture">ici ⇥</button>
            ${video ? `            <label>Images/s <input type="number" id="fps" min="1" max="30" value="${o.fps}"></label>` : ""}
          </div>` : ""}
      </div>
      <div class="card">
        <canvas id="ledMini" class="ledmini" width="128" height="128" title="Rendu sur le cadre (toucher pour l'aperçu complet)"></canvas>
        <div class="preview"><canvas id="led" width="320" height="320"></canvas>
          <div class="muted" id="previewMode"></div>
          <div class="row" style="justify-content:center"><button class="act ghost" id="sendStill"
            title="Affiche tout de suite cette image fixe sur le cadre">📷 Envoyer cette image au cadre</button></div>
          <div class="stats muted" id="stats"></div><div class="stats muted" id="final"></div></div>
        <div class="row"><input type="text" id="title" class="grow" value="${esc(w.title)}" placeholder="Nom"></div>
        <div class="row">
          <button class="act ghost" id="back">← Atelier</button>
          <button class="act ghost" id="delClip" title="Met ce clip à la corbeille de l'Atelier (toucher deux fois, restaurable) ; son GIF reste dans la galerie">🗑 Clip</button>
          <button class="act ghost" id="delOrig" title="Met l'original et tous ses clips à la corbeille de l'Atelier (toucher deux fois, restaurable) ; leurs GIF restent dans la galerie">🗑 Original</button>
          <span class="grow"></span>
          <button class="act ghost" id="saveNew" title="Ton édition devient un nouveau clip, avec son propre GIF ; ce clip-ci revient comme à l'ouverture">＋ Envoyer en nouveau clip</button>
          <button class="act ghost" id="save" title="Envoie ce clip au Pi et remplace son GIF">Pousser vers le Pi</button>
          <button class="act" id="saveShow">Pousser et afficher</button>
        </div>
        <p class="error" id="err"></p>
      </div>
      <div class="card">
        <div class="controls">${sliders}
          <div class="row"><label>Lecture <select id="loop">
              <option value="loop">En boucle</option><option value="boomerang">Boomerang (aller-retour)</option>
            </select></label>
            <label title="Mélange des points de couleurs voisines pour imiter les nuances manquantes. Dégradés plus doux, mais grain qui scintille sur les LED et fichier plus lourd"><input type="checkbox" id="dither" ${o.dither ? "checked" : ""}>Tramage</label>
            <label title="Une image presque identique à la précédente (quelques pixels qui bougent à peine) est fusionnée avec elle : même durée, même rendu sur les LED, mais un GIF plus léger et plus rapide à envoyer"><input type="checkbox" id="mergeSimilar" ${o.merge_similar !== false ? "checked" : ""}>Fusionner les images quasi identiques</label>
            <label title="Chaque image n'envoie que ce qui change. Allègement : un pixel dont la couleur bouge à peine garde l'ancienne (le bruit de la vidéo). Plus il est fort, plus le GIF est léger, mais un objet qui bouge sur un fond sombre ou dégradé peut laisser des traînées ; « aucun » est exact">Allègement
              <select id="fuzz">${FUZZ_LEVELS.map(([v, label]) => `<option value="${v}" ${v === (o.fuzz ?? DEFAULTS.fuzz) ? "selected" : ""}>${label}</option>`).join("")}</select></label>
            <label title="Nombre de couleurs du GIF : moins de couleurs, fichier plus léger, dégradés en marches">Couleurs
              <select id="colors">${COLOR_LEVELS.map((v) => `<option value="${v}" ${v === (o.colors ?? 256) ? "selected" : ""}>${v}</option>`).join("")}</select></label>
            <label title="Images par seconde au plus dans le GIF : moins d'images, envoi plus rapide, mouvement moins fluide (la durée ne change pas)">Cadence max
              <select id="maxFps">${FPS_CAPS.map(([v, label]) => `<option value="${v}" ${v === (o.max_fps || 0) ? "selected" : ""}>${label}</option>`).join("")}</select></label>
          </div>
          <div class="row"><label title="Réglages de rendu tout faits">Rendu
              <select id="render">${RENDERS.map((r) => `<option value="${r.key}" title="${esc(r.hint)}">${r.label}</option>`).join("")}
                <option value="custom">Personnalisé</option></select></label>
            <span class="muted small grow" id="renderHint"></span>
            <button class="act ghost" id="defaults" title="Remet vitesse, couleurs, netteté, taille max, lecture et tramage par défaut (le recadrage et le découpage restent)">Réglages par défaut</button>
            <label title="Montre l'image en cours sur le vrai cadre quand tu arrêtes de modifier (quelques secondes de délai)">
              <input type="checkbox" id="live" ${this._live ? "checked" : ""}>En direct sur le cadre</label></div>
        </div>
      </div></div>`;

    const stage = main.querySelector(".stage");
    const mini = main.querySelector("#ledMini");
    const led = main.querySelector("#led");
    mini.onclick = () => led.scrollIntoView({ behavior: "smooth", block: "center" });
    if (typeof IntersectionObserver !== "undefined") {
      // The pinned copy only while the real preview is off screen.
      new IntersectionObserver(([entry]) => {
        mini.hidden = entry.isIntersecting;
        const still = !mini.hidden && this._currentStill();
        if (still) drawLed(mini, still);  // at once, even while paused
      }).observe(led);
    }
    const animated = w.src.kind === "animated";
    // Animations play on a canvas so the chosen speed shows on the source too.
    // The source follows the preview's clock (see _showFrame), so both
    // sides always show the same moment.
    const media = document.createElement(video ? "video" : animated ? "canvas" : "img");
    if (video) {
      Object.assign(media, { muted: true, playsInline: true, preload: "auto", src: w.src.url });
      media.addEventListener("loadedmetadata", () => this._setupCrop(stage, media), { once: true });
    } else if (animated) {
      Object.assign(media, { width: w.src.width, height: w.src.height });
      media.getContext("2d").drawImage(w.src.frames[0].bmp, 0, 0);
    } else {
      media.addEventListener("load", () => this._setupCrop(stage, media), { once: true });
      media.src = w.src.url;
    }
    stage.appendChild(media);
    this._media = media;
    this._cropBox = null;
    if (animated) this._setupCrop(stage, media);

    const fit = main.querySelector("#fit");
    fit.value = o.fit;
    fit.onchange = () => { o.fit = fit.value; this._updateCropVisibility(); this._changed(); };
    main.querySelectorAll("input[type=range]").forEach((input) => {
      input.oninput = () => {
        o[input.dataset.key] = Number(input.value);
        main.querySelector(`[data-out="${input.dataset.key}"]`).textContent = input.value;
        this._changed("tone");
      };
    });
    const loop = main.querySelector("#loop");
    // The menu and the buttons by the play buttons show and set the same thing.
    const showLoop = () => {
      loop.value = o.boomerang ? "boomerang" : "loop";
      for (const b of main.querySelectorAll(".bounce")) b.textContent = o.boomerang ? "⇄ Boomerang" : "↻ Boucle";
    };
    showLoop();
    loop.onchange = () => { o.boomerang = loop.value === "boomerang"; showLoop(); this._changed("tone"); };
    for (const b of main.querySelectorAll(".bounce")) {
      b.onclick = () => { o.boomerang = !o.boomerang; showLoop(); this._changed("tone"); };
    }
    main.querySelector("#dither").onchange = (ev) => { o.dither = ev.target.checked; this._changed("budget"); showRender(); };
    main.querySelector("#mergeSimilar").onchange = (ev) => { o.merge_similar = ev.target.checked; this._changed("budget"); showRender(); };
    main.querySelector("#fuzz").onchange = (ev) => { o.fuzz = Number(ev.target.value); this._changed("budget"); showRender(); };
    main.querySelector("#colors").onchange = (ev) => { o.colors = Number(ev.target.value); this._changed("budget"); showRender(); };
    main.querySelector("#maxFps").onchange = (ev) => { o.max_fps = Number(ev.target.value) || 0; this._changed("budget"); showRender(); };
    const showRender = () => {
      const key = renderOf(o);
      main.querySelector("#render").value = key;
      main.querySelector("#renderHint").textContent = RENDERS.find((r) => r.key === key)?.hint || "";
    };
    showRender();
    main.querySelector("#render").onchange = (ev) => {
      const render = RENDERS.find((r) => r.key === ev.target.value);
      if (!render) return;
      for (const key of RENDER_KEYS) o[key] = render[key];
      main.querySelector("#fuzz").value = o.fuzz;
      main.querySelector("#colors").value = o.colors;
      main.querySelector("#maxFps").value = o.max_fps || 0;
      main.querySelector("#dither").checked = o.dither;
      main.querySelector("#mergeSimilar").checked = o.merge_similar;
      showRender();
      this._changed("budget");
    };
    main.querySelector("#defaults").onclick = () => {
      for (const [key] of SLIDERS) {
        o[key] = DEFAULTS[key];
        main.querySelector(`input[data-key="${key}"]`).value = o[key];
        main.querySelector(`[data-out="${key}"]`).textContent = o[key];
      }
      Object.assign(o, { boomerang: DEFAULTS.boomerang, dither: DEFAULTS.dither });
      showLoop();
      main.querySelector("#dither").checked = false;
      this._changed("tone");
    };
    main.querySelector("#live").onchange = (ev) => { this._live = ev.target.checked; this._scheduleLive(); };
    main.querySelector("#title").oninput = (ev) => { w.title = ev.target.value; this._persistClip(w); };
    const fps = main.querySelector("#fps");
    if (fps) fps.onchange = () => { o.fps = Number(fps.value) || DEFAULTS.fps; this._changed("time"); };
    if (timed) this._setupTrim(main.querySelector("#trim"), media);
    for (const [id, key] of [["setStart", "start"], ["setEnd", "end"]]) {
      const button = main.querySelector(`#${id}`);
      if (button) button.onclick = () => this._setEdge(key, this._headTime ?? 0, true);
    }
    for (const play of main.querySelectorAll("#play, #playTop")) play.onclick = () => this._togglePlay();
    const follow = main.querySelector("#follow");
    if (follow) {
      follow.onchange = () => {
        o.follow = follow.checked;
        if (o.follow && !o.track?.length) o.track = [{ t: this._headTime ?? 0, x: o.crop[0] + o.crop[2] / 2, y: o.crop[1] + o.crop[3] / 2 }];
        this._drawKeys();
        this._changed("crop");
      };
      const manual = main.querySelector("#manualFollow");
      manual.onchange = () => {
        o.manual = manual.checked;
        if (o.manual) {
          // A path of its own: start from the square as it is now, without the automatic points.
          const t = this._headTime ?? 0;
          const [x, y, cw, ch] = cropAt(o, t);
          Object.assign(o, { follow: true, trackAuto: false, anchors: [],
            track: [{ t, x: x + cw / 2, y: y + ch / 2 }], zoom: [{ t, s: cw / o.crop[2] }] });
          follow.checked = true;
        }
        this._drawKeys();
        this._changed("crop");
      };
      main.querySelector("#autoTrack").onclick = () => this._autoTrack();
      main.querySelector("#pinPoint").onclick = () => this._setPointing(!this._pointing);
      main.querySelector("#clearKeys").onclick = () => {
        o.track = [];
        o.zoom = [];
        o.anchors = [];
        o.follow = false;
        o.manual = false;
        follow.checked = false;
        main.querySelector("#manualFollow").checked = false;
        this._drawKeys();
        this._changed("crop");
      };
    }
    main.querySelector("#sendStill").onclick = () => this._sendStill();
    main.querySelector("#back").onclick = () => this._show("workspace");
    main.querySelector("#delClip").onclick = (ev) => this._editorDelete("clip", ev.currentTarget);
    main.querySelector("#delOrig").onclick = (ev) => this._editorDelete("original", ev.currentTarget);
    main.querySelector("#save").onclick = () => this._saveCurrent(false);
    main.querySelector("#saveNew").onclick = () => this._saveAsNewClip();
    main.querySelector("#saveShow").onclick = () => this._saveCurrent(true);
    this._renderTransfer();
    this._changed("time", true);
  }

  /** Clip window [start, end] in seconds, end defaulting like sourceFrames(). */
  _window() {
    const { src, opts: o } = this.current;
    const start = Math.max(0, o.start || 0);
    const fallback = src.kind === "video" ? VIDEO_SECONDS : ANIMATED_SECONDS;
    return [start, Math.min(src.duration, o.end ?? start + fallback)];
  }

  _setEdge(edge, seconds, commit) {
    const o = this.current.opts;
    const total = this.current.src.duration;
    const [start, end] = this._window();
    const t = Math.round(Math.min(total, Math.max(0, seconds)) * 10) / 10;
    if (edge === "start") o.start = Math.min(t, end - 0.1);
    else o.end = Math.max(t, start + 0.1);
    this._drawTrim();
    if (commit) this._changed("time");
  }

  /** Visible part of the timeline [from, to] in seconds (zoom). */
  _viewRange() {
    const total = this.current.src.duration || 1;
    if (!this._view) this._view = [0, total];
    return this._view;
  }

  _setView(from, to) {
    const total = this.current.src.duration || 1;
    const span = Math.min(total, Math.max(Math.min(1, total), to - from));
    const start = Math.min(Math.max(0, from), total - span);
    this._view = [start, start + span];
    this._drawTrim();
    this._moveHead(this._headTime ?? 0);
  }

  _zoom(factor, around) {
    const [from, to] = this._viewRange();
    const center = around ?? (from + to) / 2;
    this._setView(center - (center - from) * factor, center + (to - center) * factor);
  }

  _drawTrim() {
    const main = this._main();
    const trim = main.querySelector("#trim");
    if (!trim) return;
    const total = this.current.src.duration || 1;
    const [start, end] = this._window();
    const [from, to] = this._viewRange();
    const pct = (t) => `${((t - from) / (to - from)) * 100}%`;
    Object.assign(trim.querySelector(".sel").style, { left: pct(start), width: `${((end - start) / (to - from)) * 100}%` });
    trim.querySelector('[data-edge="start"]').style.left = pct(start);
    trim.querySelector('[data-edge="end"]').style.left = pct(end);
    const all = (t) => `${(t / total) * 100}%`;
    const overview = main.querySelector("#overview");
    Object.assign(overview.querySelector(".ov-sel").style, { left: all(start), width: all(end - start) });
    Object.assign(overview.querySelector(".ov-view").style, { left: all(from), width: all(to - from) });
    overview.style.display = to - from < total - 0.01 ? "" : "none";
    main.querySelector("#viewOut").textContent = `${clock(from)} → ${clock(to)}`;
    main.querySelector("#startOut").textContent = clock(start);
    main.querySelector("#endOut").textContent = clock(end);
    main.querySelector("#lenOut").textContent = `${(end - start).toFixed(1)} s / ${clock(total)}`;
    this._drawKeys();
  }

  /** Keyframe diamonds on the timeline (a dense automatic track shows as a band). */
  _drawKeys() {
    const main = this._main();
    const trim = main.querySelector("#trim");
    const info = main.querySelector("#keysInfo");
    if (!trim) return;
    trim.querySelectorAll(".key").forEach((k) => k.remove());
    const o = this.current.opts;
    const track = o.follow ? o.track || [] : [];
    const anchors = o.follow ? o.anchors || [] : [];
    if (info) {
      info.textContent = !o.follow ? "" : anchors.length
        ? `sujet suivi depuis ${anchors.length} point(s) · 📍 clique encore pour corriger`
        : o.trackAuto
          ? `suivi automatique (${track.length} positions) · déplace le carré pour corriger`
          : `${track.length} position(s) · mets en pause et déplace le carré pour en ajouter`;
      if (o.follow && o.zoom?.length) info.textContent += ` · zoom à ${o.zoom.length} moment(s)`;
    }
    const [from, to] = this._viewRange();
    for (const a of anchors) {
      const pin = document.createElement("div");
      pin.className = "key pin";
      pin.title = `point posé à ${clock(a.t)}`;
      pin.style.left = `${((a.t - from) / (to - from)) * 100}%`;
      trim.appendChild(pin);
    }
    if (o.trackAuto || track.length > 80) return;
    for (const k of track) {
      const dot = document.createElement("div");
      dot.className = "key";
      dot.title = `position à ${clock(k.t)}`;
      dot.style.left = `${((k.t - from) / (to - from)) * 100}%`;
      trim.appendChild(dot);
    }
  }

  /** 📍: the next clicks on the image set points on the subject, which is then followed. */
  _setPointing(on) {
    this._pointing = on;
    const button = this._main().querySelector("#pinPoint");
    if (button) {
      button.classList.toggle("ghost", !on);
      button.textContent = on ? "📍 Clique sur le sujet…" : "📍 Pointer";
    }
    this._main().querySelector(".stage")?.classList.toggle("pointing", on);
  }

  async _trackAnchors() {
    const w = this.current;
    const seq = (this._trackSeq = (this._trackSeq || 0) + 1);
    const info = this._main().querySelector("#keysInfo");
    if (info) info.textContent = "suivi du point…";
    try {
      const raw = await sourceFrames(w.src, w.opts, this.size, this.info.max_frames);
      if (seq !== this._trackSeq || this.current !== w || !raw.length) return;
      const times = [];
      let t = Math.max(0, w.opts.start || 0);
      for (const f of raw) { times.push(t); t += f.ms / 1000; }
      const nearest = (at) => times.reduce((best, x, i) => (Math.abs(x - at) < Math.abs(times[best] - at) ? i : best), 0);
      const { pixels, tw, th } = framePixels(raw.map((f) => f.bmp), 256);
      const path = trackPoint(pixels, tw, th, w.opts.anchors.map((a) => ({ i: nearest(a.t), x: a.x, y: a.y })));
      w.opts.track = path.map((p, i) => ({ t: times[i], x: p.x, y: p.y }));
      w.opts.follow = true;
      w.opts.trackAuto = true;
      const follow = this._main().querySelector("#follow");
      if (follow) follow.checked = true;
      this._drawKeys();
      this._changed("crop");
    } catch (err) {
      this._main().querySelector("#err").textContent = `Suivi : ${err.message || err}`;
    }
  }

  async _autoTrack() {
    const w = this.current;
    const button = this._main().querySelector("#autoTrack");
    button.disabled = true;
    button.textContent = "🎯 Analyse…";
    try {
      const raw = await sourceFrames(w.src, w.opts, this.size, this.info.max_frames);
      const times = [];
      let t = Math.max(0, w.opts.start || 0);
      for (const f of raw) { times.push(t); t += f.ms / 1000; }
      w.opts.track = autoTrack(raw.map((f) => f.bmp), times);
      w.opts.follow = true;
      w.opts.trackAuto = true;
      this._main().querySelector("#follow").checked = true;
      this._drawKeys();
      this._changed("crop");
    } catch (err) {
      this._main().querySelector("#err").textContent = `Suivi : ${err.message || err}`;
    } finally {
      button.disabled = false;
      button.textContent = "🎯 Suivi auto";
    }
  }

  /** Timeline with start/end handles; a click moves the video's play position. */
  _setupTrim(trim, media) {
    const video = this.current.src.kind === "video";
    const total = this.current.src.duration || 1;
    // Pointer position as a time inside the visible range, clamped to the video.
    const at = (ev) => {
      const [from, to] = this._viewRange();
      const x = Math.min(1, Math.max(0, (ev.clientX - trim.getBoundingClientRect().left) / trim.clientWidth));
      return Math.min(total, Math.max(0, from + x * (to - from)));
    };
    let edge = null;
    let scrubbing = false;
    // Two fingers: spread or pinch to zoom the timeline, slide to move along it.
    const fingers = new Map();
    let pinch = null;
    const pinchState = () => {
      const [a, b] = [...fingers.values()];
      const rect = trim.getBoundingClientRect();
      return { gap: Math.max(10, Math.abs(a.x - b.x)), mid: ((a.x + b.x) / 2 - rect.left) / trim.clientWidth };
    };
    trim.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      trim.setPointerCapture(ev.pointerId);
      fingers.set(ev.pointerId, { x: ev.clientX });
      if (fingers.size === 2) {
        // A second finger turns the gesture into a zoom: forget the drag it started.
        const [from, to] = this._viewRange();
        const p = pinchState();
        pinch = { ...p, from, to, at: from + p.mid * (to - from) };
        edge = null;
        scrubbing = false;
        return;
      }
      edge = ev.target.dataset.edge || null;
      scrubbing = !edge;
      this._pause();
      if (scrubbing) this._seekTo(at(ev));
    });
    trim.addEventListener("pointermove", (ev) => {
      if (fingers.has(ev.pointerId)) fingers.set(ev.pointerId, { x: ev.clientX });
      if (pinch && fingers.size === 2) {
        const p = pinchState();
        const width = Math.min(total, Math.max(0.2, (pinch.to - pinch.from) * (pinch.gap / p.gap)));
        const from = pinch.at - p.mid * width;
        this._setView(from, from + width);
        return;
      }
      if (scrubbing) { this._seekTo(at(ev)); return; }
      if (!edge) return;
      this._setEdge(edge, at(ev), false);
      // Show the frame under the handle while dragging.
      const t = this._window()[edge === "start" ? 0 : 1];
      if (video) media.currentTime = t;
      this._moveHead(t);
    });
    const release = (ev) => {
      fingers.delete(ev.pointerId);
      if (pinch) {
        if (fingers.size < 2) pinch = null;
        return;
      }
      scrubbing = false;
      if (edge) { edge = null; this._changed("time"); }
    };
    trim.addEventListener("pointerup", release);
    trim.addEventListener("pointercancel", release);
    trim.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const [from, to] = this._viewRange();
      if (ev.shiftKey || Math.abs(ev.deltaX) > Math.abs(ev.deltaY)) {
        const delta = (ev.shiftKey ? ev.deltaY : ev.deltaX) / trim.clientWidth;
        this._setView(from + delta * (to - from), to + delta * (to - from));
      } else {
        this._zoom(ev.deltaY > 0 ? 1.25 : 0.8, at(ev));
      }
    }, { passive: false });

    const overview = this._main().querySelector("#overview");
    const centerOn = (ev) => {
      const [from, to] = this._viewRange();
      const t = ((ev.clientX - overview.getBoundingClientRect().left) / overview.clientWidth) * total;
      this._setView(t - (to - from) / 2, t + (to - from) / 2);
    };
    let panning = false;
    overview.addEventListener("pointerdown", (ev) => { overview.setPointerCapture(ev.pointerId); panning = true; centerOn(ev); });
    overview.addEventListener("pointermove", (ev) => { if (panning) centerOn(ev); });
    overview.addEventListener("pointerup", () => { panning = false; });

    const main = this._main();
    main.querySelector("#zoomIn").onclick = () => this._zoom(0.5, this._headTime);
    main.querySelector("#zoomOut").onclick = () => this._zoom(2);
    main.querySelector("#zoomAll").onclick = () => this._setView(0, total);
    main.querySelector("#zoomSel").onclick = () => {
      const [start, end] = this._window();
      const margin = (end - start) * 0.15;
      this._setView(start - margin, end + margin);
    };
    this._drawTrim();
  }

  _setupCrop(stage, media) {
    const w = this.current;
    const { width: natW, height: natH } = w.src;
    const box = document.createElement("div");
    box.className = "crop";
    box.innerHTML = `<div class="handle"></div>`;
    stage.appendChild(box);
    this._cropBox = box;
    const place = () => {
      if (!box.isConnected) { window.removeEventListener("resize", place); return; }
      // Fill the card width (small images too), leaving room under it for the
      // timeline so the whole editor fits in the window.
      const width = stage.parentElement.clientWidth - 32;
      const room = window.innerHeight - stage.getBoundingClientRect().top
        - (stage.parentElement.scrollHeight - stage.offsetHeight) - 24;
      const scale = Math.min(width / natW, Math.max(160, room, window.innerHeight * 0.3) / natH);
      Object.assign(media.style, { width: `${Math.round(natW * scale)}px`, height: `${Math.round(natH * scale)}px` });
      const r = media.getBoundingClientRect();
      const [x, y, cw, ch] = cropAt(w.opts, this._headTime ?? 0);
      Object.assign(box.style, { left: `${x * r.width}px`, top: `${y * r.height}px`, width: `${cw * r.width}px`, height: `${ch * r.height}px` });
    };
    this._placeCrop = place;
    place();
    this._updateCropVisibility();
    window.addEventListener("resize", place);

    let drag = null;
    box.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      box.setPointerCapture(ev.pointerId);
      // ✋ Suivi perso keeps the video playing: the square is recorded as it goes.
      if (!w.opts.manual) this._pause();
      const crop = [...cropAt(w.opts, this._headTime ?? 0)];
      drag = { resize: ev.target.classList.contains("handle"), x: ev.clientX, y: ev.clientY, crop, current: crop,
        lastT: this._headTime ?? 0, manual: !!w.opts.manual };
      this._cropDrag = drag;
    });
    box.addEventListener("pointermove", (ev) => {
      if (!drag) return;
      const r = media.getBoundingClientRect();
      const [x0, y0, w0, h0] = drag.crop;
      const dx = (ev.clientX - drag.x) / r.width;
      const dy = (ev.clientY - drag.y) / r.height;
      let crop;
      if (drag.resize) {
        // Square in source pixels: the width and height fractions differ by the aspect ratio.
        const side = Math.max(8, Math.min(w0 * natW + Math.max(dx * natW, dy * natH), (1 - x0) * natW, (1 - y0) * natH));
        crop = [x0, y0, side / natW, side / natH];
      } else {
        crop = [Math.min(Math.max(0, x0 + dx), 1 - w0), Math.min(Math.max(0, y0 + dy), 1 - h0), w0, h0];
      }
      if (drag.manual) {
        // Only the box moves now; the LED preview catches up on release.
        drag.current = crop;
        this._recordCrop(drag, this._headTime ?? 0);
        place();
        return;
      }
      if (w.opts.follow) {
        // Following: moving the square sets a position at the playhead, resizing
        // it a zoom; both glide to the next ones.
        const t = this._headTime ?? 0;
        if (drag.resize) w.opts.zoom = setZoom(w.opts.zoom || [], t, crop[2] / w.opts.crop[2]);
        w.opts.track = setKey(w.opts.track || [], t, crop[0] + crop[2] / 2, crop[1] + crop[3] / 2);
        if (w.opts.trackAuto && w.opts.track.length <= 80) w.opts.trackAuto = false;
        this._drawKeys();
      } else {
        w.opts.crop = crop;
      }
      place();
      this._changed("crop");
    });
    const end = () => {
      const was = drag;
      drag = null;
      this._cropDrag = null;
      if (was?.manual) this._changed("crop");
    };
    box.addEventListener("pointerup", end);
    box.addEventListener("pointercancel", end);
    // Mouse wheel on the square: zoom in or out around its centre (a zoom key when following).
    box.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      this._pause();
      const t = this._headTime ?? 0;
      const [x, y, cw, ch] = cropAt(w.opts, t);
      const side = Math.max(8, Math.min(cw * natW * (ev.deltaY > 0 ? 1.1 : 1 / 1.1), natW, natH));
      const [nw, nh] = [side / natW, side / natH];
      if (w.opts.follow) {
        w.opts.zoom = setZoom(w.opts.zoom || [], t, nw / w.opts.crop[2]);
        this._drawKeys();
      } else {
        const [cx, cy] = [x + cw / 2, y + ch / 2];
        w.opts.crop = [Math.min(Math.max(0, cx - nw / 2), 1 - nw), Math.min(Math.max(0, cy - nh / 2), 1 - nh), nw, nh];
      }
      place();
      this._changed("crop");
    }, { passive: false });
    // 📍 on: a click on the image sets a point on the subject at this moment.
    stage.addEventListener("pointerdown", (ev) => {
      if (!this._pointing) return;
      ev.preventDefault();
      ev.stopPropagation();
      const r = media.getBoundingClientRect();
      const x = (ev.clientX - r.left) / r.width;
      const y = (ev.clientY - r.top) / r.height;
      if (x < 0 || x > 1 || y < 0 || y > 1) return;
      this._pause();
      w.opts.anchors = setKey(w.opts.anchors || [], this._headTime ?? 0, x, y);
      w.opts.follow = true;
      this._drawKeys();
      this._trackAnchors();
    }, true);
  }

  /** ✋ Suivi perso: the square held at time t, replacing the moments gone through since the last one. */
  _recordCrop(drag, t) {
    const o = this.current.opts;
    const [x, y, cw, ch] = drag.current;
    o.track = recordKey(o.track || [], drag.lastT, t, { x: x + cw / 2, y: y + ch / 2 });
    o.zoom = recordKey(o.zoom || [], drag.lastT, t, { s: cw / o.crop[2] });
    drag.lastT = t;
    this._drawKeys();
  }

  _updateCropVisibility() {
    if (!this._cropBox) return;
    const cropping = this.current.opts.fit === "crop";
    this._cropBox.style.display = cropping ? "" : "none";
    const hint = this._main().querySelector("#hint");
    if (hint) hint.style.visibility = cropping ? "" : "hidden";
  }

  /**
   * Something changed in the editor. Crop and tone changes re-render the
   * cached source frames instantly (coalesced per animation frame); clip
   * window changes re-extract video frames; the final size is asked from
   * Home Assistant and the live still sent to the display after a pause.
   */
  _changed(kind = "tone", initial = false) {
    const w = this.current;
    w.result = null;
    if (!initial) {
      this._persistClip(w);
      if (w.pushed) w.dirty = true;
      if (w.status === "error") w.status = "ready";
    }
    if (kind !== "budget") {
      w.frames = null;
      clearTimeout(this._renderTimer);
      if (kind === "time") {
        this._renderPreview();
      } else {
        // While dragging: redraw only the frame on screen, instantly; the
        // whole animation follows once the movement pauses.
        this._quickPreview(kind);
        this._renderTimer = setTimeout(() => this._renderPreview(), 250);
      }
    }
    clearTimeout(this._encodeTimer);
    this._encodeTimer = setTimeout(() => this._estimate(), kind === "budget" ? 500 : 1200);
    if (kind !== "budget") this._scheduleLive();
  }

  async _renderPreview() {
    const w = this.current;
    if (this.state.tab !== "editor" || !w) return;
    const seq = ++this._renderSeq;
    const stats = this._main().querySelector("#stats");
    try {
      const frames = await processItem(w, this.size, this.info.max_frames, (i, n) => {
        // Superseded by a newer start/end: stop, the newer extraction takes the video.
        if (seq !== this._renderSeq) throw STALE;
        this._setWork(`Extraction de la vidéo ${i}/${n}…`, i / n);
      });
      if (seq === this._renderSeq) this._setWork(null);
      if (seq !== this._renderSeq || this.current !== w || this.state.tab !== "editor") return;
      w.frames = frames;
      const total = frames.reduce((s, f) => s + f.ms, 0);
      const loops = w.opts.boomerang && frames.length > 2 ? (2 * frames.length - 2) / frames.length : 1;
      if (stats) stats.innerHTML = `<span>${frames.length} images</span><span>${(total * loops / 1000).toFixed(1)} s</span><span>${this.size}×${this.size}</span>`;
      this._play(frames);
    } catch (err) {
      if (err === STALE) return;
      if (seq === this._renderSeq) this._setWork(null);
      if (stats) stats.innerHTML = `<span class="error">${esc(err.message || err)}</span>`;
    }
  }

  _quickPreview(kind) {
    const w = this.current;
    const canvas = this._main().querySelector("#led");
    const scaled = w.scaled;
    if (!canvas || !scaled) return;
    this._stopPlayer();
    const index = Math.min(this._playFrame || 0, scaled.raw.length - 1);
    const base = kind === "crop"
      ? scaleFrame(scaled.raw[index].bmp, w.opts, this.size, makeCanvas(this.size, this.size).getContext("2d", { willReadFrequently: true }), scaled.times?.[index] ?? 0)
      : scaled.frames[index];
    drawLed(canvas, toneFrame(base, w.opts));
  }

  /**
   * One clock drives the LED preview and the source view, so both sides
   * show the same moment; the head on the timeline follows it.
   */
  _play(frames, exact = false) {
    this._stopPlayer();
    const n = frames.length;
    const order = [...frames.keys()];
    // The final GIF already contains its boomerang half.
    if (!exact && this.current.opts.boomerang && n > 2) for (let i = n - 2; i > 0; i--) order.push(i);
    const mode = this._main().querySelector("#previewMode");
    if (mode) {
      mode.innerHTML = exact
        ? `<span class="ok">✓ Aperçu exact : le GIF final, tel que le cadre l'affichera</span>`
        : "Aperçu instantané (avant réduction des couleurs) · le GIF final arrive…";
    }
    const previous = this._transport;
    const playing = previous?.playing ?? true;
    // A change re-renders the preview: keep the moment being watched, not the first frame.
    let pos = 0;
    if (previous?.clip === this.current.id && this._headTime != null) {
      let gap = Infinity;
      order.forEach((index, p) => {
        const d = Math.abs((frames[index].t ?? 0) - this._headTime);
        if (d < gap) { gap = d; pos = p; }
      });
    }
    this._transport = { frames, order, pos, playing, clip: this.current.id };
    this._showFrame();
    if (playing) this._tick();
    this._updatePlayButton();
  }

  _tick() {
    const tr = this._transport;
    if (!tr || tr.order.length < 2) return;
    const ms = tr.frames[tr.order[tr.pos]].ms;
    this._timer = setTimeout(() => {
      if (this._transport !== tr || !this._main().querySelector("#led")) return;
      tr.pos = (tr.pos + 1) % tr.order.length;
      this._showFrame();
      this._tick();
    }, Math.max(20, ms));
  }

  _showFrame() {
    const tr = this._transport;
    const canvas = this._main().querySelector("#led");
    if (!tr || !canvas) return;
    const index = tr.order[tr.pos];
    const frame = tr.frames[index];
    // Exact frames point back at the source frame they come from.
    const source = frame.srcIndex ?? index;
    this._playFrame = source;
    drawLed(canvas, frame.data);
    const mini = this._main().querySelector("#ledMini");
    // offsetParent is always null for a fixed element: ask for its boxes instead.
    if (mini && !mini.hidden && mini.getClientRects().length) drawLed(mini, frame.data);
    // Live on the display while playing: a stream of stills, as fast as Bluetooth takes them.
    if (this._live && tr.playing && performance.now() - (this._lastLive || 0) > LIVE_INTERVAL_MS) this._sendLive();
    const w = this.current;
    const media = this._media;
    if (w.src.kind === "video" && media && !media.seeking) media.currentTime = frame.t;
    if (w.src.kind === "animated" && media && w.scaled?.raw[source]) {
      const ctx = media.getContext("2d");
      ctx.clearRect(0, 0, media.width, media.height);
      ctx.drawImage(w.scaled.raw[source].bmp, 0, 0, media.width, media.height);
    }
    this._moveHead(frame.t);
    const held = this._cropDrag;
    if (held?.manual && tr.playing) this._recordCrop(held, frame.t);
    if (w.opts.follow && this._placeCrop) this._placeCrop();
  }

  _moveHead(t) {
    const total = this.current.src.duration || 1;
    t = Math.min(total, Math.max(0, t));
    this._headTime = t;
    const main = this._main();
    const head = main.querySelector("#trim .head");
    if (!head) return;
    const [from, to] = this._viewRange();
    head.style.left = `${((t - from) / (to - from)) * 100}%`;
    main.querySelector("#overview .ov-head").style.left = `${(t / total) * 100}%`;
  }

  /** Pause on the frame shown at time t (the video itself shows exactly t). */
  _seekTo(t) {
    const tr = this._transport;
    if (!tr) return;
    let pos = 0;
    tr.order.forEach((index, p) => {
      if (p < tr.frames.length && tr.frames[index].t <= t) pos = p;
    });
    tr.pos = pos;
    this._showFrame();
    if (this.current.src.kind === "video" && this._media) this._media.currentTime = t;
    this._moveHead(t);
    this._scheduleLive();
  }

  _pause() {
    if (!this._transport) return;
    this._transport.playing = false;
    this._stopPlayer();
    this._updatePlayButton();
  }

  _togglePlay() {
    const tr = this._transport;
    if (!tr) return;
    if (tr.playing) { this._pause(); return; }
    tr.playing = true;
    this._tick();
    this._updatePlayButton();
  }

  _updatePlayButton() {
    for (const play of this._main().querySelectorAll("#play, #playTop")) {
      play.textContent = this._transport?.playing ? "⏸" : "▶";
    }
  }

  _currentStill() {
    const tr = this._transport;
    return tr ? tr.frames[tr.order[tr.pos]].data : this.current.frames?.[0]?.data;
  }

  async _sendStill() {
    const still = this._currentStill();
    const button = this._main().querySelector("#sendStill");
    if (!still) return;
    button.disabled = true;
    try {
      await this._ws({ type: "idotmatrix/studio/live", png: stillPng(still) });
      this._onTransfer({ file: "live", state: "started" });
    } catch (err) {
      this._main().querySelector("#err").textContent = err.message || err;
    } finally {
      setTimeout(() => { if (button.isConnected) button.disabled = false; }, 1500);
    }
  }

  _stopPlayer() { clearTimeout(this._timer); this._timer = null; }

  async _estimate() {
    const w = this.current;
    if (this.state.tab !== "editor" || !w) return;
    const final = this._main().querySelector("#final");
    if (!w.frames) { this._encodeTimer = setTimeout(() => this._estimate(), 500); return; }
    final.textContent = "Calcul de la taille finale sur le Pi…";
    // One preview at a time: settings changed meanwhile ask for the latest once it is back.
    if (this._estimating) { this._estimateAgain = true; return; }
    this._estimating = true;
    const frames = w.frames;
    try {
      const res = await this._encode(w, { save: false });
      if (res.superseded) return;
      // Settings changed while the Pi was encoding: a newer estimate follows.
      if (this.current !== w || !final.isConnected || w.frames !== frames) return;
      w.result = res;
      if (this._transport && this.current === w) this._play(this._exactFrames(res, frames, w.opts), true);
      final.innerHTML = `<img class="final" src="data:image/gif;base64,${res.gif}" title="GIF final">
        <span><b>${kb(res.size_bytes)}</b></span><span>${(res.duration_ms / 1000).toFixed(1)} s</span>
        <span>${res.colors} couleurs</span>
        <span>envoi ${duration(res.estimate_s)}</span>`;
    } catch (err) {
      final.innerHTML = `<span class="error">${esc(err.message || err)}</span>`;
    } finally {
      this._estimating = false;
      if (this._estimateAgain) {
        this._estimateAgain = false;
        this._estimate();
      }
    }
  }

  /**
   * Frames of the encoded GIF, each mapped back to the source time it shows
   * (frames may have been thinned or merged, and boomerang adds a way back).
   */
  _exactFrames(res, frames, o) {
    const bytes = Uint8Array.from(atob(res.gif), (c) => c.charCodeAt(0));
    const gif = decodeGif(bytes.buffer);
    const forward = frames.reduce((sum, f) => sum + f.ms, 0);
    const start = frames[0]?.t ?? 0;
    const speed = o.speed || 1;
    let elapsed = 0;
    return gif.frames.map((f) => {
      let at = elapsed;
      elapsed += f.ms;
      if (at >= forward) at = Math.max(0, 2 * forward - at - (frames.at(-1)?.ms || 0));
      const t = start + (at * speed) / 1000;
      let srcIndex = 0;
      frames.forEach((g, i) => { if (g.t <= t + 1e-6) srcIndex = i; });
      return { data: f.data, ms: f.ms, t, srcIndex };
    });
  }

  /** Mirror the frame being edited on the real display once edits pause. */
  _scheduleLive() {
    clearTimeout(this._liveTimer);
    if (!this._live || this.state.tab !== "editor") return;
    // Right away: Home Assistant keeps only the newest still while one is sent.
    this._liveTimer = setTimeout(() => this._sendLive(), 50);
  }

  /** Send the frame on screen to the display (Home Assistant drops the ones it cannot keep up with). */
  async _sendLive() {
    const w = this.current;
    if (!this._live || !w || this.state.tab !== "editor") return;
    this._lastLive = performance.now();
    try {
      // The frame shown in the preview (head position), not the clip start.
      const still = this._currentStill() || (await processItem(w, this.size, 1))[0].data;
      await this._ws({ type: "idotmatrix/studio/live", png: stillPng(still) });
    } catch (err) {
      const el = this._main().querySelector("#err");
      if (el) el.textContent = `Direct : ${err.message || err}`;
    }
  }

  /** Send the edit as a new clip (its own GIF), put the edited clip back as it was, and go on editing the new one. */
  _saveAsNewClip() {
    const w = this.current;
    const opened = this._opened;
    const typed = this._main().querySelector("#title").value.trim();
    const copy = this._newClip(this._original(w.originalId), w);
    // A name typed in the editor goes to the new clip; otherwise it is « … (copie) » of the original name.
    copy.title = typed && typed !== opened?.title ? typed : `${opened?.title ?? w.title} (copie)`;
    Object.assign(copy, { src: w.src, frames: w.frames });  // already extracted for these settings
    if (opened) Object.assign(w, { opts: opened.opts, title: opened.title, dirty: opened.dirty, frames: null, result: null });
    this._persistClip(w);
    this._persistClip(copy);
    this._push(copy, false);
    // Keep editing, now on the new clip: the edit goes on from where it was.
    return this._openEditor(copy);
  }

  /** From the editor: the clip, or its original with all its clips, to the workspace trash (second tap). */
  _editorDelete(kind, button) {
    const clip = this.current;
    if (!clip) return;
    const original = this._original(clip.originalId);
    const others = original ? this._clipsOf(original).length : 0;
    if (kind === "original" && !original) return;
    const label = kind === "clip" ? "Supprimer le clip ?" : `Supprimer l'original${others > 1 ? ` et ses ${others} clips` : ""} ?`;
    if (!this._armed(button, label)) return;
    this._stopPlayer();
    if (kind === "clip") this._trashClip(clip);
    else this._trashOriginal(original);
    this.current = null;
    this._show("workspace");
  }

  async _saveCurrent(display) {
    const main = this._main();
    const w = this.current;
    w.title = main.querySelector("#title").value.trim() || "animation";
    // The Pi works through the queue in the background; progress stays in the status bar.
    this._push(w, display);
    this._show("workspace");
  }

  // --------------------------------------------------------------- routines

  async _renderRoutines() {
    const main = this._main();
    main.innerHTML = `<div class="card modecard">
        <div class="modes" title="Qui décide de ce qu'affiche le cadre">
          <button class="modebtn" data-mode="plan">📅 Planning</button><button class="modebtn" data-mode="manual">✋ Manuel</button></div>
        <p class="muted small" id="modehint"></p>
      </div>
      <div class="card sched">
        <div class="toolbar"><b class="grow">📅 Planning de la journée</b>
          <select id="sgaps" class="small" title="Ce que fait le cadre en dehors des plages">
            <option value="off">Hors plages : écran éteint</option><option value="keep">Hors plages : rien ne change</option></select>
          <button class="act small" id="ssave" disabled>Enregistrer</button></div>
        <div class="chips" id="sdays"></div>
        <div class="day" id="day"></div>
        <div class="ticks">${[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => `<span style="left:${(h / 24) * 100}%">${h}h</span>`).join("")}</div>
        <div id="sblocks"></div>
        <div class="row"><button class="act ghost small" id="saddSet" title="Une plage où un ensemble passe">+ Plage d'ensemble</button>
          <button class="act ghost small" id="sadd" title="Une plage où l'écran est éteint">+ Écran éteint</button>
          <span class="muted small grow" id="shint"></span></div>
        <p class="error small" id="serr"></p>
      </div>
      <div class="toolbar">
        <b>Ensembles de GIF</b><span class="grow muted small">tournent sur Home Assistant, même navigateur fermé</span>
        <button class="act ghost" id="newWeather" title="L'heure et la météo de la journée, mise à jour chaque minute">+ Météo</button>
        <button class="act" id="newRoutine">+ Nouvel ensemble</button></div>
      <div id="routines"></div>`;
    main.querySelector("#newRoutine").onclick = () => this._editRoutine(null);
    main.querySelector("#newWeather").onclick = () => { this._weatherView = "new"; this._show("weather"); };
    this._schedDirty = false;
    this._setupSchedule();
    const [{ routines, status }] = await Promise.all([this._ws({ type: "idotmatrix/studio/routines" }), this._galleryItems()]);
    this.state.routines = routines;
    this.state.routineStatus = status;
    this._drawSchedule();  // also draws the ensembles
  }

  // ------------------------------------------------------- day schedule

  _setupSchedule() {
    const main = this._main();
    const $ = (sel) => main.querySelector(sel);
    const edited = () => this._schedEdited();
    // Planning: the strip decides. Manuel: ensembles are switched on and off by
    // hand, and the planning waits until Planning is chosen again.
    main.querySelector(".modes").onclick = (ev) => {
      const button = ev.target.closest("[data-mode]");
      if (!button || !this._sched) return;
      const plan = button.dataset.mode === "plan";
      if (plan === !!this._sched.enabled) return;
      this._sched.enabled = plan;
      this._schedEdited();
      this._saveSchedule();
    };
    $("#sgaps").onchange = (ev) => { this._sched.gaps = ev.target.value; edited(); };
    // Drag a block to move it, its edges to change its hours (15 min steps).
    const day = $("#day");
    day.onpointerdown = (ev) => {
      const blk = ev.target.closest(".blk");
      if (!blk || ev.button > 0) return;
      const block = this._sched.blocks[Number(blk.dataset.i)];
      const edge = ev.target.dataset.edge || null;
      const width = day.getBoundingClientRect().width || 1;
      const startX = ev.clientX;
      const from = toMinutes(block.from);
      const to = toMinutes(block.to);
      const snap = (m) => (((Math.round(m / 15) * 15) % 1440) + 1440) % 1440;
      let moved = false;
      day.setPointerCapture?.(ev.pointerId);
      day.onpointermove = (e) => {
        if (!moved && Math.abs(e.clientX - startX) < 4) return;
        moved = true;
        const delta = ((e.clientX - startX) / width) * 1440;
        const next = { from: edge === "to" ? from : snap(from + delta), to: edge === "from" ? to : snap(to + delta) };
        if (next.from === next.to) return;
        Object.assign(block, { from: fromMinutes(next.from), to: fromMinutes(next.to) });
        edited();
      };
      day.onpointerup = day.onpointercancel = () => {
        day.onpointermove = day.onpointerup = day.onpointercancel = null;
        this._schedDragged = moved;
      };
    };
    $("#sblocks").onchange = (ev) => this._schedRowChange(ev);
    $("#sdays").onclick = (ev) => {
      const chip = ev.target.closest("[data-day]");
      if (!chip) return;
      this._schedDay = chip.dataset.day === "*" ? null : Number(chip.dataset.day);
      this._drawSchedule(true);
    };
    $("#sblocks").onclick = (ev) => this._schedRowClick(ev);
    $("#day").onclick = (ev) => {
      if (this._schedDragged) {
        this._schedDragged = false;
        return;
      }
      const blk = ev.target.closest(".blk");
      if (blk) {
        const row = main.querySelector(`.srow[data-i="${blk.dataset.i}"]`);
        if (row) {
          row.scrollIntoView({ block: "nearest", behavior: "smooth" });
          row.classList.add("flash");
          setTimeout(() => row.classList.remove("flash"), 1200);
        }
        return;
      }
      const rect = ev.currentTarget.getBoundingClientRect();
      const hour = Math.min(23, Math.floor(((ev.clientX - rect.left) / rect.width) * 24));
      this._sched.blocks.push({ from: fromMinutes(hour * 60), to: fromMinutes((hour + 1) * 60), action: "off", routine_id: null,
        days: null });
      edited();
    };
    $("#sadd").onclick = () => {
      this._sched.blocks.push({ from: "23:00", to: "07:00", action: "off", routine_id: null, days: null });
      edited();
    };
    $("#saddSet").onclick = () => {
      const first = (this.state.routines || [])[0];
      this._sched.blocks.push(first ? { from: "18:00", to: "22:00", action: "routine", routine_id: first.id, days: null }
        : { from: "23:00", to: "07:00", action: "off", routine_id: null, days: null });
      edited();
    };
    $("#ssave").onclick = () => this._saveSchedule();
  }

  /** A schedule edit: redraw the strip and the routines, then save it shortly after. */
  _schedEdited() {
    this._schedDirty = true;
    this._drawSchedule(true);
    clearTimeout(this._schedSaveTimer);
    this._schedSaveTimer = setTimeout(() => this._saveSchedule(), 800);
  }

  async _saveSchedule() {
    clearTimeout(this._schedSaveTimer);
    const main = this._main();
    const err = main.querySelector("#serr");
    if (err) err.textContent = "";
    try {
      await this._ws({ type: "idotmatrix/studio/schedule_save", schedule: this._sched });
      this._schedDirty = false;
      const save = main.querySelector("#ssave");
      if (save) save.disabled = true;
      this._refreshStatus();
    } catch (e) {
      if (err) err.textContent = e.message || e;
    }
  }

  /** Hours, « what », priority or on/off changed in a time-slot row. */
  _schedRowChange(ev) {
    const row = ev.target.closest(".srow[data-i]");
    if (!row) return false;
    const block = this._sched.blocks[Number(row.dataset.i)];
    const key = ev.target.dataset.k;
    if (key === "from" || key === "to") {
      if (ev.target.value) block[key] = ev.target.value;
    } else if (key === "what") {
      block.action = ev.target.value === "off" ? "off" : "routine";
      block.routine_id = block.action === "routine" ? ev.target.value.slice(2) : null;
    } else if (key === "enabled") {
      if (ev.target.checked) delete block.enabled; else block.enabled = false;
    } else if (key === "priority") {
      const priority = Number(ev.target.value);
      if (priority === 1) delete block.priority; else block.priority = priority;
    } else {
      return false;
    }
    this._schedEdited();
    return true;
  }

  /** A day toggled or a slot deleted in a time-slot row. */
  _schedRowClick(ev) {
    const toggle = ev.target.closest(".srow[data-i] button[data-wd]");
    if (toggle) {
      const block = this._sched.blocks[Number(toggle.closest(".srow").dataset.i)];
      const day = Number(toggle.dataset.wd);
      const days = new Set(block.days || []);
      if (days.has(day)) days.delete(day); else days.add(day);
      // No day chosen (or all of them): every day.
      block.days = days.size && days.size < 7 ? [...days].sort() : null;
      this._schedEdited();
      return true;
    }
    const del = ev.target.closest(".srow[data-i] button[data-del]");
    if (!del) return false;
    this._sched.blocks.splice(Number(del.closest(".srow").dataset.i), 1);
    this._schedEdited();
    return true;
  }

  /** One time slot: hours, days, delete (and what it does, for the « off » list). */
  _blockRowHtml(b, i, colour, withWhat) {
    const routines = this.state.routines || [];
    return `<div class="srow ${b.enabled === false ? "off" : ""}" data-i="${i}">
        <input type="checkbox" data-k="enabled" title="Plage active (décochée : gardée mais ignorée)" ${b.enabled !== false ? "checked" : ""}>
        <span class="swatch" style="background:${b.action === "off" ? "#263238" : colour}"></span>
        <input type="time" data-k="from" value="${b.from}"> → <input type="time" data-k="to" value="${b.to}">
        ${b.from === b.to ? `<span class="muted small">toute la journée</span>` : ""}
        ${withWhat ? `<select data-k="what"><option value="off" ${b.action === "off" ? "selected" : ""}>🌙 Écran éteint</option>
          ${routines.map((r) => `<option value="r:${esc(r.id)}" ${b.action === "routine" && b.routine_id === r.id ? "selected" : ""}>${r.mode === "weather" ? "🌤" : "▶"} ${esc(r.name)}</option>`).join("")}</select>` : ""}
        <span class="days" title="Jours choisis (aucun : tous les jours)">${WEEKDAYS.map((label, d) =>
          `<button data-wd="${d}" class="${b.days?.includes(d) ? "on" : ""}">${label.slice(0, 2)}</button>`).join("")}</span>
        ${b.days?.length ? "" : `<span class="muted small">tous les jours</span>`}
        <select data-k="priority" class="small" title="Si des plages se chevauchent : la priorité la plus haute l'emporte, puis la plage la plus courte">
          ${PRIORITIES.map(([value, label]) => `<option value="${value}" ${(b.priority ?? 1) === value ? "selected" : ""}>${label}</option>`).join("")}</select>
        <button class="icon" data-del title="Supprimer la plage">🗑</button></div>`;
  }

  /** Draw the 24 h strip and the block rows (from the server unless being edited). */
  _drawSchedule(fromEdit = false) {
    const main = this._main();
    const day = main.querySelector("#day");
    if (!day || !this.state.routines) return;
    if (!fromEdit) {
      if (this._schedDirty) return;
      this._sched = structuredClone(this.state.status?.schedule || { enabled: false, blocks: [] });
    }
    const sched = this._sched;
    const routines = this.state.routines;
    const shownDay = this._schedDay ?? null;
    main.querySelector("#sdays").innerHTML = [["*", "Tous les jours"], ...WEEKDAYS.map((label, i) => [String(i), label])]
      .map(([key, label]) => `<button class="chip-btn ${String(shownDay ?? "*") === key ? "on" : ""}" data-day="${key}">${label}${key === String(today()) ? " •" : ""}</button>`)
      .join("") + `<span class="muted small">${shownDay === null ? "voir la journée d'un jour donné" : "aperçu de ce jour (les plages se règlent dessous)"}</span>`;
    const colour = (b) => ROUTINE_COLORS[Math.max(0, routines.findIndex((r) => r.id === b.routine_id)) % ROUTINE_COLORS.length];
    const label = (b) => {
      if (b.action === "off") return "🌙 Éteint";
      const routine = routines.find((r) => r.id === b.routine_id);
      return `${routine?.mode === "weather" ? "🌤" : "▶"} ${esc(routine?.name || "routine supprimée")}`;
    };
    const pct = (m) => `${(m / 1440) * 100}%`;
    let strip = "";
    // Drawn last = on top: the block that wins an overlap, as on the server.
    const order = sched.blocks.map((_b, i) => i).sort((i, j) => outranks(sched.blocks[j], j, sched.blocks[i], i));
    for (const i of order) {
      const b = sched.blocks[i];
      if (b.enabled === false) continue;
      const a = toMinutes(b.from);
      const z = toMinutes(b.to);
      for (const [from, to] of a === z ? [[0, 1440]] : a < z ? [[a, z]] : [[a, 1440], [0, z]]) {
        if (to === from) continue;
        // One day shown: after midnight, a block that crosses it is the day before's.
        if (shownDay !== null && !onDay(b, a > z && from === 0 ? (shownDay + 6) % 7 : shownDay)) continue;
        // Handles on the block's real edges (not on midnight when it wraps).
        const left = from === a && a !== z ? `<i class="h l" data-edge="from"></i>` : "";
        const right = a !== z && (to === z || (z === 0 && to === 1440)) ? `<i class="h r" data-edge="to"></i>` : "";
        const rank = b.priority === 2 ? " · priorité haute" : b.priority === 0 ? " · priorité basse" : "";
        strip += `<div class="blk ${b.action}" data-i="${i}" title="${b.from} → ${b.to}${rank} · glisser pour déplacer, les bords pour changer les heures"
          style="left:${pct(from)};width:${pct(to - from)};background:${colour(b)}">${left}<span>${label(b)}</span>${right}</div>`;
      }
    }
    const now = new Date();
    strip += `<div class="now" style="left:${pct(now.getHours() * 60 + now.getMinutes())}"></div>`;
    day.innerHTML = strip;
    day.classList.toggle("disabled", !sched.enabled);
    day.classList.toggle("gapoff", (sched.gaps || "off") === "off" && sched.blocks.some((b) => b.enabled !== false));
    for (const button of main.querySelectorAll(".modebtn")) {
      button.classList.toggle("on", (button.dataset.mode === "plan") === !!sched.enabled);
    }
    main.querySelector("#modehint").textContent = sched.enabled
      ? "📅 Planning : la frise décide quel ensemble passe et quand. Allumer un ensemble à la main passe en ✋ Manuel."
      : "✋ Manuel : tu allumes et éteins les ensembles toi-même ; le planning est gardé mais attend que tu repasses en 📅 Planning.";
    main.querySelector("#sgaps").value = sched.gaps || "off";
    main.querySelector("#ssave").disabled = !this._schedDirty;
    // Every slot of the planning, whatever it shows: ensembles only hold their GIFs.
    main.querySelector("#sblocks").innerHTML = sched.blocks.map((b, i) => this._blockRowHtml(b, i, colour(b), true)).join("")
      || `<p class="muted small">Aucune plage : ajoute-en une pour qu'un ensemble passe à ses heures, ou pour éteindre l'écran.</p>`;
    const minutes = new Array(1440).fill(0);
    for (const b of sched.blocks) {
      if (b.enabled === false || (shownDay !== null && !onDay(b, shownDay))) continue;
      const a = toMinutes(b.from);
      const z = toMinutes(b.to);
      let m = a;
      do { minutes[m]++; m = (m + 1) % 1440; } while (m !== z);
    }
    const notes = [];
    if (minutes.some((n) => n > 1)) notes.push("Des plages se chevauchent : celle de priorité la plus haute l'emporte, à égalité la plus courte (une routine « toute la journée » sert de fond). La frise montre celle qui passe.");
    if (!sched.enabled && sched.blocks.length) notes.push("Mode Manuel : ces plages attendent le retour au mode 📅 Planning.");
    if (!notes.length) {
      notes.push("Touche la frise vide pour ajouter une heure, glisse une plage pour la déplacer et ses bords pour changer les heures."
        + ((sched.gaps || "off") === "off" ? " En dehors des plages, l'écran est éteint." : ""));
    }
    main.querySelector("#shint").textContent = notes.join(" ");
    this._drawRoutineList();
  }

  _drawRoutineList() {
    const list = this._main().querySelector("#routines");
    if (!list) return;
    const status = this.state.routineStatus || {};
    const routines = this.state.routines || [];
    const blocks = this._sched?.blocks || [];
    list.innerHTML = routines.map((r, n) => {
      const active = status.active === r.id;
      const slots = blocks.filter((b) => b.action === "routine" && b.routine_id === r.id && b.enabled !== false).length;
      const colour = ROUTINE_COLORS[n % ROUTINE_COLORS.length];
      return `<div class="orig routine ${active ? "active" : ""}" data-routine="${esc(r.id)}">
        <div class="orow">
          <span class="swatch" style="background:${colour}"></span>
          <label class="switch" title="On : cet ensemble passe maintenant (mode ✋ Manuel, le planning attend). Off : il s'arrête.">
            <input type="checkbox" data-run="${esc(r.id)}" ${active ? "checked" : ""}><span>${active ? "On" : "Off"}</span></label>
          ${active && r.mode === "ha" ? `<button class="icon" data-act="next" title="GIF suivant maintenant">⏭</button>` : ""}
          <div class="grow ellipsis"><span class="title">${esc(r.name)}</span>
            <span class="muted small">${this._routineSummary(r)}${slots ? ` · 📅 ${slots} plage${slots > 1 ? "s" : ""} au planning` : ""}</span></div>
          <button class="icon" data-act="edit" title="Modifier">✎</button>
          <button class="icon" data-act="delete" title="Supprimer">🗑</button>
        </div>
        ${active ? `<div class="muted small routine-status">${this._routineStatusText(status)}</div>
          <div class="upnext">${this._upNextHtml(status)}</div>` : ""}
      </div>`;
    }).join("") || `<div class="card empty muted">Aucun ensemble. Un ensemble change ce qu'affiche le cadre toutes les N minutes, au hasard ou dans l'ordre, parmi une sélection de GIF ; tu l'allumes à la main ou tu le mets au planning.</div>`;
    this._fillThumbs(list);
    list.onclick = (ev) => {
      if (this._upNextClick(ev)) return;
      this._routineAction(ev);
    };
    list.onchange = (ev) => {
      const run = ev.target.closest("[data-run]");
      if (run) this._runEnsemble(run.dataset.run, run.checked);
    };
  }

  /** On: the ensemble plays now, in ✋ Manuel mode (the Pi pauses the planning). Off: it stops. */
  async _runEnsemble(id, on) {
    try {
      if (on) {
        this._onRoutineStatus(await this._ws({ type: "idotmatrix/studio/routine_start", routine_id: id }));
        if (this._sched && !this._schedDirty) {
          this._sched.enabled = false;
          this._drawSchedule(true);
        }
      } else {
        await this._ws({ type: "idotmatrix/studio/routine_stop" });
        this._onRoutineStatus({ active: null });
      }
      this._refreshStatus();
    } catch (err) {
      alert(err.message || err);
      this._drawRoutineList();
    }
  }

  /**
   * Thumbnails of what a running routine shows next: the current GIF then the
   * next ones drawn by Home Assistant (a click shows that one now), or the
   * display carousel's slots with the one it probably shows (the display never
   * says: estimated from when it started and the interval).
   */
  _upNextHtml(status) {
    if (!status || !status.active) return "";
    if (!this.state.items && !this._itemsLoading) {
      this._itemsLoading = this._galleryItems().catch(() => {}).finally(() => { this._redrawUpNext(); });
    }
    const title = (file) => esc(this.state.items?.find((i) => i.file === file)?.title || file);
    const thumb = (file, cls, attrs, label, badge = "") =>
      `<button class="th ${cls}" ${attrs} title="${title(file)}${label}"><img data-thumb="${esc(file)}" alt="">${badge}</button>`;
    if (status.state === "carousel") {
      const slots = status.carousel || [];
      const shown = status.carousel_at && status.interval && slots.length
        ? Math.floor((Date.now() / 1000 - status.carousel_at) / status.interval) % slots.length : -1;
      return slots.map((file, i) => thumb(file, i === shown ? "now est" : "", "",
        ` — emplacement ${i + 1}${i === shown ? " (probablement affiché, estimation)" : ""}`, `<i>${i + 1}</i>`)).join("");
    }
    const current = status.current ? [thumb(status.current, "now", "", " — affiché maintenant")] : [];
    return current.concat((status.upcoming || []).map((file, i) =>
      thumb(file, "", `data-upnext="${esc(file)}"`, ` — ${i ? `dans ${i + 1} GIF` : "le suivant"} · cliquer pour l'afficher maintenant`))).join("");
  }

  /** Signed thumbnail URLs, reused for 50 minutes (they are signed for an hour). */
  _fillThumbs(root) {
    this._thumbUrls ||= new Map();
    for (const img of root.querySelectorAll("img[data-thumb]")) {
      const item = this.state.items?.find((i) => i.file === img.dataset.thumb);
      if (!item) continue;
      const key = `${item.url}?v=${Math.round(item.modified)}`;
      let cached = this._thumbUrls.get(key);
      if (!cached || cached.at < Date.now() - 50 * 60 * 1000) {
        cached = { at: Date.now(), url: this._sign(key) };
        cached.url.catch(() => this._thumbUrls.delete(key));
        this._thumbUrls.set(key, cached);
      }
      cached.url.then((url) => { img.src = url; }, () => {});
    }
  }

  _redrawUpNext() {
    const strip = this.shadowRoot.querySelector("#supnext");
    if (strip) {
      strip.innerHTML = this._upNextHtml(this.state.status?.routine);
      this._fillThumbs(strip);
    }
    // Only the strip: redrawing the whole list would drop an hour being typed.
    const row = this.state.tab === "routines" && this._main().querySelector(".routine.active .upnext");
    if (row) {
      row.innerHTML = this._upNextHtml(this.state.routineStatus);
      this._fillThumbs(row);
    }
  }

  /** A click on an upcoming GIF shows it now. True when the click was one. */
  _upNextClick(ev) {
    const button = ev.target.closest("[data-upnext]");
    if (!button) return false;
    button.disabled = true;
    this._ws({ type: "idotmatrix/studio/routine_next", file: button.dataset.upnext }).catch((err) => {
      this._screenError = `Routine : ${err.message || err}`;
      this._refreshStatus();
    });
    return true;
  }

  _routineSummary(r) {
    if (r.mode === "weather") {
      const strip = { days: "les prochains jours", sun: "lever et coucher du soleil" }[r.weather?.strip] || "les prochaines heures";
      const hours = r.hours ? ` · ${r.hours.from}–${r.hours.to}` : "";
      const clock = r.weather?.seconds === false ? "l'heure" : "l'heure et les secondes";
      return `🌤 ${esc(this._weatherPlace(r.weather))} · ${clock}, ${strip}, météo toutes les ${Math.round(r.interval / 60)} min${hours}`;
    }
    const every = r.interval >= 60 ? `${+(r.interval / 60).toFixed(1)} min` : `${r.interval} s`;
    const mode = r.mode === "carousel" ? "carrousel du cadre" : "piloté par HA";
    const hours = r.hours ? ` · ${r.hours.from}–${r.hours.to}` : "";
    const collection = r.collection && (this.state.collections || []).find((c) => c.id === r.collection);
    const gifs = collection ? `🗂 ${esc(collection.name)} (${collection.files.length} GIF)` : `${r.files.length} GIF`;
    return `${gifs} · toutes les ${every} · ${r.order === "random" ? "aléatoire" : "dans l'ordre"} · ${mode}${hours}`;
  }

  _routineStatusText(status) {
    const next = status.next_at ? ` · suivant ${new Date(status.next_at * 1000).toLocaleTimeString()}` : "";
    if (status.mode === "weather") return this._weatherStatusText(status);
    switch (status.state) {
      case "starting": return `démarrage…${next}`;
      case "sending": return status.current ? `envoi de ${esc(status.current)} au cadre…` : "envoi du carrousel au cadre…";
      case "showing": return `affiche ${esc(status.current || "")}${next}`;
      case "waiting": return "hors de la plage horaire, en attente";
      case "carousel": return `le cadre fait tourner ${status.carousel?.length || ""} GIF tout seul${status.next_at ? `, nouveau tirage ${new Date(status.next_at * 1000).toLocaleTimeString()}` : ""}`;
      case "error": return `<span class="error">${esc(status.message || "erreur")}</span>`;
      default: return "";
    }
  }

  _onRoutineStatus(status) {
    if (this._otherDisplay(status)) return;
    this.state.routineStatus = status;
    if (this.state.status) this.state.status.routine = status;
    this._renderStatus();
    if (this.state.tab === "routines") this._drawRoutineList();
    if (this.state.tab === "weather") this._drawWeatherStatus();
    // The routine's name and the screen state come with the full status.
    if (status.state === "starting" || !status.active) this._refreshStatus();
  }

  async _routineAction(ev) {
    const button = ev.target.closest("button[data-act]");
    if (!button) return;
    const routine = this.state.routines.find((r) => r.id === button.closest("[data-routine]").dataset.routine);
    try {
      switch (button.dataset.act) {
        case "start":
          this._onRoutineStatus(await this._ws({ type: "idotmatrix/studio/routine_start", routine_id: routine.id }));
          break;
        case "stop":
          await this._ws({ type: "idotmatrix/studio/routine_stop" });
          this._onRoutineStatus({ active: null });
          break;
        case "next":
          await this._ws({ type: "idotmatrix/studio/routine_next" });
          break;
        case "edit":
          if (routine.mode === "weather") {
            this._weatherView = routine.id;
            this._show("weather");
          } else {
            this._editRoutine(routine);
          }
          break;
        case "delete":
          if (!this._armed(button, "Supprimer ?")) return;
          await this._ws({ type: "idotmatrix/studio/routine_delete", routine_id: routine.id });
          this._renderRoutines();
          break;
        default:
      }
    } catch (err) {
      alert(err.message || err);
    }
  }

  _editRoutine(routine) {
    const r = routine ? structuredClone(routine) : {
      id: newId("r"), name: "Ma routine", files: [], interval: 300, order: "random", mode: "ha", hours: null,
    };
    const picked = new Set(r.files);
    const items = this.state.items;
    const collections = this.state.collections || [];
    const main = this._main();
    const presets = [[30, "30 s"], [60, "1 min"], [300, "5 min"], [900, "15 min"], [1800, "30 min"], [3600, "1 h"]];
    main.innerHTML = `<div class="card routine-editor">
      <div class="row"><input type="text" id="rname" class="grow" value="${esc(r.name)}" placeholder="Nom de la routine"></div>
      <div class="row"><b>Changer toutes les</b>
        ${presets.map(([v, label]) => `<button class="act ghost small preset" data-v="${v}">${label}</button>`).join("")}
        <input type="number" id="rint" min="5" max="86400" value="${r.interval}"> s</div>
      <div class="row"><b>Ordre</b>
        <label><input type="radio" name="order" value="random" ${r.order === "random" ? "checked" : ""}> Aléatoire</label>
        <label><input type="radio" name="order" value="sequence" ${r.order === "sequence" ? "checked" : ""}> Dans l'ordre</label></div>
      <div class="row"><b>Mode</b>
        <label title="Home Assistant envoie un GIF à chaque changement : sélection illimitée, vrai aléatoire, plage horaire possible">
          <input type="radio" name="mode" value="ha" ${r.mode === "ha" ? "checked" : ""}> Piloté par HA</label>
        <label title="Jusqu'à 12 GIF envoyés une fois : le cadre les fait tourner tout seul, sans Bluetooth ensuite">
          <input type="radio" name="mode" value="carousel" ${r.mode === "carousel" ? "checked" : ""}> Carrousel du cadre (12 max)</label></div>
      <div class="row" id="hoursRow"><label><input type="checkbox" id="rhours" ${r.hours ? "checked" : ""}> Seulement entre</label>
        <input type="time" id="rfrom" value="${r.hours?.from || "08:00"}"> et <input type="time" id="rto" value="${r.hours?.to || "23:00"}"></div>
      <p class="muted small" id="rhint"></p>
      <div class="row"><b>GIF</b><select id="rsource" title="Choisis les GIF un par un, ou prends ceux d'une collection (suivie : ce qu'on y ajoute passe aussi)">
          <option value="">choisis un par un</option>
          ${collections.map((c) => `<option value="${esc(c.id)}" ${r.collection === c.id ? "selected" : ""}>🗂 collection « ${esc(c.name)} » (${c.files.length})</option>`).join("")}</select>
        <span class="muted small" id="rsourcehint"></span></div>
      <div class="toolbar" id="rpicktools"><b class="grow">GIF de l'ensemble <span id="rcount"></span></b>
        <input type="search" id="rq" placeholder="Filtrer…">
        <select id="rfolder" title="Dossier"><option value="*">Tous les dossiers</option>
          ${items.some((i) => !i.folder) ? `<option value="">📂 Sans dossier</option>` : ""}
          ${this._allFolders().map((f) => `<option value="${esc(f)}">📁 ${esc(f)}</option>`).join("")}</select>
        <label class="small"><input type="checkbox" id="rfav"> Favoris</label>
        <button class="act ghost small" id="rall">Tout</button><button class="act ghost small" id="rnone">Aucun</button></div>
      <div class="pick-grid" id="rpick"></div>
      <div class="row"><button class="act ghost" id="rcancel">Annuler</button><span class="grow"></span>
        <button class="act ghost" id="rsave">Enregistrer</button><button class="act" id="rsaveStart">Enregistrer et démarrer</button></div>
      <p class="error" id="rerr"></p></div>`;
    const $ = (sel) => main.querySelector(sel);
    const draw = () => {
      const q = $("#rq").value.trim().toLowerCase();
      const favOnly = $("#rfav").checked;
      const folder = $("#rfolder").value;
      $("#rpick").innerHTML = items.filter((i) => (!favOnly || i.favorite) && (!q || i.title.toLowerCase().includes(q))
          && (folder === "*" || (i.folder || "") === folder))
        .map((i) => `<label class="pick ${picked.has(i.file) ? "on" : ""}" data-file="${esc(i.file)}" title="${esc(i.title)}">
          <img alt=""><input type="checkbox" ${picked.has(i.file) ? "checked" : ""}><span class="ellipsis small">${esc(i.title)}</span></label>`).join("")
        || `<div class="muted">Aucun GIF dans la galerie.</div>`;
      for (const el of $("#rpick").querySelectorAll(".pick")) {
        const item = items.find((i) => i.file === el.dataset.file);
        this._sign(`${item.url}?v=${Math.round(item.modified)}`).then((url) => { el.querySelector("img").src = url; });
      }
      hint();
    };
    const hint = () => {
      const mode = main.querySelector("input[name=mode]:checked").value;
      const order = main.querySelector("input[name=order]:checked").value;
      const interval = Number($("#rint").value) || 0;
      $("#rcount").textContent = `(${picked.size} sélectionné${picked.size > 1 ? "s" : ""})`;
      const source = collections.find((c) => c.id === $("#rsource").value);
      $("#rpicktools").style.display = $("#rpick").style.display = source ? "none" : "";
      $("#rsourcehint").textContent = source ? `${source.files.length} GIF, suivis : ce que tu ajoutes à la collection passe aussi` : "";
      $("#hoursRow").style.display = mode === "ha" ? "" : "none";
      const chosenFiles = new Set(collections.find((c) => c.id === $("#rsource").value)?.files || picked);
      const chosen = items.filter((i) => chosenFiles.has(i.file));
      const slowest = Math.max(0, ...chosen.map((i) => i.estimate_s || 0));
      const notes = [];
      if (mode === "carousel" && chosenFiles.size > 12) {
        notes.push(order === "random" ? "Le cadre ne garde que 12 GIF : 12 sont tirés au hasard, puis re-tirés chaque heure."
          : "Le cadre ne garde que 12 GIF : seuls les 12 premiers seront utilisés.");
      }
      if (mode === "carousel") notes.push("Une fois envoyé, le carrousel tourne sans Bluetooth, même si Home Assistant est éteint.");
      if (mode === "ha" && slowest > interval * 0.8) {
        notes.push(`⚠ L'envoi du plus gros GIF prend ${duration(slowest)} : un intervalle plus long (ou des GIF plus légers) est conseillé.`);
      }
      $("#rhint").innerHTML = notes.join("<br>");
    };
    $("#rpick").onchange = (ev) => {
      const el = ev.target.closest(".pick");
      if (!el) return;
      if (ev.target.checked) picked.add(el.dataset.file); else picked.delete(el.dataset.file);
      el.classList.toggle("on", ev.target.checked);
      hint();
    };
    $("#rq").oninput = draw;
    $("#rsource").onchange = hint;
    $("#rfav").onchange = draw;
    $("#rfolder").onchange = draw;
    $("#rall").onclick = () => { for (const el of $("#rpick").querySelectorAll(".pick")) picked.add(el.dataset.file); draw(); };
    $("#rnone").onclick = () => { picked.clear(); draw(); };
    main.querySelectorAll(".preset").forEach((b) => { b.onclick = () => { $("#rint").value = b.dataset.v; hint(); }; });
    $("#rint").oninput = hint;
    main.querySelectorAll("input[name=mode], input[name=order]").forEach((el) => { el.onchange = hint; });
    $("#rcancel").onclick = () => this._show("routines");
    const save = async (start) => {
      // Keep the gallery order so "in order" follows the newest-first list.
      const files = items.map((i) => i.file).filter((f) => picked.has(f));
      const collection = $("#rsource").value || null;
      const routine = {
        id: r.id, name: $("#rname").value.trim() || "Routine", files: collection ? [] : files, collection,
        interval: Number($("#rint").value), order: main.querySelector("input[name=order]:checked").value,
        mode: main.querySelector("input[name=mode]:checked").value,
        hours: $("#rhours").checked ? { from: $("#rfrom").value, to: $("#rto").value } : null,
      };
      if (!collection && !files.length) { $("#rerr").textContent = "Choisis au moins un GIF, ou une collection."; return; }
      try {
        await this._ws({ type: "idotmatrix/studio/routine_save", routine });
        if (start) await this._ws({ type: "idotmatrix/studio/routine_start", routine_id: routine.id });
        this._show("routines");
      } catch (err) {
        $("#rerr").textContent = err.message || err;
      }
    };
    $("#rsave").onclick = () => save(false);
    $("#rsaveStart").onclick = () => save(true);
    draw();
  }

  // ---------------------------------------------------------------- weather

  /** Where one place's forecast comes from, in words. */
  _profilePlace(p) {
    const sources = this._weatherSources;
    if (!p) return "?";
    if (p.label) return p.label;
    if (p.source === "place") return p.place?.name?.split(",")[0] || "lieu à choisir";
    if (p.source === "entity") return sources?.entities.find((e) => e.entity_id === p.entity_id)?.name || p.entity_id;
    if (p.source === "zone") return sources?.zones.find((z) => z.entity_id === p.zone)?.name || p.zone;
    return sources?.home?.name || "Maison";
  }

  /** A weather view's places, « Lyon / Marseille » (views saved before profiles had one, at the top). */
  _weatherPlace(w) {
    const profiles = w?.profiles || (w ? [w] : []);
    return profiles.map((p) => this._profilePlace(p)).join(" / ") || "?";
  }

  _weatherStatusText(status) {
    const at = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const w = status.weather;
    const what = w ? `🌤 ${esc(w.place)}${w.temperature != null ? ` ${Math.round(w.temperature)}°` : ""} · prévisions de ${at(w.fetched)}` : "🌤 météo";
    const problem = status.message ? ` · <span class="error">${esc(status.message)}</span>` : "";
    switch (status.state) {
      case "starting": return `démarrage…${problem}`;
      case "busy": return `${what} · un autre envoi est en cours : la minute suivante attend qu'il finisse`;
      case "sending": return `${what} · envoi de la minute au cadre…`;
      case "updated": return `${what} · prévisions mises à jour`;
      case "showing": return `${what}${status.next_at ? ` · minute suivante à ${at(status.next_at)}` : ""}${problem}`;
      case "waiting": return "hors de la plage horaire, en attente";
      case "error": return `<span class="error">${esc(status.message || "météo indisponible")}</span>`;
      default: return problem;
    }
  }

  _newProfile() {
    return this._weatherSources?.home_assistant && !(this._wv?.weather.profiles || []).some((p) => p.source === "home")
      ? { source: "home" } : { source: "place", place: null };
  }

  _newWeatherView() {
    return {
      id: newId("w"), name: "Météo", files: [], interval: 1800, order: "sequence", mode: "weather", hours: null,
      weather: {
        // Without Home Assistant (the Windows build), the weather comes from a place typed in.
        profiles: [this._weatherSources?.home_assistant ? { source: "home" } : { source: "place", place: null }],
        switch_seconds: 15, seconds: true, animate: true, clock_color: "#78beff", clock_style: "digits", strip: "hours",
        hours_step: 3, hours_at: null, hour24: true, brightness: null, layout: null,
      },
    };
  }

  /** Views saved before profiles kept their one place at the top. */
  _weatherCfg(w) {
    const cfg = { switch_seconds: 15, seconds: true, animate: true, clock_color: "#78beff", strip: "hours", hours_step: 3, hours_at: null,
      hour24: true, brightness: null, ...structuredClone(w || {}) };
    if (!cfg.profiles?.length) {
      cfg.profiles = [{ source: cfg.source || "home", entity_id: cfg.entity_id, zone: cfg.zone, place: cfg.place, label: cfg.label }];
    }
    for (const key of ["source", "entity_id", "zone", "place", "label"]) delete cfg[key];
    return cfg;
  }

  _profileHtml(p, i, count) {
    const sources = this._weatherSources;
    const source = p.source === "entity" ? `entity:${p.entity_id}` : p.source === "zone" ? `zone:${p.zone}` : p.source;
    const option = (value, label) => `<option value="${esc(value)}" ${value === source ? "selected" : ""}>${label}</option>`;
    return `<div class="wprof" data-p="${i}">
      <div class="row"><b>${count > 1 ? `Ville ${i + 1}` : "Où"}</b><select data-k="source" class="grow">
        ${sources.home_assistant ? option("home", `🏠 ${esc(sources.home?.name || "Maison")} (la météo de Home Assistant)`) : ""}
        ${sources.entities.map((e) => option(`entity:${e.entity_id}`, `☁ ${esc(e.name)}`)).join("")}
        ${sources.zones.map((z) => option(`zone:${z.entity_id}`, `📍 Zone ${esc(z.name)}`)).join("")}
        ${option("place", "🔎 Un lieu, par son nom…")}</select>
        ${count > 1 ? `<button class="icon" data-delp title="Retirer cette ville">🗑</button>` : ""}</div>
      <div class="row" data-placerow ${p.source === "place" ? "" : "hidden"}>
        <input type="search" data-k="q" class="grow" placeholder="Ville, village…" value="${esc(p.place?.name || "")}">
        <button class="act ghost small" data-find>Chercher</button></div>
      <div class="chips" data-places></div>
      <div class="row"><span class="muted small">Nom écrit sur le cadre</span>
        <input type="text" data-k="label" class="grow" maxlength="40" placeholder="${esc(this._profilePlace({ ...p, label: null }))}" value="${esc(p.label || "")}"></div>
    </div>`;
  }

  /**
   * « Météo » tab: the time and the day ahead on the display, for one or more
   * places taking turns. A weather view is a routine (mode « weather »):
   * switched on here or in Routines, or placed in the planning.
   */
  async _renderWeather() {
    const main = this._main();
    main.innerHTML = `<p class="muted">Chargement…</p>`;
    let sources;
    let listed;
    try {
      [sources, listed] = await Promise.all([
        this._ws({ type: "idotmatrix/studio/weather_sources" }), this._ws({ type: "idotmatrix/studio/routines" })]);
    } catch (err) {
      main.innerHTML = `<p class="error">${esc(errorText(err))}</p>`;
      return;
    }
    if (this.state.tab !== "weather") return;
    this._weatherSources = sources;
    this.state.routines = listed.routines;
    this.state.routineStatus = listed.status;
    const views = listed.routines.filter((r) => r.mode === "weather");
    const saved = this._weatherView !== "new" && (views.find((r) => r.id === this._weatherView) || views[0]);
    const view = this._wv = structuredClone(saved || this._newWeatherView());
    view.weather = this._weatherCfg(view.weather);
    this._weatherView = view.id;
    this._weatherFound = {};
    // The screens: none yet (a view from before), the weather as it was, one per place.
    if (!view.weather.screens?.length) {
      const layout = view.weather.layout || {};
      const kept = Object.fromEntries(WEATHER_VIEW.filter((p) => !layout[p]?.hidden).map((p) => [p, { ...(layout[p] || {}) }]));
      view.weather.screens = view.weather.profiles.map((_p, i) => ({ place: i, seconds: view.weather.switch_seconds || 15, parts: structuredClone(kept) }));
    }
    this._wcur = Math.min(this._wcur || 0, view.weather.screens.length - 1);
    this._wplaying = false;
    main.innerHTML = `<div class="card">
      <div class="toolbar"><b class="grow">🌤 L'heure et la météo de la journée sur le cadre</b>
        <select id="wview" title="Vues météo enregistrées">
          ${views.map((r) => `<option value="${esc(r.id)}" ${r.id === view.id ? "selected" : ""}>${esc(r.name)}</option>`).join("")}
          <option value="new" ${saved ? "" : "selected"}>+ Nouvelle vue météo</option></select></div>
      <div class="wgrid">
        <div class="wside">
          <div class="chips wnums" id="wpagenums" title="Les écrans qui tournent : clique un numéro pour le garder à l'aperçu et le régler"></div>
          <div class="woverlay" id="wpresets" style="display:none"><div class="box"><b>Nouvel écran</b>
            <p class="muted small">Vide, ou déjà rempli : tu le changes ensuite.</p>
            <div class="grid">${WEATHER_PRESETS.map(([k, label], i) => `<button class="chip-btn ${i < 2 ? "first" : ""}" data-wpreset="${k}">${label}</button>`).join("")}</div>
            <p class="muted small">Ou une copie d'un de tes écrans :</p>
            <div class="grid" id="wcopygrid"></div>
            <div class="row"><span class="grow"></span><button class="act ghost small" id="wpresetcancel">Annuler</button></div></div></div>
          <canvas id="wled" class="wled" width="256" height="256" title="Touche une partie pour la régler, glisse-la pour la déplacer"></canvas>
          <div class="chips" id="wzones">${[["", "Tout"], ["clock", "Heure"], ["date", "Date"], ["name", "Ville"], ["today", "Aujourd'hui"], ["strip", "En bas"], ["pages", "Pages"]]
            .map(([z, label]) => `<button class="chip-btn ${z === (this._wzone || "") ? "on" : ""}" data-wzone="${z}">${label}</button>`).join("")}</div>
          <div class="row" id="wedit" style="display:none">
            <button class="act ghost small" data-wedit="smaller" title="Plus petit">A↓</button><button class="act ghost small" data-wedit="bigger" title="Plus grand">A↑</button>
            ${[["-1,0", "←", "1 LED à gauche"], ["1,0", "→", "1 LED à droite"], ["0,-1", "↑", "1 LED plus haut"], ["0,1", "↓", "1 LED plus bas"]]
              .map(([m, icon, title]) => `<button class="act ghost small" data-wmove="${m}" title="${title}">${icon}</button>`).join("")}
            <button class="act ghost small" data-wedit="remove" title="L'enlever de cet écran">Retirer</button><button class="act ghost small" data-wedit="reset" title="Remettre à sa place">↺</button>
            <label class="small" title="Une ligne de cette couleur autour (du noir se voit avec : une LED noire est éteinte)"><input type="checkbox" id="wolOn"> contour</label><input type="color" id="wol" value="#ffffff">
            <span id="walign">${[["left", "⇤", "À gauche"], ["center", "↔", "Au centre"], ["right", "⇥", "À droite"]]
              .map(([a, icon, title]) => `<button class="act ghost small" data-walign="${a}" title="${title}">${icon}</button>`).join("")}</span>
            <span class="muted small">glisse-la sur l'aperçu</span></div>
          <div class="row" id="wnamerow" style="display:none"><input type="text" id="wscrname" class="grow" maxlength="40"></div>
          <div class="row" id="wcdrow" style="display:none"><input type="text" id="wcdtitle" class="grow" maxlength="40" placeholder="Vacances aux Maldives">
            <input type="date" id="wcddate"><label><input type="checkbox" id="wcdweekend"> le week-end</label></div>
          <div id="wscreen">
            <div class="row"><b id="wscrtitle">Écran 1</b></div>
            <div class="row small" id="wscrparts"></div>
            <div class="chips" id="waddparts" title="Clique ce que tu veux, puis +"></div>
            <div class="row small"><button class="act small" id="waddsel" disabled>+ Ajouter</button>
              reste <input type="number" id="wscrsec" min="1" max="600"> s
              <span id="wscrplacerow">· météo de <select id="wscrplace"></select></span></div>
            <div class="row small"><label><input type="checkbox" id="wscrhours"> seulement de</label>
              <input type="number" id="wscrfrom" min="0" max="23"> h à <input type="number" id="wscrto" min="0" max="24"> h</div>
            <div class="row small"><button class="act ghost small" id="wscrleft">← avant</button><button class="act ghost small" id="wscrright">après →</button>
              <button class="act ghost small" id="wscrdel" title="Supprimer cet écran">🗑 Écran</button></div></div>
          <div class="row small" id="wdetails"><b>Aujourd'hui</b> <label><input type="checkbox" data-wdetail="icon"> icône</label><label><input type="checkbox" data-wdetail="temp"> température</label><label><input type="checkbox" data-wdetail="minmax"> min/max</label><label><input type="checkbox" data-wdetail="drop"> goutte</label></div>
          <div class="row">
            <button class="act ghost small ${this._wgrid ? "on" : ""}" id="wgridbtn" title="Un quadrillage toutes les 8 LED, pour aligner">▦ Grille</button>
            <button class="act ghost small" id="wresetall" title="Remettre chaque partie de cet écran à sa place et à sa taille">↺ Tout remettre</button></div>
          <p class="muted small">Un numéro au-dessus de l'aperçu règle cet écran, « + » en ajoute un, ▶ les fait défiler.</p>
        </div>
        <div class="wform">
          <div class="row"><b>Nom</b><input type="text" id="wname" class="grow" value="${esc(view.name)}"></div>
          <div id="wprofiles" data-zone="name"></div>
          <p class="error" id="werr"></p>
          <div class="row" data-zone="clock"><b>Style</b>
            <label><input type="radio" name="wstyle" value="digits"> chiffres</label>
            <label><input type="radio" name="wstyle" value="flip"> cartes qui basculent (HTC)</label></div>
          <div class="row" data-zone="clock"><b>Heure</b>
            <label><input type="radio" name="wh24" value="24"> 24 h</label><label><input type="radio" name="wh24" value="12"> 12 h</label>
            <label title="Les secondes défilent sur le cadre (il joue la minute tout seul)"><input type="checkbox" id="wsec"> secondes</label>
            <label title="Couleur de l'heure">couleur <input type="color" id="wcolor"></label>
            <label title="La pluie tombe, les rayons du soleil tournent… (une image toutes les demi-secondes, un peu plus long à envoyer)"><input type="checkbox" id="wanim"> icône animée</label></div>
          <div class="row" data-zone="clock"><b>Format</b>
            <input type="text" id="wtformat" maxlength="20" placeholder="HH:mm (vide : l'habituel)">
            <span class="muted small">HH 14 · H 9 · hh 02 · h 2 · mm minutes · ss secondes · tt AM/PM. Avec ss, les secondes sont dans l'heure.</span></div>
          <div class="row" data-zone="date"><b>Date</b>
            <input type="text" id="wdformat" maxlength="30" placeholder="ww d (vide : l'habituel)">
            <span class="muted small">dddd LUNDI · ddd LUN · ww LU · dd 03 · d 3 · mmmm NOVEMBRE · mmm NOV · mm 11 · yyyy 2026 · yy 26. Ex. : dd/mm · mm/dd/yy · ddd d mmm</span></div>
          <div class="row" data-zone="clock"><b>Secondes</b>
            ${[["auto", "auto"], ["digits", "chiffres"], ["bar", "barre"], ["ring", "anneau"]]
              .map(([v, label]) => `<label><input type="radio" name="wsstyle" value="${v}"> ${label}</label>`).join("")}
            <label><input type="checkbox" id="wscolorOn"> couleur à part</label> <input type="color" id="wscolor">
            <span class="muted small">−/+ : épaisseur de la barre, taille des chiffres ou de l'anneau</span></div>
          <div class="row" data-zone="today"><b>La goutte</b>
            <label><input type="radio" name="wdrop" value="rain"> risque de pluie</label>
            <label><input type="radio" name="wdrop" value="humidity"> humidité</label></div>
          <div class="row" data-zone="strip"><b>En bas</b>
            <label><input type="radio" name="wstrip" value="hours"> les heures</label>
            <label><input type="radio" name="wstrip" value="days"> les jours</label>
            <label><input type="radio" name="wstrip" value="sun"> lever et coucher du soleil</label></div>
          <div class="row" id="whoursRow" data-zone="strip"><b>4 heures</b>
            <select id="whmode"><option value="step">toutes les</option><option value="at">à heures fixes</option></select>
            <select id="wstep">${[1, 2, 3, 4, 6].map((h) => `<option value="${h}">${h} h</option>`).join("")}</select>
            <span id="wat">${[0, 1, 2, 3].map((i) => `<input type="number" min="0" max="23" data-at="${i}" placeholder="h">`).join(" ")}</span></div>
          <div class="row" data-zone="today"><b>Luminosité</b>
            <label title="Le cadre baisse sa luminosité au coucher du soleil de la première ville et la remonte au lever">
              <input type="checkbox" id="wbright"> selon le soleil</label>
            <span id="wbrightRow">jour <input type="range" id="wday" min="5" max="100" step="5"> <span id="wdayv"></span>
              nuit <input type="range" id="wnight" min="5" max="100" step="5"> <span id="wnightv"></span></span></div>
          <div class="row" data-zone="today"><b>Météo</b><span class="muted small">mise à jour toutes les</span>
            <select id="wrefresh">${WEATHER_REFRESH.map(([v, label]) => `<option value="${v}" ${view.interval === v ? "selected" : ""}>${label}</option>`).join("")}</select></div>
          <div data-zone="agenda">
            <div class="row"><b>Agenda</b>
              <label><input type="radio" name="wastyle" value="list"> liste</label>
              <label><input type="radio" name="wastyle" value="timeline"> frise</label>
              <b>Défilement</b>${[["slow", "lent"], ["normal", "normal"], ["fast", "rapide"], ["faster", "très rapide"]]
                .map(([v, label]) => `<label><input type="radio" name="wspeed" value="${v}"> ${label}</label>`).join("")}</div>
            <div class="row" id="wcalendars">${(sources.calendars || []).map((c) => `<label><input type="checkbox" data-cal="${esc(c.entity_id)}"> 📅 ${esc(c.name)}</label>`).join("")}</div>
            <div class="row"><textarea id="wics" class="grow" rows="2" placeholder="Liens iCal d'autres agendas (Google : Paramètres → Adresse secrète au format iCal), un par ligne"></textarea></div>
            <div id="wicsstatus" class="small"></div>
            <div class="row"><b>Mes rendez-vous</b><span class="muted small">(en plus des agendas)</span></div>
            <div id="wevents"></div>
            <div class="row"><button class="act ghost small" id="waddevent">+ Événement</button></div>
          </div>
          <div data-zone="pages">
            <div class="row"><b>Réglages des pages</b><span class="muted small">ce que montrent les écrans qui ont ces parties</span></div>
            <div class="row"><b>Anniversaires</b></div>
            <div id="wbirthdays"></div>
            <div class="row"><button class="act ghost small" id="waddbirthday">+ Anniversaire</button></div>
            <div id="wtoday"></div>
            <div class="row"><b>Saint</b><input type="text" id="wsainttitle" maxlength="24" placeholder="BONNE FÊTE">
              <label><input type="checkbox" id="wsaintto"> « À » / « AUX »</label></div>
            <div class="row"><b>N'oubliez pas</b><span class="muted small">l'agenda du jour, et :</span></div>
            <div id="wreminders"></div>
            <div class="row"><button class="act ghost small" id="waddreminder">+ Rappel</button></div>
            <div class="row"><b>Notes</b></div>
            <div id="wnotes"></div>
            <div class="row"><button class="act ghost small" id="waddnote">+ Note</button></div>
            <p class="muted small" id="wpagesToday"></p>
          </div>
          <p class="small" id="wsummary"></p>
          <p class="muted small" id="wsize"></p>
          <p class="muted small" id="wstatus"></p>
          <div class="row">${saved ? `<button class="icon" id="wdelete" title="Supprimer cette vue">🗑</button>` : ""}<span class="grow"></span>
            <button class="act ghost" id="wstop" hidden title="Le cadre redevient libre jusqu'au prochain changement">Arrêter</button></div>
          <p class="muted small">Chaque changement s'affiche sur le cadre en direct, sans rien appuyer (« Arrêter » rend le cadre libre jusqu'au suivant).
            Chaque minute part un seul GIF qui contient toute la minute : le cadre fait défiler
            les secondes, anime l'icône et change de ville tout seul, sans Bluetooth entre deux envois, jamais pendant
            un autre envoi. Un emoji tapé dans le nom (🏠, 🤣…) est dessiné en petit.
            Pour ne l'afficher qu'à certaines heures, mets cette vue au 📅 Planning (onglet Routines).</p>
        </div></div></div>`;
    const $ = (sel) => main.querySelector(sel);
    const w = view.weather;
    // Options outside the places: set once from the view, then read back on each change.
    main.querySelector(`input[name=wh24][value="${w.hour24 === false ? "12" : "24"}"]`).checked = true;
    main.querySelector(`input[name=wstrip][value="${w.strip || "hours"}"]`).checked = true;
    main.querySelector(`input[name=wstyle][value="${w.clock_style === "flip" ? "flip" : "digits"}"]`).checked = true;
    $("#wsec").checked = w.seconds !== false;
    $("#wanim").checked = w.animate !== false;
    $("#wtformat").value = w.time_format || "";
    $("#wdformat").value = w.date_format || "";
    main.querySelector(`input[name=wsstyle][value="${w.seconds_style || "auto"}"]`).checked = true;
    $("#wscolorOn").checked = !!w.seconds_color;
    $("#wscolor").value = w.seconds_color || "#ffffff";
    main.querySelector(`input[name=wdrop][value="${w.drop === "humidity" ? "humidity" : "rain"}"]`).checked = true;
    main.querySelector(`input[name=wastyle][value="${w.agenda_style === "timeline" ? "timeline" : "list"}"]`).checked = true;
    main.querySelector(`input[name=wspeed][value="${w.scroll_speed || "normal"}"]`).checked = true;
    main.querySelectorAll("[data-cal]").forEach((box) => { box.checked = (w.agenda_calendars || []).includes(box.dataset.cal); });
    $("#wics").value = (w.agenda_ics || []).join("\n");
    $("#wsainttitle").value = w.saint_title || "";
    $("#wsaintto").checked = w.saint_to !== false;
    this._drawBirthdays(w.birthdays || []);
    this._drawReminders(w.reminders || []);
    this._drawEvents(w.events || []);
    this._wtodayKey = "";
    this._drawNotes(w.notes || []);
    $("#wcolor").value = w.clock_color || "#78beff";
    $("#whmode").value = w.hours_at?.length ? "at" : "step";
    $("#wstep").value = String(w.hours_step || 3);
    for (const input of main.querySelectorAll("[data-at]")) input.value = w.hours_at?.[Number(input.dataset.at)] ?? "";
    $("#wbright").checked = !!w.brightness;
    $("#wday").value = w.brightness?.day ?? 100;
    $("#wnight").value = w.brightness?.night ?? 20;
    this._drawProfiles();
    const form = $(".wform");
    form.oninput = (ev) => this._weatherInput(ev);
    form.onchange = (ev) => this._weatherInput(ev, true);
    form.onclick = (ev) => this._weatherClick(ev);
    form.onkeydown = (ev) => {
      if (ev.key === "Enter" && ev.target.dataset?.k === "q") this._weatherFind(Number(ev.target.closest("[data-p]").dataset.p));
    };
    $("#wview").onchange = (ev) => { this._weatherView = ev.target.value; this._renderWeather(); };
    if ($("#wdelete")) {
      $("#wdelete").onclick = async (ev) => {
        if (!this._armed(ev.currentTarget, "Supprimer ?")) return;
        await this._ws({ type: "idotmatrix/studio/routine_delete", routine_id: this._wv.id });
        this._weatherView = null;
        this._renderWeather();
      };
    }
    this._weatherOptions();
    this._drawWeatherStatus();
    this._setupWeatherEditor();
    this._pickWeatherZone(this._wzone || "");
    this._weatherPreview(true, false);  // opening the tab changes nothing on the display
  }

  // ------------------------------------------------- weather: parts on the preview

  /** Picking a part (touching it on the preview, or its chip) keeps only its settings in view. */
  _pickWeatherZone(zone) {
    const main = this._main();
    this._wzone = zone;
    main.querySelectorAll("#wzones [data-wzone]").forEach((chip) => chip.classList.toggle("on", chip.dataset.wzone === zone));
    // Nothing picked: every setting.
    main.querySelectorAll(".wform [data-zone]").forEach((row) => {
      const wanted = zone === "seconds" ? "clock" : zone;  // the seconds' settings are the time's
      row.classList.toggle("wzone-off", !!wanted && row.dataset.zone !== wanted);
    });
    main.querySelectorAll(".wform [data-zone]").forEach((row) => { row.style.display = row.classList.contains("wzone-off") ? "none" : ""; });
    this._drawWeatherEdit();
    this._outlineWeatherPart();
  }

  /** The screen being set (its number above the preview). */
  _wscreen() {
    const screens = this._wv.weather.screens;
    return screens[Math.min(this._wcur || 0, screens.length - 1)];
  }

  _weatherPart(name) {
    const screen = this._wscreen();
    screen.parts ||= {};
    return (screen.parts[name] ||= {});
  }

  _drawWeatherEdit() {
    const main = this._main();
    const zone = this._wzone;
    main.querySelector("#wedit").style.display = zone ? "" : "none";
    if (!zone) {
      main.querySelectorAll("[data-wpick]").forEach((n) => n.classList.remove("on"));
      return;
    }
    main.querySelectorAll("[data-wpick]").forEach((n) => n.classList.toggle("on", n.dataset.wpick === zone));
    const p = this._wscreen().parts?.[zone];  // read only: a part not on this screen stays off it
    const editable = !!WEATHER_SIZES[zone] && !!p;
    main.querySelector("#wedit").style.display = editable ? "" : "none";
    main.querySelector("#wcdrow").style.display = editable && zone === "countdown" ? "" : "none";
    main.querySelector("#wnamerow").style.display = editable && zone === "name" ? "" : "none";
    if (editable && zone === "name") {  // this screen's own name, else the city's
      const city = this._wv.weather.profiles[this._wscreen().place || 0];
      main.querySelector("#wscrname").placeholder = `Nom sur cet écran (${city ? this._profilePlace(city) || "la ville" : "la ville"})`;
      main.querySelector("#wscrname").value = p.title || "";
    }
    if (!editable) return;
    main.querySelector("#wolOn").checked = !!p.outline;
    main.querySelector("#wol").value = p.outline || "#ffffff";
    main.querySelector("#wcdtitle").value = p.title || "";
    main.querySelector("#wcdweekend").checked = p.date === "weekend";
    main.querySelector("#wcddate").value = p.date && p.date !== "weekend" ? p.date.slice(0, 10) : "";
    main.querySelector("#wcddate").disabled = p.date === "weekend";
    const [low, high] = WEATHER_SIZES[zone];
    const size = p.size || this._usualSize(zone);
    main.querySelector('[data-wedit="smaller"]').disabled = size <= low;
    main.querySelector('[data-wedit="bigger"]').disabled = size >= high;
    main.querySelector("#walign").style.display = zone === "name" ? "" : "none";
    main.querySelectorAll("[data-walign]").forEach((b) => b.classList.toggle("on", (p.align || "center") === b.dataset.walign));
  }

  _drawWeatherShows() {
    const main = this._main();
    const w = this._wv.weather;
    main.querySelectorAll("[data-wdetail]").forEach((box) => { box.checked = !(w.today_hide || []).includes(box.dataset.wdetail); });
  }

  _usualSize(zone) {
    const strip = this._wv.weather.clock_style === "flip" ? 1 : 2;
    return { clock: 2, seconds: 1, date: 1, name: 1, today: 2, strip, days: strip, sun: strip }[zone] ?? 2;
  }

  _outlineWeatherPart() {
    const canvas = this._main().querySelector("#wled");
    if (!canvas || !this._weatherDrawn) return;
    const ctx = canvas.getContext("2d");
    const k = canvas.width / 64;
    if (this._wgrid) {  // lines every 8 LEDs, the middle ones brighter
      for (let i = 8; i < 64; i += 8) {
        ctx.fillStyle = i === 32 ? "rgba(74,163,255,.55)" : "rgba(255,255,255,.18)";
        ctx.fillRect(i * k - 0.5, 0, 1, canvas.height);
        ctx.fillRect(0, i * k - 0.5, canvas.width, 1);
      }
    }
    const box = this._weatherBoxes?.[this._wzone];
    if (!box) return;
    ctx.strokeStyle = "#4aa3ff";
    ctx.lineWidth = 3;
    ctx.strokeRect(box[0] * k - 1, box[1] * k - 1, (box[2] - box[0]) * k + 2, (box[3] - box[1]) * k + 2);
  }

  /** The part under a point of the preview (in LEDs): where it is now, else by its usual rows. */
  _weatherPartAt(x, y) {
    const on = this._wscreen().parts || {};
    const hit = Object.entries(this._weatherBoxes || {})
      .find(([k, b]) => on[k] && x >= b[0] - 1 && x <= b[2] + 1 && y >= b[1] - 1 && y <= b[3] + 1);
    if (hit) return hit[0];
    return [["clock", 0, 14], ["name", 14, 21], ["today", 21, 37], ["strip", 37, 64]].find(([k, a, b]) => on[k] && y >= a && y < b)?.[0] || "";
  }

  _setupWeatherEditor() {
    const main = this._main();
    const canvas = main.querySelector("#wled");
    const point = (ev) => {
      const rect = canvas.getBoundingClientRect();
      return [((ev.clientX - rect.left) / rect.width) * 64, ((ev.clientY - rect.top) / rect.height) * 64];
    };
    let drag = null;
    canvas.onpointerdown = (ev) => {
      const [x, y] = point(ev);
      const hit = this._weatherPartAt(x, y);
      const p = (hit && this._wscreen().parts?.[hit]) || {};
      const box = this._weatherBoxes?.[hit];
      drag = { x, y, hit, moved: false, dx: p.dx || 0, dy: p.dy || 0, box: box ? [...box] : null };
      canvas.setPointerCapture?.(ev.pointerId);
    };
    canvas.onpointermove = (ev) => {
      if (!drag || !drag.hit) return;
      const [x, y] = point(ev);
      const dx = Math.round(x - drag.x);
      const dy = Math.round(y - drag.y);
      if (!drag.moved && Math.abs(dx) + Math.abs(dy) < 2) return;
      if (!drag.moved && drag.hit !== this._wzone) this._pickWeatherZone(drag.hit);  // grabbed and dragged in one go
      drag.moved = true;
      // With the grid shown, an edge or the middle sticks to a line within 2 LEDs.
      const snap = (edges, d) => {
        let best = d;
        let gap = 3;
        for (const edge of edges) {
          const line = Math.round((edge + d) / 8) * 8;
          if (Math.abs(line - edge - d) < gap) { gap = Math.abs(line - edge - d); best = line - edge; }
        }
        return best;
      };
      const b = drag.box;
      const [sx, sy] = this._wgrid && b
        ? [snap([b[0], b[2], (b[0] + b[2]) / 2], dx), snap([b[1], b[3], (b[1] + b[3]) / 2], dy)] : [dx, dy];
      Object.assign(this._weatherPart(this._wzone), {
        dx: Math.max(-63, Math.min(63, Math.round(drag.dx + sx))), dy: Math.max(-63, Math.min(63, Math.round(drag.dy + sy))),
      });
      if (!this._weatherDragging) {
        this._weatherDragging = true;
        this._weatherPreview().finally(() => { this._weatherDragging = false; });
      }
    };
    // A tap picks (a click: phones may cancel the pointer); a drag that moved saves on release.
    let dragged = false;
    canvas.onpointerup = canvas.onpointercancel = () => {
      if (!drag) return;
      dragged = drag.moved;
      if (drag.moved) this._weatherPreview(true);
      drag = null;
    };
    canvas.onclick = (ev) => {
      if (dragged) {
        dragged = false;
        return;
      }
      const [x, y] = point(ev);
      const hit = this._weatherPartAt(x, y);
      this._pickWeatherZone(hit === this._wzone ? "" : hit);
    };
    main.querySelector("#wzones").onclick = (ev) => {
      const chip = ev.target.closest("[data-wzone]");
      if (chip) this._pickWeatherZone(chip.dataset.wzone);
    };
    main.querySelector("#wgridbtn").onclick = (ev) => {
      this._wgrid = !this._wgrid;
      ev.currentTarget.classList.toggle("on", this._wgrid);
      this._weatherPreview();
    };
    // The screens: a number sets that one, « + » adds one (empty or a preset), ▶ shows them in turn.
    main.querySelector("#wpagenums").onclick = (ev) => {
      const chip = ev.target.closest("[data-wnum]");
      if (!chip) return;
      if (chip.dataset.wnum === "plus") {
        main.querySelector("#wcopygrid").innerHTML = this._wv.weather.screens.map((_sc, i) => `<button class="chip-btn" data-wcopy="${i}">${i + 1} · ${esc((this._wtitles || [])
          .find((t) => t.screen === i)?.title || "Écran")}</button>`).join("");
        main.querySelector("#wpresets").style.display = "";
        return;
      }
      if (chip.dataset.wnum === "play") this._wplaying = !this._wplaying;
      else {
        this._wcur = Number(chip.dataset.wnum);
        this._wplaying = false;
      }
      this._pickWeatherZone("");
      this._drawWeatherScreen();
      this._drawProfiles();
      this._weatherPreview();
    };
    main.querySelector("#wpresets").onclick = (ev) => {
      if (ev.target === ev.currentTarget || ev.target.closest("#wpresetcancel")) {
        ev.currentTarget.style.display = "none";
        return;
      }
      const copy = ev.target.closest("[data-wcopy]");
      const chip = ev.target.closest("[data-wpreset]");
      if (!chip && !copy) return;
      const screens = this._wv.weather.screens;
      if (copy) screens.push(structuredClone(screens[Number(copy.dataset.wcopy)]));
      else {
        const key = chip.dataset.wpreset;
        const parts = key === "empty" ? [] : key === "weather" ? WEATHER_VIEW.filter((p) => p !== "seconds") : ["clock", key];
        screens.push({ place: 0, seconds: 15, parts: Object.fromEntries(parts.map((p) => [p, key === "countdown" && p === key ? { date: "weekend" } : {}])) });
      }
      this._wcur = screens.length - 1;
      this._wplaying = false;
      main.querySelector("#wpresets").style.display = "none";
      this._pickWeatherZone("");
      this._drawWeatherScreen();
      this._drawProfiles();
      this._weatherPreview(true);
    };
    main.querySelector("#wscreen").onclick = (ev) => {
      const screens = this._wv.weather.screens;
      // Adding: click what you want (it lights up, click again to leave it), then « + ».
      const pick = ev.target.closest("[data-wadd]");
      if (pick) {
        const picked = this._wpicked ||= new Set();
        if (picked.has(pick.dataset.wadd)) picked.delete(pick.dataset.wadd);
        else picked.add(pick.dataset.wadd);
        this._drawWeatherScreen();
        return;
      }
      if (ev.target.closest("#waddsel")) {
        const added = [...(this._wpicked || [])];
        if (!added.length) return;
        const screen = this._wscreen();
        screen.parts = { ...(screen.parts || {}), ...Object.fromEntries(added.map((p) => [p, p === "countdown" ? { date: "weekend" } : {}])) };
        this._wpicked.clear();
        this._drawWeatherScreen();
        this._pickWeatherZone(added.at(-1));
        this._weatherPreview(true);
        return;
      }
      const off = ev.target.closest("[data-wunpart]");
      const name = ev.target.closest("[data-wpick]");
      if (off) {
        delete this._wscreen().parts[off.dataset.wunpart];
        if (this._wzone === off.dataset.wunpart) this._pickWeatherZone("");
      } else if (name) {
        this._pickWeatherZone(name.dataset.wpick === this._wzone ? "" : name.dataset.wpick);
        return;
      } else if (ev.target.closest("#wscrleft, #wscrright")) {
        const to = this._wcur + (ev.target.closest("#wscrleft") ? -1 : 1);
        if (to < 0 || to >= screens.length) return;
        [screens[this._wcur], screens[to]] = [screens[to], screens[this._wcur]];
        this._wcur = to;
      } else if (ev.target.closest("#wscrdel")) {
        if (screens.length < 2 || !this._armed(ev.target.closest("#wscrdel"), "Supprimer ?")) return;
        screens.splice(this._wcur, 1);
        this._wcur = Math.max(0, this._wcur - 1);
        this._pickWeatherZone("");
        this._pruneProfiles();
        this._drawProfiles();
      } else return;
      this._drawWeatherScreen();
      this._weatherPreview(true);
    };
    main.querySelector("#wscreen").onchange = (ev) => {
      const screen = this._wscreen();
      const t = ev.target;
      if (t.id === "wscrsec") screen.seconds = Math.max(1, Math.min(600, Number(t.value) || 15));
      else if (t.id === "wscrplace") {
        screen.place = Number(t.value);
        this._drawProfiles();
      }
      else if (["wscrhours", "wscrfrom", "wscrto"].includes(t.id)) {
        if (main.querySelector("#wscrhours").checked) {
          screen.from = Math.max(0, Math.min(23, Number(main.querySelector("#wscrfrom").value) || 0));
          screen.to = Math.max(0, Math.min(24, Number(main.querySelector("#wscrto").value) || 0));
        } else {
          delete screen.from;
          delete screen.to;
        }
      } else return;
      this._drawWeatherScreen();
      this._weatherPreview(true);
    };
    // The outline, the countdown's title and date: on the part picked.
    main.querySelector("#wolOn").onchange = main.querySelector("#wol").onchange = () => {
      if (!this._wzone) return;
      this._weatherPart(this._wzone).outline = main.querySelector("#wolOn").checked ? main.querySelector("#wol").value : null;
      this._weatherPreview(true);
    };
    main.querySelector("#wscrname").oninput = () => {
      this._weatherPart("name").title = main.querySelector("#wscrname").value.trim() || null;
      clearTimeout(this._weatherTypeTimer);
      this._weatherTypeTimer = setTimeout(() => this._weatherPreview(true), 900);
    };
    main.querySelector("#wcdtitle").oninput = () => {
      this._weatherPart("countdown").title = main.querySelector("#wcdtitle").value.trim() || null;
      clearTimeout(this._weatherTypeTimer);
      this._weatherTypeTimer = setTimeout(() => this._weatherPreview(true), 900);
    };
    main.querySelector("#wcddate").onchange = main.querySelector("#wcdweekend").onchange = () => {
      this._weatherPart("countdown").date = main.querySelector("#wcdweekend").checked ? "weekend" : main.querySelector("#wcddate").value || null;
      this._drawWeatherEdit();
      this._weatherPreview(true);
    };
    this._drawWeatherScreen();
    main.querySelector("#wdetails").onchange = () => {
      this._wv.weather.today_hide = [...main.querySelectorAll("[data-wdetail]")].filter((b) => !b.checked).map((b) => b.dataset.wdetail);
      this._weatherPreview(true);
    };
    this._drawWeatherShows();
    main.querySelector("#wresetall").onclick = () => {  // this screen's parts back in place, at their size
      const screen = this._wscreen();
      screen.parts = Object.fromEntries(Object.entries(screen.parts || {}).map(([k, p]) => [k,
        Object.fromEntries(Object.entries({ title: p.title, date: p.date, outline: p.outline }).filter(([, v]) => v != null))]));
      this._drawWeatherShows();
      this._drawWeatherEdit();
      this._weatherPreview(true);
    };
    main.querySelector("#walign").onclick = (ev) => {
      const button = ev.target.closest("[data-walign]");
      if (!button) return;
      ev.stopPropagation();
      this._weatherPart("name").align = button.dataset.walign;
      this._drawWeatherEdit();
      this._weatherPreview(true);
    };
    main.querySelector("#wedit").onclick = (ev) => {
      const arrow = ev.target.closest("[data-wmove]");
      if (arrow && this._wzone) {
        const [mx, my] = arrow.dataset.wmove.split(",").map(Number);
        const p = this._weatherPart(this._wzone);
        p.dx = Math.max(-63, Math.min(63, (p.dx || 0) + mx));
        p.dy = Math.max(-63, Math.min(63, (p.dy || 0) + my));
        this._weatherPreview(true);
        return;
      }
      const button = ev.target.closest("[data-wedit]");
      if (!button || !this._wzone) return;
      const p = this._weatherPart(this._wzone);
      const size = p.size || this._usualSize(this._wzone);
      if (button.dataset.wedit === "smaller") p.size = Math.max(WEATHER_SIZES[this._wzone][0], size - 1);
      else if (button.dataset.wedit === "bigger") p.size = Math.min(WEATHER_SIZES[this._wzone][1], size + 1);
      else if (button.dataset.wedit === "remove") {
        delete this._wscreen().parts[this._wzone];
        this._pickWeatherZone("");
        this._drawWeatherScreen();
      } else {
        this._wscreen().parts[this._wzone] = Object.fromEntries(Object.entries({ title: p.title, date: p.date, outline: p.outline })
          .filter(([, v]) => v != null));
      }
      this._drawWeatherShows();
      this._drawWeatherEdit();
      this._weatherPreview(true);
    };
  }

  /** The city of the screen being set (each screen has its own; several may share one). */
  _drawProfiles() {
    const main = this._main();
    const w = this._wv.weather;
    const i = Math.min(this._wscreen()?.place || 0, w.profiles.length - 1);
    const p = w.profiles[i];
    const shared = (w.screens || []).map((sc, n) => n).filter((n) => n !== this._wcur && (w.screens[n].place || 0) === i);
    const cities = (w.screens || []).filter((sc) => ["name", "today", "strip"].some((k) => sc.parts?.[k])).length;
    main.querySelector("#wprofiles").innerHTML = `<div class="row"><b>Ville de l'écran ${(this._wcur || 0) + 1}</b>
        ${shared.length ? `<span class="muted small">(la même que l'écran ${shared.map((n) => n + 1).join(", ")} : la changer ici ne change que cet écran)</span>` : ""}</div>`
      + this._profileHtml(p, i, 1)
      + `<div class="row">${cities > 1 ? `<span class="muted small">changer de ville toutes les</span>
          <input type="number" id="wswitch" min="1" max="600" value="${w.switch_seconds || 15}"> s` : ""}
        <label title="Chaque ville montre l'heure qu'il est là-bas, avec sa météo"><input type="checkbox" id="wcitytime" ${w.city_time !== false ? "checked" : ""}> l'heure de chaque ville</label></div>`;
    main.querySelector(`[data-p="${i}"] [data-k=source]`).value =
      p.source === "entity" ? `entity:${p.entity_id}` : p.source === "zone" ? `zone:${p.zone}` : p.source;
  }

  /** The city ``i`` for this screen alone: when other screens show it too, this screen gets a copy
   * (changing it then leaves them alone). Returns its number. */
  _ownProfile(i) {
    const w = this._wv.weather;
    const others = (w.screens || []).some((sc, n) => n !== this._wcur && (sc.place || 0) === i);
    if (!others || w.profiles.length >= 12) return i;
    w.profiles.push(structuredClone(w.profiles[i]));
    this._wscreen().place = w.profiles.length - 1;
    return w.profiles.length - 1;
  }

  /** Cities no screen shows any more are dropped (the screens' numbers follow). */
  _pruneProfiles() {
    const w = this._wv.weather;
    if (!w.screens?.length) return false;
    const used = [...new Set(w.screens.map((sc) => Math.min(sc.place || 0, w.profiles.length - 1)))].sort((a, b) => a - b);
    if (used.length === w.profiles.length) return false;
    const renumber = Object.fromEntries(used.map((p, k) => [p, k]));
    w.profiles = used.map((p) => w.profiles[p]);
    w.screens.forEach((sc) => { sc.place = renumber[Math.min(sc.place || 0, used.at(-1))] ?? 0; });
    return true;
  }

  /** The options under the places, read back into the view. */
  _weatherOptions() {
    const main = this._main();
    if (this._pruneProfiles()) this._drawProfiles();
    const $ = (sel) => main.querySelector(sel);
    const w = this._wv.weather;
    w.hour24 = main.querySelector("input[name=wh24]:checked").value === "24";
    w.strip = main.querySelector("input[name=wstrip]:checked").value;
    w.clock_style = main.querySelector("input[name=wstyle]:checked").value;
    w.seconds = $("#wsec").checked;
    w.animate = $("#wanim").checked;
    w.clock_color = $("#wcolor").value;
    w.time_format = $("#wtformat").value.trim();
    w.date_format = $("#wdformat").value.trim();
    w.seconds_style = main.querySelector("input[name=wsstyle]:checked").value;
    w.seconds_color = $("#wscolorOn").checked ? $("#wscolor").value : null;
    w.drop = main.querySelector("input[name=wdrop]:checked").value;
    w.agenda_style = main.querySelector("input[name=wastyle]:checked").value;
    w.scroll_speed = main.querySelector("input[name=wspeed]:checked")?.value || "normal";
    w.agenda_calendars = [...main.querySelectorAll("[data-cal]")].filter((box) => box.checked).map((box) => box.dataset.cal);
    w.agenda_ics = $("#wics").value.split(/\s+/).filter((u) => /^(https?|webcal):\/\//.test(u)).slice(0, 5);
    w.saint_title = $("#wsainttitle").value.trim() || "BONNE FÊTE";
    w.saint_to = $("#wsaintto").checked;
    w.reminders = [...main.querySelectorAll("#wreminders [data-r]")].map((row) => {
      const date = row.querySelector("[data-rdate]").value;
      const days = [...row.querySelectorAll("[data-rday]")].filter((b) => b.checked).map((b) => Number(b.dataset.rday));
      return { text: row.querySelector("[data-rtext]").value.trim(), date: date || null, days: date ? null : days };
    }).filter((r) => r.text);
    w.notes = [...main.querySelectorAll("#wnotes [data-note]")].map((t) => t.value.trim()).filter(Boolean);
    w.events = [...main.querySelectorAll("#wevents [data-e]")].map((row) => ({
      title: row.querySelector("[data-etitle]").value.trim(), date: row.querySelector("[data-edate]").value,
      time: row.querySelector("[data-etime]").value || null,
    })).filter((e) => e.title && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(e.date));
    const today = main.querySelectorAll("[data-today]");
    if (today.length) {  // today's saints and world days ticked (for today only)
      const ticked = (kind) => [...main.querySelectorAll(`[data-today="${kind}"]`)].filter((b) => b.checked).map((b) => b.value);
      w.pick = { date: this._wtodayDate, saints: ticked("saints"), world_days: ticked("world_days") };
    }
    w.birthdays = [...main.querySelectorAll("#wbirthdays [data-b]")].map((row) => ({
      name: row.querySelector("[data-bname]").value.trim(), date: row.querySelector("[data-bdate]").value,
    })).filter((b) => b.name && /^(\d{4}-)?\d{2}-\d{2}$/.test(b.date));
    w.hours_step = Number($("#wstep").value);
    const fixed = $("#whmode").value === "at";
    const hours = [...main.querySelectorAll("[data-at]")].map((i) => i.value).filter((v) => v !== "")
      .map(Number).filter((h) => h >= 0 && h <= 23);
    w.hours_at = fixed && hours.length ? hours : null;
    w.brightness = $("#wbright").checked ? { day: Number($("#wday").value), night: Number($("#wnight").value) } : null;
    if ($("#wswitch")) {
      const every = Math.max(1, Math.min(600, Number($("#wswitch").value) || 15));
      if (every !== w.switch_seconds) {  // the cities' screens take that time
        w.switch_seconds = every;
        for (const screen of w.screens || []) {
          if (["name", "today", "strip"].some((p) => screen.parts?.[p])) screen.seconds = every;
        }
        if (main.querySelector("#wscreen")) this._drawWeatherScreen();
      }
    }
    if ($("#wcitytime")) w.city_time = $("#wcitytime").checked;
    $("#whoursRow").hidden = w.strip !== "hours";
    $("#wstep").hidden = fixed;
    $("#wat").hidden = !fixed;
    $("#wbrightRow").hidden = !w.brightness;
    $("#wdayv").textContent = `${$("#wday").value} %`;
    $("#wnightv").textContent = `${$("#wnight").value} %`;
    this._wv.interval = Number($("#wrefresh").value);
  }

  /** Reminders: a text, each week on some days (none: every day), or on a date. */
  _drawReminders(list) {
    this._main().querySelector("#wreminders").innerHTML = list.map((r, i) => `<div class="row small" data-r="${i}">🔔
      <input type="text" data-rtext class="grow" maxlength="60" placeholder="Sortir les poubelles" value="${esc(r.text || "")}">
      ${WEATHER_DAYS.map((d, n) => `<label><input type="checkbox" data-rday="${n}" ${(r.days || []).includes(n) ? "checked" : ""}>${d}</label>`).join("")}
      ou le <input type="date" data-rdate value="${esc(r.date && r.date.length === 10 ? r.date : "")}">
      <button class="icon" data-rdel title="Retirer">🗑</button></div>`).join("");
  }

  /** Appointments typed in: a title, a day, a time (empty: all day). */
  _drawEvents(list) {
    this._main().querySelector("#wevents").innerHTML = list.map((e, i) => `<div class="row small" data-e="${i}">📅
      <input type="text" data-etitle class="grow" maxlength="60" placeholder="Dentiste" value="${esc(e.title || "")}">
      <input type="date" data-edate value="${esc(e.date || "")}"> <input type="time" data-etime value="${esc(e.time || "")}">
      <button class="icon" data-edel title="Retirer">🗑</button></div>`).join("");
  }

  /** Today's saints and world days as loaded (tick those to show; world days 2 at most), and what the agenda reads. */
  _drawWeatherToday(today) {
    const main = this._main();
    // Each iCal link: read, or why not (a « public » Google address of a private calendar: 404).
    const status = main.querySelector("#wicsstatus");
    if (status && today?.ics) {
      status.innerHTML = today.ics.map((l) => {
        const name = esc(decodeURIComponent((l.url.match(/ical\/([^/]+)/) || [])[1] || l.url).slice(0, 40));
        if (l.ok) return `<div class="ok">✓ ${name} : ${l.events} événements</div>`;
        if (!l.error) return `<div class="muted">… ${name} : lecture en cours</div>`;
        const hint = l.public && /404|403/.test(l.error)
          ? " — cet agenda n'est pas public : prends son « Adresse secrète au format iCal » (Google Agenda → Paramètres → l'agenda)" : "";
        return `<div class="error">✗ ${name} : erreur ${esc(l.error)}${hint}</div>`;
      }).join("");
    }
    const key = JSON.stringify([today, this._wv.weather.pick]);
    if (!today || key === this._wtodayKey) return;
    this._wtodayKey = key;
    this._wtodayDate = today.date;
    const pick = this._wv.weather.pick?.date === today.date ? this._wv.weather.pick : null;
    const box = (kind, item, on) => `<label><input type="checkbox" data-today="${kind}" value="${esc(item)}" ${on ? "checked" : ""}> ${esc(item)}</label>`;
    const parts = [];
    if (today.calendars) {
      parts.push(`<div class="row small"><b>Agenda lu aujourd'hui</b> ${today.agenda.length
        ? today.agenda.map((e) => `<span>📅 ${esc(e)}</span>`).join(" ") : `<span class="muted">aucun rendez-vous</span>`}</div>`);
    }
    if (today.saints.length) {
      parts.push(`<div class="row small"><b>Saints</b> ${today.saints.map((n) => box("saints", n, !pick?.saints?.length || pick.saints.includes(n))).join("")}</div>`);
    }
    if (today.world_days.length) {
      parts.push(`<div class="row small"><b>Journées (2 au plus)</b> ${today.world_days.map((d, i) => box("world_days", d,
        pick?.world_days?.length ? pick.world_days.includes(d) : i < 2)).join("")}</div>`);
    }
    main.querySelector("#wtoday").innerHTML = parts.join("");
    this._limitWorldDays();
  }

  _limitWorldDays() {
    const boxes = [...this._main().querySelectorAll('[data-today="world_days"]')];
    const full = boxes.filter((b) => b.checked).length >= 2;
    boxes.forEach((b) => { b.disabled = full && !b.checked; });
  }

  /** Notes: just text. */
  _drawNotes(list) {
    this._main().querySelector("#wnotes").innerHTML = list.map((t, i) => `<div class="row" data-n="${i}">
      <textarea data-note class="grow" rows="2" maxlength="200">${esc(t)}</textarea>
      <button class="icon" data-ndel title="Retirer">🗑</button></div>`).join("");
  }

  /** Birthdays: a name and a date (the year, if given, tells the age). */
  _drawBirthdays(list) {
    this._main().querySelector("#wbirthdays").innerHTML = list.map((b, i) => `<div class="row" data-b="${i}">🎂
      <input type="text" data-bname maxlength="40" placeholder="Prénom" value="${esc(b.name || "")}">
      <input type="date" data-bdate value="${esc(b.date && b.date.length === 10 ? b.date : b.date ? `2000-${b.date}` : "")}">
      <button class="icon" data-bdel title="Retirer">🗑</button></div>`).join("");
  }

  _weatherInput(ev, committed = false) {
    const t = ev.target;
    if (t.id === "wname") { this._wv.name = t.value; return; }
    const row = t.closest?.("[data-p]");
    if (row) {
      if (t.dataset.k === "label" || (t.dataset.k === "source" && committed)) {
        row.dataset.p = String(this._ownProfile(Number(row.dataset.p)));  // the other screens keep theirs
      }
      const p = this._wv.weather.profiles[Number(row.dataset.p)];
      if (t.dataset.k === "label") {
        p.label = t.value.trim() || null;
        if (committed) this._weatherPreview(true);
        else this._weatherTyped();
      } else if (t.dataset.k === "source" && committed) {
        const [kind, id] = t.value.split(/:(.*)/s);
        Object.assign(p, { source: kind, entity_id: kind === "entity" ? id : null, zone: kind === "zone" ? id : null });
        if (kind !== "place") p.place = null;
        row.querySelector("[data-placerow]").hidden = kind !== "place";
        row.querySelector("[data-places]").innerHTML = "";
        this._weatherPreview(true);
      }
      return;
    }
    if (t.matches?.("input[type=range]") && !committed) {
      this._weatherOptions();  // the % follows the slider
      return;
    }
    if (!committed) {
      if (t.matches?.("input[type=text], textarea")) this._weatherTyped();
      return;
    }
    this._weatherOptions();
    this._weatherPreview(true);
  }

  /** Typing: sent a moment after the last key, without leaving the field. */
  _weatherTyped() {
    clearTimeout(this._weatherTypeTimer);
    this._weatherTypeTimer = setTimeout(() => {
      if (!this._wv) return;
      this._weatherOptions();
      this._weatherPreview(true);
    }, 900);
  }

  _weatherClick(ev) {
    const t = ev.target;
    const row = t.closest?.("[data-p]");
    const w = this._wv.weather;
    if (t.closest?.("#waddp")) {
      w.profiles.push(this._newProfile());
      this._drawProfiles();
      this._weatherPreview(true);
    } else if (row && t.closest("[data-delp]")) {
      w.profiles.splice(Number(row.dataset.p), 1);
      this._drawProfiles();
      this._weatherPreview(true);
    } else if (row && t.closest("[data-find]")) {
      this._weatherFind(Number(row.dataset.p));
    } else if (row && t.closest("[data-place]")) {
      const place = this._weatherFound[Number(row.dataset.p)][Number(t.closest("[data-place]").dataset.place)];
      const i = this._ownProfile(Number(row.dataset.p));  // the other screens keep their city
      row.dataset.p = String(i);
      w.profiles[i].place = place;
      row.querySelector("[data-k=q]").value = place.name;
      row.querySelector("[data-places]").innerHTML = "";
      row.querySelector("[data-k=label]").placeholder = this._profilePlace({ ...w.profiles[i], label: null });
      this._weatherPreview(true);
    } else if (t.closest?.("#waddbirthday")) {
      this._weatherOptions();
      this._drawBirthdays([...(w.birthdays || []), { name: "", date: "" }]);
    } else if (t.closest?.("#waddreminder")) {
      this._weatherOptions();
      this._drawReminders([...(w.reminders || []), { text: "", days: [] }]);
    } else if (t.closest?.("[data-rdel]")) {
      t.closest("[data-r]").remove();
      this._weatherOptions();
      this._weatherPreview(true);
    } else if (t.closest?.("#waddevent")) {
      this._weatherOptions();
      const d = new Date();
      const day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      this._drawEvents([...(w.events || []), { title: "", date: day, time: "" }]);
    } else if (t.closest?.("[data-edel]")) {
      t.closest("[data-e]").remove();
      this._weatherOptions();
      this._weatherPreview(true);
    } else if (t.closest?.("#waddnote")) {
      this._weatherOptions();
      this._drawNotes([...(w.notes || []), ""]);
    } else if (t.closest?.("[data-ndel]")) {
      t.closest("[data-n]").remove();
      this._weatherOptions();
      this._weatherPreview(true);
    } else if (t.closest?.("[data-bdel]")) {
      t.closest("[data-b]").remove();
      this._weatherOptions();
      this._weatherPreview(true);
    } else if (t.id === "wstop") {
      this._ws({ type: "idotmatrix/studio/routine_stop" }).then(() => this._onRoutineStatus({ active: null }),
        (err) => { this._main().querySelector("#werr").textContent = errorText(err); });
    }
  }

  _drawWeatherStatus() {
    const main = this._main();
    const line = main.querySelector("#wstatus");
    if (!line || !this._wv) return;
    const status = this.state.routineStatus || {};
    const on = status.active === this._wv.id;
    line.innerHTML = on ? this._weatherStatusText(status) : "Pas sur le cadre : le prochain changement l'y affiche.";
    main.querySelector("#wstop").hidden = !on;
  }

  async _weatherFind(i) {
    const row = this._main().querySelector(`[data-p="${i}"]`);
    const query = row.querySelector("[data-k=q]").value.trim();
    const list = row.querySelector("[data-places]");
    if (query.length < 2) return;
    list.innerHTML = `<span class="muted small">Recherche…</span>`;
    try {
      const { places } = await this._ws({ type: "idotmatrix/studio/weather_geocode", query });
      this._weatherFound[i] = places;
      list.innerHTML = places.map((p, n) => `<button class="chip-btn" data-place="${n}">📍 ${esc(p.name)}</button>`).join("")
        || `<span class="muted small">Aucun lieu de ce nom.</span>`;
    } catch (err) {
      list.innerHTML = `<span class="error small">${esc(errorText(err))}</span>`;
    }
  }

  /**
   * The LED preview as the display shows it now (its place, its second), redrawn
   * every second. After a change, also how heavy a minute is to send.
   */
  /** Live: a change is saved shortly after and shows on the display at once (the view is put
   * on it if it was not: no button to press). */
  _weatherLiveSave() {
    clearTimeout(this._weatherLiveTimer);
    this._weatherLiveTimer = setTimeout(async () => {
      if (this.state.tab !== "weather" || !this._wv) return;
      if (this._wv.weather.profiles.some((p) => p.source === "place" && !p.place)) return;
      try {
        this._weatherOptions();
        await this._ws({ type: "idotmatrix/studio/routine_save", routine: { ...this._wv, name: this._wv.name.trim() || "Météo" } });
        this._weatherView = this._wv.id;
        if (this.state.routineStatus?.active !== this._wv.id) {
          this._onRoutineStatus(await this._ws({ type: "idotmatrix/studio/routine_start", routine_id: this._wv.id }));
        }
        const line = this._main().querySelector("#wstatus");
        if (line) line.innerHTML = `${this._weatherStatusText(this.state.routineStatus || {})} · <span class="ok">changement envoyé au cadre</span>`;
      } catch (err) {
        const box = this._main().querySelector("#werr");
        if (box) box.textContent = errorText(err);
      }
    }, 800);
  }

  async _weatherPreview(changed = false, live = changed) {
    clearTimeout(this._weatherTimer);
    if (live && this._wv) this._weatherLiveSave();
    if (this.state.tab !== "weather" || !this._wv || !this.isConnected) return;
    const main = this._main();
    const seq = this._weatherSeq = (this._weatherSeq || 0) + 1;
    const summary = main.querySelector("#wsummary");
    const w = this._wv.weather;
    const missing = w.profiles.findIndex((p) => p.source === "place" && !p.place);
    if (missing >= 0) {
      summary.textContent = `${w.profiles.length > 1 ? `Ville ${missing + 1} : t` : "T"}ape un lieu puis « Chercher ».`;
      return;
    }
    try {
      const res = await this._ws({
        type: "idotmatrix/studio/weather_preview", weather: w, max_age: this._wv.interval, minute: changed,
        page: this._wplaying ? null : this._wcur || 0,
      });
      if (seq !== this._weatherSeq || this.state.tab !== "weather") return;
      if (changed || !this._weatherSummary) {
        this._weatherSummary = (res.forecasts || [res.forecast]).map((f) => {
          const parts = [`📍 ${esc(f.place)}`];
          if (f.temperature != null) parts.push(`${Math.round(f.temperature)}${esc(f.unit || "°")}`);
          if (f.high != null || f.low != null) parts.push(`↑${f.high != null ? Math.round(f.high) : "–"} ↓${f.low != null ? Math.round(f.low) : "–"}`);
          if (f.rain != null) parts.push(`pluie ${f.rain} %`);
          else if (f.rain_mm != null) parts.push(`pluie ${f.rain_mm} mm`);
          parts.push(`prévisions de ${new Date(f.fetched * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`);
          return parts.join(" · ");
        }).join("<br>");
        summary.innerHTML = this._weatherSummary;
      }
      if (changed && res.today) {
        this._drawWeatherToday(res.today);
        this._limitWorldDays();
      }
      if (changed && res.pages) {
        main.querySelector("#wpagesToday").textContent = res.pages.length
          ? `Aujourd'hui, en plus de la météo : ${res.pages.map((k) => PAGE_NAMES[k] || k).join(", ")}.` : "Aujourd'hui : la météo seule.";
      }
      if (res.minute_bytes) {
        const packets = Math.ceil(res.minute_bytes / 4096);
        main.querySelector("#wsize").textContent = `Chaque minute : ${kb(res.minute_bytes)}, ${packets} paquet${packets > 1 ? "s" : ""} Bluetooth (${duration(res.minute_s || packets * 0.6)}).`;
      }
      main.querySelector("#werr").textContent = "";
      this._drawWeatherPages(res.titles || [], res.page);
      this._weatherBoxes = res.boxes || {};
      try {
        drawLed(main.querySelector("#wled"), await pngPixels(res.png));
        this._weatherDrawn = true;
        this._outlineWeatherPart();
      } catch (_err) { /* no image decoding here (tests) */ }
    } catch (err) {
      if (seq !== this._weatherSeq) return;
      summary.textContent = "";
      main.querySelector("#werr").textContent = errorText(err);
      return;
    }
    if (seq !== this._weatherSeq || this.state.tab !== "weather" || !this.isConnected) return;
    // The seconds and the places move on: draw it again on the next second.
    this._weatherTimer = setTimeout(() => this._weatherPreview(), 1000 - (Date.now() % 1000) + 30);
  }

  /** The screens: their numbers above the preview (greyed: nothing to show now, or out of its hours),
   * « + » to add one, ▶ to see them in turn. */
  _drawWeatherPages(titles, current) {
    const main = this._main();
    this._wtitles = titles;
    const html = titles.map((t, i) => `<button class="chip-btn ${i === current ? "on" : ""}
      ${!this._wplaying && t.screen === this._wcur ? "pinned" : ""} ${t.off ? "off" : ""}" data-wnum="${t.screen ?? i}"
      title="${esc(t.title)}${t.off ? " (rien maintenant)" : ""}">${(t.screen ?? i) + 1}</button>`).join("")
      + `<button class="chip-btn plus" data-wnum="plus" title="Ajouter un écran">+</button>`
      + `<button class="chip-btn ${this._wplaying ? "pinned" : ""}" data-wnum="play" title="Les voir défiler">▶</button>`;
    const nums = main.querySelector("#wpagenums");
    if (nums.innerHTML !== html && nums.dataset.html !== html) {  // only when it changes: a click is not lost
      nums.innerHTML = html;
      nums.dataset.html = html;
    }
    const title = titles.find((t) => t.screen === this._wcur)?.title;
    main.querySelector("#wscrtitle").textContent = `Écran ${(this._wcur || 0) + 1}${title ? ` · ${title}` : ""}`;
  }

  /** The screen being set: its parts (✕ takes one off), « + Ajouter », its time, city and hours. */
  _drawWeatherScreen() {
    const main = this._main();
    const w = this._wv.weather;
    const screen = this._wscreen();
    const parts = Object.keys(screen.parts || {});
    main.querySelector("#wscrparts").innerHTML = parts.filter((p) => p !== "seconds").map((p) => `<span class="chip-btn wpart"><span class="wpick" data-wpick="${p}">${WEATHER_PARTS[p] || p}</span>
      <b data-wunpart="${p}" title="L'enlever">✕</b></span>`).join("") || `<span class="muted">Écran vide : ajoute ce qu'il doit montrer.</span>`;
    const picked = this._wpicked ||= new Set();
    main.querySelector("#waddparts").innerHTML = Object.entries(WEATHER_PARTS).filter(([k]) => k !== "seconds" && !parts.includes(k))
      .map(([k, label]) => `<button class="chip-btn ${picked.has(k) ? "on" : ""}" data-wadd="${k}">${label}</button>`).join("");
    main.querySelector("#waddsel").disabled = !picked.size;
    main.querySelector("#waddsel").textContent = picked.size > 1 ? `+ Ajouter (${picked.size})` : "+ Ajouter";
    main.querySelector("#wscrsec").value = screen.seconds || 15;
    main.querySelector("#wscrplacerow").style.display = w.profiles.length > 1 ? "" : "none";
    main.querySelector("#wscrplace").innerHTML = w.profiles.map((p, i) => `<option value="${i}" ${i === (screen.place || 0) ? "selected" : ""}>${esc(this._profilePlace(p) || `Ville ${i + 1}`)}</option>`).join("");
    const hours = screen.from != null && screen.to != null;
    main.querySelector("#wscrhours").checked = hours;
    main.querySelector("#wscrfrom").value = screen.from ?? 6;
    main.querySelector("#wscrto").value = screen.to ?? 10;
    main.querySelector("#wscrfrom").disabled = main.querySelector("#wscrto").disabled = !hours;
    main.querySelector("#wscrleft").disabled = !this._wcur;
    main.querySelector("#wscrright").disabled = this._wcur >= w.screens.length - 1;
    main.querySelector("#wscrdel").disabled = w.screens.length < 2;
    main.querySelectorAll("[data-wpick]").forEach((n) => n.classList.toggle("on", n.dataset.wpick === this._wzone));
  }

  // ---------------------------------------------------------- frame status

  /** Re-read the display's state (connection, screen, routine, schedule). */
  _refreshStatus() {
    clearTimeout(this._statusDebounce);
    this._statusDebounce = setTimeout(async () => {
      try {
        this.state.status = await this._ws({ type: "idotmatrix/studio/status" });
      } catch (_err) {
        return;
      }
      const st = this.state.status;
      if (this._entryId && !(st.displays || []).some((d) => d.entry_id === this._entryId)) {
        this._entryId = null;  // that display was removed: back to the selected one
        this._refreshStatus();
        return;
      }
      this._entryId ||= st.entry_id;
      this.state.routineStatus = st.routine;
      this._renderStatus();
      if (this.state.tab === "routines") { this._drawRoutineList(); this._drawSchedule(); }
    }, 250);
  }

  _updatePreview() {
    const entity = this.state.status?.preview_entity;
    const img = this.shadowRoot?.querySelector(".sprev");
    if (!img || !entity) return;
    const picture = this._hass.states[entity]?.attributes?.entity_picture;
    if (picture === this._previewUrl) return;
    this._previewUrl = picture;
    img.classList.toggle("none", !picture);
    // Nothing sent since Home Assistant started: an empty screen, not a broken image.
    img.onerror = () => {
      img.onerror = null;
      img.src = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
      img.title = "Rien n'a encore été envoyé au cadre depuis le démarrage de Home Assistant";
    };
    img.title = "Ce qu'affiche le cadre";
    if (picture) img.src = picture;
  }

  _renderStatus() {
    const st = this.state.status;
    const line1 = this.shadowRoot.querySelector("#sline1");
    if (!st || !line1) return;
    this._updatePreview();
    const sched = st.schedule_status || {};
    const until = sched.next_change ? ` jusqu'à ${hhmm(sched.next_change)}` : "";
    const dark = sched.screen_off || !st.screen_on;
    const size = this.info?.screen_size ? ` · ${this.info.screen_size}×${this.info.screen_size}` : "";
    const displays = st.displays || [];
    // With several displays, each runs on its own: the picker chooses which one the Studio drives.
    const name = displays.length > 1
      ? `<select class="dsel" title="Cadre piloté par le Studio (chaque cadre garde sa routine et son planning)">${displays.map((d) =>
        `<option value="${esc(d.entry_id)}" ${d.entry_id === st.entry_id ? "selected" : ""}>${esc(d.name)}${d.routine_name ? ` · ▶ ${esc(d.routine_name)}` : ""}${d.screen_on ? "" : " · 🌙"}</option>`).join("")}</select>`
      : `<b>${esc(st.display || "Cadre")}</b>`;
    const parts = [`<span title="${st.connected ? "Le cadre est connecté en Bluetooth" : "Connexion Bluetooth ouverte au prochain envoi"}">
      <span class="dot ${st.connected ? "on" : ""}"></span>${name}${size} · ${st.connected ? "connecté" : "en veille"}</span>`];
    if (dark) parts.push(`<span class="pill off">🌙 Écran éteint${sched.screen_off ? until : ""}</span>`);
    const routine = st.routine || {};
    if (routine.active) parts.push(`<span class="pill">▶ ${esc(st.routine_name || "Routine")}</span>`);
    parts.push(sched.enabled ? `<span class="pill" title="La frise du planning décide">📅 Planning</span>`
      : `<span class="pill" title="Les ensembles s'allument à la main ; le planning attend">✋ Manuel</span>`);
    if (sched.enabled && sched.block && sched.block.action === "routine") {
      parts.push(`<span class="muted small">planning${until}</span>`);
    }
    line1.innerHTML = parts.join("");
    const line2 = this.shadowRoot.querySelector("#sline2");
    line2.innerHTML = routine.active ? this._routineStatusText(routine)
      : sched.enabled ? `Planning${sched.block ? "" : " · aucune plage en cours"}${!sched.block && sched.next_change ? `, prochaine à ${hhmm(sched.next_change)}` : ""}`
      : "Aucun ensemble allumé";
    if (this._screenError) line2.innerHTML = `<span class="error">${esc(this._screenError)}</span>`;
    const strip = this.shadowRoot.querySelector("#supnext");
    strip.innerHTML = this._upNextHtml(routine);
    this._fillThumbs(strip);
    // The carousel's estimated slot moves on by itself.
    clearInterval(this._carouselTimer);
    if (routine.active && routine.state === "carousel") this._carouselTimer = setInterval(() => this._redrawUpNext(), 5000);
    this.shadowRoot.querySelector(".sacts").innerHTML = (routine.active && (routine.mode || "ha") === "ha"
      ? `<button class="icon" data-sact="next" title="GIF suivant maintenant">⏭</button>` : "")
      + (routine.active ? `<button class="icon" data-sact="stop" title="Arrêter la routine">■</button>` : "")
      // Both stay clickable: the cached screen state can be wrong (e.g. switched on the frame itself).
      + `<button class="icon" data-sact="off" title="Éteindre l'écran (écran noir)">🌙</button>`
      + `<button class="icon" data-sact="on" title="Allumer l'écran">☀️</button>`;
  }

  /** Drive another display: its size, routine, schedule and screen. */
  async _pickDisplay(entryId) {
    const size = this.size;
    this._entryId = entryId;
    this._screenError = null;
    this._schedDirty = false;
    this.state.transfer = null;
    this._renderTransfer();
    try {
      await this._ws({ type: "idotmatrix/studio/select", entry_id: entryId });
      this.info = await this._ws({ type: "idotmatrix/studio/info" });
    } catch (err) {
      this._screenError = `Cadre : ${err.message || err}`;
    }
    if (this.size !== size) {
      // Clips are cut to the display's size: prepare them again for this one.
      for (const clip of this.clips || []) { clip.frames = null; clip.result = null; }
      this._show(this.state.tab);
    } else if (this.state.tab === "routines" || this.state.tab === "weather") {
      this._show(this.state.tab);
    }
    this._refreshStatus();
  }

  async _statusAction(ev) {
    const button = ev.target.closest("button[data-sact]");
    if (!button) return;
    const action = button.dataset.sact;
    if (action === "stop") {
      await this._ws({ type: "idotmatrix/studio/routine_stop" });
      this._refreshStatus();
    } else if (action === "next") {
      try {
        await this._ws({ type: "idotmatrix/studio/routine_next" });
      } catch (err) {
        this._screenError = `Routine : ${err.message || err}`;
        this._refreshStatus();
      }
    } else if (action === "on" || action === "off") {
      button.disabled = true;
      this._screenError = null;
      try {
        await this._ws({ type: "idotmatrix/studio/screen", on: action === "on" });
      } catch (err) {
        this._screenError = `Écran : ${err.message || err}`;
      }
      this._refreshStatus();
    }
  }

  // ---------------------------------------------------------------- transfer

  _onTransfer(data) {
    if (this._otherDisplay(data)) return;
    // The weather clock sends one packet a minute: its line in the status says enough.
    if (data.file === WEATHER_SEND) return;
    // A send that gave way to a newer one: the newer one owns the bar.
    if (data.state === "superseded") return;
    const t = this.state.transfer = Object.assign(this.state.transfer || {}, { what: null }, data);
    if (data.state === "started") Object.assign(t, { sent: 0, total: 0, message: "", startedAt: Date.now() });
    this._renderTransfer();
    if (data.state === "done" || data.state === "error") this._refreshStatus();
  }

  _renderTransfer() {
    const t = this.state.transfer;
    const el = this.shadowRoot.querySelector(".status .transfer");
    if (!el) return;
    if (!t) { el.innerHTML = ""; return; }
    const what = t.file === "live" ? "l'aperçu direct" : t.file ? esc(t.file) : "un affichage";
    const clearLater = () => setTimeout(() => {
      if (this.state.transfer !== t) return;
      this.state.transfer = null;
      if (el.isConnected) el.innerHTML = "";
    }, 6000);
    if (t.state === "done" && t.file === "live") {
      el.innerHTML = "";  // live stills come and go: no message to read
      this.state.transfer = null;
      return;
    }
    if (t.state === "done") {
      el.innerHTML = `<div class="tline ok">✅ ${what} est affiché sur le cadre.</div>`;
      clearLater();
      return;
    }
    if (t.state === "error") {
      el.innerHTML = `<div class="tline error">${esc(t.what || "Échec de l'envoi")} : ${esc(t.message || "")}</div>`;
      clearLater();
      return;
    }
    if (t.state === "saved") {
      el.innerHTML = `<div class="tline ok">✓ ${esc(t.message || "")}</div>`;
      clearLater();
      return;
    }
    let left = "";
    if (t.total && t.sent && t.startedAt) {
      const per = (Date.now() - t.startedAt) / t.sent;
      left = ` · encore ${duration(Math.round((per * (t.total - t.sent)) / 1000))}`;
    }
    const label = t.total ? `${t.sent}/${t.total}${left}` : "préparation…";
    el.innerHTML = `<div class="tline"><span class="ellipsis">⇪ ${what}</span>
      <progress max="${t.total || 1}" value="${t.sent || 0}"></progress><span class="small">${label}</span></div>`;
  }
}

Object.assign(IDotMatrixStudio, { matchSource, trackPoint, cropAt, renderOf, RENDERS });  // for the tests
if (!customElements.get("idotmatrix-studio")) customElements.define("idotmatrix-studio", IDotMatrixStudio);
