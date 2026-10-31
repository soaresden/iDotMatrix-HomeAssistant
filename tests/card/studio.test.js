import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

const window = new Window({ url: "http://localhost" });
for (const key of ["window", "document", "customElements", "HTMLElement", "Element", "Node", "Event", "sessionStorage", "navigator"]) {
  Object.defineProperty(globalThis, key, { value: key === "window" ? window : window[key], configurable: true, writable: true });
}
await import("../../custom_components/idotmatrix/www/idotmatrix-studio.js");

const wait = (ms = 20) => new Promise((resolve) => setTimeout(resolve, ms));
const panels = [];
afterEach(() => {
  for (const panel of panels) panel.remove();
  panels.length = 0;
  sessionStorage.clear();
});

/** The panel against a fake Home Assistant: one original filed in « Chats », one empty folder. */
async function studio(extra = {}) {
  const synced = [];
  const calls = [];
  const replies = {
    "idotmatrix/studio/info": { screen_size: 64, max_frames: 64, transfer_event: "t", routine_event: "r", schedule_event: "s", store: true },
    "idotmatrix/studio/workspace": {
      originals: [{ id: "o1", name: "chat.mp4", size: 10, device: "PC", folder: "Chats", created: 1, updated: 1 }],
      clips: [{ id: "c1", originalId: "o1", title: "Chat", opts: {}, created: 1, updated: 1 }],
      deleted: [], folders: ["Vide"],
    },
    "idotmatrix/studio/gallery": {
      items: [{ file: "a.gif", title: "A", folder: "Chats", frames: 2, url: "/a.gif", modified: 1, size_bytes: 9, estimate_s: 1 }],
    },
    "idotmatrix/studio/status": { display: "Cadre", displays: [], connected: false, screen_on: true, routine: {}, schedule_status: {} },
    "auth/sign_path": { path: "/signed" },
    ...extra,
  };
  const hass = {
    states: {},
    callWS: async (msg) => {
      if (msg.type === "idotmatrix/studio/workspace_sync") synced.push(msg);
      calls.push(msg);
      const reply = replies[msg.type];
      return typeof reply === "function" ? reply(msg) : structuredClone(reply ?? {});
    },
    connection: { subscribeEvents: async () => () => {} },
  };
  const panel = document.createElement("idotmatrix-studio");
  panels.push(panel);
  document.body.appendChild(panel);
  panel.hass = hass;
  await wait();
  const $ = (selector) => panel.shadowRoot.querySelector(selector);
  const chips = (id) => [...panel.shadowRoot.querySelectorAll(`#${id} .chip-btn`)].map((b) => b.textContent.replace(/\s+/g, " ").trim());
  return { panel, synced, calls, $, chips };
}

test("gallery and workspace share folders, empty ones included", async () => {
  const { $, chips } = await studio();
  assert.deepEqual(chips("gfolders"), ["Tous 1", "📂 Sans dossier 0", "📁 Chats 1", "📁 Vide 0", "⋯"]);
  $('nav button[data-tab="workspace"]').click();
  await wait();
  assert.deepEqual(chips("wfolders"), ["Tous 1", "📂 Sans dossier 0", "📁 Chats 1", "📁 Vide 0", "⋯"]);
});

test("a folder made in the workspace receives the next imports and reaches Home Assistant", async () => {
  const { $, chips, panel, synced } = await studio();
  $('nav button[data-tab="workspace"]').click();
  await wait();
  $("#wfolders [data-newfolder]").click();
  const input = $("#wfolders .chip-input");
  input.value = "Noël";
  input.dispatchEvent(new Event("blur"));
  await wait();
  assert.ok(chips("wfolders").includes("📁 Noël 0"));
  assert.equal($("#wfolders .chip-btn.on").dataset.folder, "Noël");
  assert.match($("main").textContent, /les ajouts vont dans 📁 Noël/);
  await wait(700);
  assert.deepEqual(synced.at(-1).folders, ["Vide", "Noël"]);
  // An empty folder made by hand can be removed again (two taps).
  $("#wfolders [data-delfolder]").click();
  $("#wfolders [data-delfolder]").click();
  await wait(700);
  assert.deepEqual(synced.at(-1).folders, ["Vide"]);
  assert.equal(panel.state.filter.folder, null);
});

test("selected originals are filed in another folder on every device", async () => {
  const { $, chips, panel, synced } = await studio();
  $('nav button[data-tab="workspace"]').click();
  await wait();
  $('.orig[data-orig="o1"] [data-act="pick"]').click();
  $("#wmove").value = "Archives";
  $('#wselbar [data-sel="move"]').click();
  await wait(700);
  assert.equal(panel.originals[0].folder, "Archives");
  assert.ok(chips("wfolders").includes("📁 Archives 1"));
  const record = synced.at(-1).put_originals.find((o) => o.id === "o1");
  assert.equal(record.folder, "Archives");
  assert.ok(record.updated > 1, "a newer edit wins over the other devices' copy");
});

test("after a reload (phone file picker, low memory) the panel reopens the same tab", async () => {
  const first = await studio();
  first.$('nav button[data-tab="workspace"]').click();
  await wait();
  first.panel.remove();
  const { $ } = await studio();
  assert.equal($("nav button.on").dataset.tab, "workspace");
});

test("deleting moves to a shared trash that restores everything; nothing clears the whole workspace", async () => {
  const { $, chips, panel, synced } = await studio();
  $('nav button[data-tab="workspace"]').click();
  await wait();
  assert.equal($("#clear"), null);
  $('.orig[data-orig="o1"] [data-act="delorig"]').click();
  await wait(1200);  // clips save after 400 ms, then sync after 600 ms
  assert.deepEqual([panel.originals.length, panel.clips.length], [0, 0]);
  // Other devices hear of it as a trashed record, never as a deletion.
  const sent = synced.flatMap((m) => [...m.put_originals, ...m.put_clips]);
  assert.ok(sent.some((r) => r.id === "o1" && r.trashed) && sent.some((r) => r.id === "c1" && r.trashed));
  assert.ok(synced.every((m) => !m.delete_originals.length && !m.delete_clips.length && !m.clear));
  assert.ok(chips("wfolders").includes("🗑 Corbeille 2"));
  $('#wfolders [data-folder="__corbeille__"]').click();
  await wait();
  $('[data-kind="originals"][data-id="o1"] [data-tact="restore"]').click();
  await wait(1200);
  assert.deepEqual([panel.originals.length, panel.clips.length, panel.trash.originals.length], [1, 1, 0]);
  assert.equal(panel.originals[0].trashed, null);
});

test("a bulk import lists every file at once and reads them one at a time", async () => {
  const { $, panel, synced } = await studio();
  $('nav button[data-tab="workspace"]').click();
  await wait();
  let reading = 0;
  let most = 0;
  panel._loadFile = async (original) => {
    reading += 1;
    most = Math.max(most, reading);
    await wait(5);
    reading -= 1;
    throw new Error(`no decoder here for ${original.name}`);
  };
  const files = Array.from({ length: 48 }, (_, i) => new window.File(["x"], `video${i}.mp4`, { type: "video/mp4" }));
  const done = panel._addFiles(files);
  // Every row (and a first clip each) is there before any file is read.
  assert.equal(panel.originals.length, 49);
  assert.equal(panel.clips.length, 49);
  assert.equal(panel.shadowRoot.querySelectorAll("#tree .orig").length, 49);
  await done;
  assert.equal(most, 1);
  await wait(700);
  const listed = new Set(synced.flatMap((m) => m.put_originals.map((r) => r.name)));
  assert.ok(files.every((f) => listed.has(f.name)));
});

test("the store tab lists a category, shows each GIF's size and adds it to the gallery", async () => {
  const gif = "R0lGODlhAQABAAAAACw=";
  const item = (name) => ({ url: `https://cdn/${name}.gif`, name, width: 64, height: 64, format: "gif" });
  const { $, calls, panel } = await studio({
    "idotmatrix/studio/store_list": (msg) => ({
      items: msg.group === "daily" ? [item(`coeur${msg.page}`), item(`chat${msg.page}`)] : [item("sapin")],
      page: msg.page, total_pages: 2, total: 4, size: 64,
    }),
    "idotmatrix/studio/store_item": (msg) => ({
      gif, size_bytes: msg.url.includes("coeur") ? 2048 : 5120, frames: 12, duration_ms: 1200, width: 64, height: 64,
      local_palettes: msg.url.includes("chat") ? 12 : 0, device_ready: !msg.url.includes("chat"),
    }),
    "idotmatrix/studio/store_import": (msg) => ({ file: `${msg.title}.gif`, size_bytes: 2048, reencoded: false, estimate_s: 3 }),
  });
  $('nav button[data-tab="store"]').click();
  await wait(60);
  const cards = () => [...panel.shadowRoot.querySelectorAll("#sgrid .item")];
  assert.deepEqual(cards().slice(0, 2).map((c) => c.querySelector(".title").textContent), ["coeur1", "chat1"]);
  assert.match(cards()[0].textContent, /2\.0 Ko · 12 img · 1\.2 s/);
  assert.match(cards()[0].textContent, /✓ tel quel/);
  assert.match(cards()[1].textContent, /↻ redimensionné/);
  assert.equal(cards()[0].querySelector("img").getAttribute("src"), `data:image/gif;base64,${gif}`);

  // Every page loads on its own (no "load more"), then the filter on file names.
  await wait(60);
  assert.equal(cards().length, 4);
  assert.equal($("#smore"), null);
  $("#sq").value = "chat";
  $("#sq").dispatchEvent(new Event("input"));
  assert.deepEqual(cards().map((c) => c.querySelector(".title").textContent), ["chat1", "chat2"]);

  cards()[0].querySelector('[data-act="add"]').click();
  await wait();
  assert.deepEqual(calls.filter((m) => m.type === "idotmatrix/studio/store_import").map((m) => [m.url, m.title, m.display]),
    [["https://cdn/chat1.gif", "chat1", false]]);
  assert.match($(".status .transfer").textContent, /chat1\.gif ajouté à la galerie/);

  // Another category starts over.
  $("#sq").value = "";
  $("#sq").dispatchEvent(new Event("input"));
  $('#sgroups [data-group="holiday"]').click();
  await wait(60);
  assert.deepEqual(cards().map((c) => c.querySelector(".title").textContent), ["sapin"]);
});

test("a store that does not answer says so instead of an empty grid", async () => {
  const { $ } = await studio({
    "idotmatrix/studio/store_list": async () => { throw new Error("The store refused the request (HTTP 403)"); },
  });
  $('nav button[data-tab="store"]').click();
  await wait(60);
  assert.match($("#sgrid").textContent, /Le store ne répond pas : The store refused the request \(HTTP 403\)/);
});

test("an open page picks up what another device just added, trash untouched", async () => {
  const { $, panel } = await studio();
  $('nav button[data-tab="workspace"]').click();
  await wait();
  $('.orig[data-orig="o1"] [data-act="delorig"]').click();
  await wait(1200);
  const callWS = panel._hass.callWS;
  panel._hass.callWS = async (msg) => (msg.type === "idotmatrix/studio/workspace"
    ? {
      originals: [
        { id: "o1", name: "chat.mp4", size: 10, device: "PC", folder: "Chats", created: 1, updated: Date.now(), trashed: Date.now() },
        { id: "o2", name: "tel.mp4", size: 20, device: "téléphone", folder: "", created: 2, updated: 2 },
      ],
      clips: [{ id: "c2", originalId: "o2", title: "Tel", opts: {}, created: 2, updated: 2 }],
      deleted: [], folders: ["Vide"],
    }
    : callWS(msg));
  await panel._refreshWorkspace();
  assert.deepEqual(panel.originals.map((o) => [o.name, !!o.missing]), [["tel.mp4", true]]);
  assert.deepEqual(panel.trash.originals.map((o) => o.id), ["o1"]);
  assert.match($("#tree").textContent, /importé sur téléphone/);
});


test("store animations can be starred and found again under Favoris", async () => {
  const item = { url: "https://cdn/coeur1.gif", name: "coeur1", width: 64, height: 64, format: "gif" };
  const { $, calls, panel } = await studio({
    "idotmatrix/studio/store_list": () => ({ items: [item], page: 1, total_pages: 1, total: 1, size: 64 }),
    "idotmatrix/studio/store_favorites": () => ({ items: [] }),
  });
  $('nav button[data-tab="store"]').click();
  await wait(60);
  panel.shadowRoot.querySelector('#sgrid [data-act="favorite"]').click();
  await wait();
  const sent = calls.find((m) => m.type === "idotmatrix/studio/store_favorite");
  assert.deepEqual([sent.url, sent.favorite, sent.item.name], ["https://cdn/coeur1.gif", true, "coeur1"]);
  assert.equal(panel.shadowRoot.querySelector('#sgrid [data-act="favorite"]').textContent, "★");
  $('#sgroups [data-group="favorites"]').click();
  await wait(60);
  assert.deepEqual([...panel.shadowRoot.querySelectorAll("#sgrid .item .title")].map((t) => t.textContent), ["coeur1"]);
});

test("new clips play as a boomerang; clips saved before keep their setting", async () => {
  const { panel } = await studio();
  assert.equal(panel.clips.find((c) => c.id === "c1").opts.boomerang, true);  // saved with no setting: the default
  const original = panel.originals[0];
  const clip = panel._newClip(original);
  assert.equal(clip.opts.boomerang, true);
  clip.opts.boomerang = false;
  assert.equal(panel._newClip(original, clip).opts.boomerang, false);  // a copy keeps the choice
});

test("the live bar clears once the still is on the display", async () => {
  const { $, panel } = await studio();
  panel._onTransfer({ file: "live", state: "started" });
  panel._onTransfer({ state: "progress", sent: 1, total: 1, file: "live" });
  assert.match($(".status .transfer").textContent, /aperçu direct/);
  panel._onTransfer({ file: "live", state: "done" });
  assert.equal($(".status .transfer").textContent.trim(), "");
  assert.equal(panel.state.transfer, null);
});

test("gallery GIFs always have a checkbox and a folder button; folders can be renamed everywhere", async () => {
  const { $, calls, synced, panel } = await studio();
  const organize = () => calls.filter((m) => m.type === "idotmatrix/studio/organize").map((m) => [m.files, m.folder]);
  assert.equal($("#gsel"), null);
  assert.equal($("#gselbar").hidden, true);
  $('.item[data-file="a.gif"] [data-act="check"]').click();
  await wait();
  assert.equal($("#gselbar").hidden, false);
  $('.item[data-file="a.gif"] [data-act="check"]').click();
  await wait();
  assert.equal($("#gselbar").hidden, true);

  $('.item[data-file="a.gif"] [data-act="folder"]').click();
  const field = $(".item .chip-input");
  assert.equal(field.value, "Chats");
  field.value = "Vide";
  field.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter" }));
  await wait();
  assert.deepEqual(organize(), [[["a.gif"], "Vide"]]);

  // Rename « Chats »: the original in the workspace and the gallery GIFs follow.
  $('#gfolders [data-folder="Chats"]').click();
  await wait();
  $("#gfolders [data-renamefolder]").click();
  const rename = $("#gfolders .chip-input");
  rename.value = "Félins";
  rename.dispatchEvent(new Event("blur"));
  await wait(700);
  assert.deepEqual(organize().at(-1), [["a.gif"], "Félins"]);
  assert.equal(panel.originals[0].folder, "Félins");
  assert.equal(synced.flatMap((m) => m.put_originals).find((o) => o.id === "o1").folder, "Félins");
  assert.equal(panel.state.galleryFilter.folder, "Félins");
});

test("schedule blocks move and resize by dragging; gaps switch the screen off by default", async () => {
  const { $, panel } = await studio({ "idotmatrix/studio/routines": { routines: [], status: {} } });
  $('nav button[data-tab="routines"]').click();
  await wait();
  assert.equal($("#sgaps").value, "off");
  $("#sadd").click();  // 23:00 → 07:00, screen off
  await wait();
  assert.ok($("#day").classList.contains("gapoff"));
  const day = $("#day");
  day.getBoundingClientRect = () => ({ left: 0, width: 1440, top: 0, height: 44 });  // 1 px = 1 min
  const pointer = (target, type, x) => target.dispatchEvent(new window.PointerEvent(type, { clientX: x, bubbles: true, pointerId: 1 }));
  pointer($('.blk [data-edge="from"]'), "pointerdown", 1380);
  pointer(day, "pointermove", 1320);
  pointer(day, "pointerup", 1320);
  assert.deepEqual([panel._sched.blocks[0].from, panel._sched.blocks[0].to], ["22:00", "07:00"]);
  // The whole block: 30 minutes later.
  pointer($('.blk[data-i="0"] span'), "pointerdown", 600);
  pointer(day, "pointermove", 630);
  pointer(day, "pointerup", 630);
  assert.deepEqual([panel._sched.blocks[0].from, panel._sched.blocks[0].to], ["22:30", "07:30"]);
  // The click that ends a drag does not add an hour.
  day.click();
  assert.equal(panel._sched.blocks.length, 1);
  assert.equal($("#ssave").disabled, false);
  $("#sgaps").value = "keep";
  $("#sgaps").dispatchEvent(new Event("change"));
  assert.equal(panel._sched.gaps, "keep");
  assert.ok(!$("#day").classList.contains("gapoff"));
});

test("schedule blocks can keep to some days, and the strip shows one day", async () => {
  const { $, panel } = await studio({ "idotmatrix/studio/routines": { routines: [], status: {} } });
  $('nav button[data-tab="routines"]').click();
  await wait();
  $("#sadd").click();  // no day chosen: every day
  const row = () => $('.srow[data-i="0"]');
  assert.equal(row().querySelectorAll(".days button.on").length, 0);
  assert.match(row().textContent, /tous les jours/);
  for (const wd of [4, 5]) row().querySelector(`[data-wd="${wd}"]`).click();  // Friday and Saturday nights
  assert.deepEqual(panel._sched.blocks[0].days, [4, 5]);
  // The day chips only show a day: Sunday shows Saturday's night after midnight.
  $('#sdays [data-day="6"]').click();
  assert.equal($("#day").querySelectorAll(".blk").length, 1);
  assert.equal($("#day .blk").style.left, "0%");
  $("#sadd").click();  // added while Sunday is shown: still every day
  assert.equal(panel._sched.blocks[1].days, null);
  $('#sdays [data-day="*"]').click();
  for (const wd of [4, 5]) row().querySelector(`[data-wd="${wd}"]`).click();  // none chosen: every day again
  assert.equal(panel._sched.blocks[0].days, null);
});

test("Planning or Manuel: an ensemble switched On by hand plays now and the planning waits", async () => {
  const blocks = [{ from: "18:00", to: "22:00", action: "routine", routine_id: "r1", days: null }];
  const { $, panel, calls } = await studio({
    "idotmatrix/studio/routines": { routines: [{ id: "r1", name: "Matin", files: ["a.gif"], interval: 60, order: "random", mode: "ha" }], status: {} },
    "idotmatrix/studio/status": { display: "Cadre", displays: [], connected: true, screen_on: true, routine: {},
      schedule: { enabled: true, blocks, gaps: "off" }, schedule_status: { enabled: true } },
    "idotmatrix/studio/routine_start": { active: "r1", state: "starting" },
  });
  await wait(300);
  $('nav button[data-tab="routines"]').click();
  await wait(300);
  assert.ok($('.modebtn[data-mode="plan"]').classList.contains("on"));
  assert.match($("#modehint").textContent, /Planning/);
  // Slots are listed in the planning, ensembles only hold their GIFs.
  assert.equal(panel.shadowRoot.querySelectorAll("#sblocks .srow").length, 1);
  assert.equal($('[data-routine="r1"] .srow'), null);
  assert.match($('[data-routine="r1"]').textContent, /1 plage au planning/);
  const run = $('[data-run="r1"]');
  assert.equal(run.checked, false);
  run.checked = true;
  run.dispatchEvent(new Event("change", { bubbles: true }));
  await wait();
  assert.ok(calls.some((m) => m.type === "idotmatrix/studio/routine_start" && m.routine_id === "r1"));
  // Manuel now: the planning keeps its slots and waits.
  assert.equal(panel._sched.enabled, false);
  assert.ok($('.modebtn[data-mode="manual"]').classList.contains("on"));
  assert.equal(panel._sched.blocks.length, 1);
  // Back to Planning: saved at once.
  $('.modebtn[data-mode="plan"]').click();
  await wait();
  assert.equal(calls.filter((m) => m.type === "idotmatrix/studio/schedule_save").at(-1).schedule.enabled, true);
  // A slot can be switched off without losing its hours.
  const slot = $('#sblocks .srow [data-k="enabled"]');
  slot.checked = false;
  slot.dispatchEvent(new Event("change", { bubbles: true }));
  assert.equal(panel._sched.blocks[0].enabled, false);
  assert.equal($("#day .blk"), null);
  $("#saddSet").click();
  assert.deepEqual(panel._sched.blocks.at(-1), { from: "18:00", to: "22:00", action: "routine", routine_id: "r1", days: null });
});

test("deleting a folder with GIFs and originals only unfiles them", async () => {
  const { $, panel, calls } = await studio();
  $('#gfolders [data-folder="Chats"]').click();
  await wait();
  $("#gfolders [data-delfolder]").click();
  assert.equal(calls.filter((m) => m.type === "idotmatrix/studio/organize").length, 0, "a first tap only arms it");
  $("#gfolders [data-delfolder]").click();
  await wait(50);
  assert.deepEqual(calls.filter((m) => m.type === "idotmatrix/studio/organize").map((m) => [m.files, m.folder]), [[["a.gif"], ""]]);
  assert.equal(panel.originals[0].folder, "");
  assert.equal(panel.state.galleryFilter.folder, null);
});

test("the queue tab lists the Pi's jobs and cancels them", async () => {
  const { $, calls } = await studio({
    "idotmatrix/studio/jobs": { jobs: [
      { id: "j1", kind: "display", label: "chat.gif", display: "Salon", state: "sending", sent: 3, total: 10 },
      { id: "j2", kind: "display", label: "chien.gif", display: "Salon", state: "waiting" },
    ], routines: [{ entry_id: "a", display: "Salon", name: "Matin", status: { state: "showing", current: "chat.gif" } }] },
  });
  $('nav button[data-tab="queue"]').click();
  await wait();
  const text = $("#qpi").textContent;
  assert.match(text, /chat\.gif → Salon/);
  assert.match(text, /envoi au cadre 3\/10 paquets/);
  assert.match(text, /chien\.gif → Salon[\s\S]*en attente/);
  assert.match(text, /Routine « Matin »/);
  $('[data-cancel-pi="j2"]').click();
  await wait();
  assert.deepEqual(calls.filter((m) => m.type === "idotmatrix/studio/job_cancel").map((m) => m.id), ["j2"]);
  $('[data-stop-routine="a"]').click();
  await wait();
  assert.ok(calls.some((m) => m.type === "idotmatrix/studio/routine_stop" && m.entry_id === "a"));
  assert.match($("#qbrowser").textContent, /Rien en cours/);
  $('nav button[data-tab="gallery"]').click();
});

test("the routine editor filters the gallery by folder", async () => {
  const { $ } = await studio({
    "idotmatrix/studio/gallery": { items: [
      { file: "a.gif", title: "A", folder: "Chats", frames: 2, url: "/a.gif", modified: 1, size_bytes: 9, estimate_s: 1 },
      { file: "b.gif", title: "B", folder: "", frames: 2, url: "/b.gif", modified: 1, size_bytes: 9, estimate_s: 1 },
    ] },
    "idotmatrix/studio/routines": { routines: [], status: {} },
  });
  $('nav button[data-tab="routines"]').click();
  await wait();
  $("#newRoutine").click();
  await wait();
  const shown = () => [...$("#rpick").querySelectorAll(".pick")].map((el) => el.dataset.file);
  assert.deepEqual(shown(), ["a.gif", "b.gif"]);
  $("#rfolder").value = "Chats";
  $("#rfolder").dispatchEvent(new Event("change"));
  assert.deepEqual(shown(), ["a.gif"]);
  $("#rfolder").value = "";
  $("#rfolder").dispatchEvent(new Event("change"));
  assert.deepEqual(shown(), ["b.gif"]);
});

test("without folder handles (Brave, Firefox) a folder chosen for the visit is searched", async () => {
  const { $, panel } = await studio();
  $('nav button[data-tab="config"]').click();
  await wait();
  assert.match($("main").textContent, /Pour cette visite/);
  // Why it cannot keep folders here, and how to allow it.
  assert.match($("main").textContent, window.isSecureContext ? /ne sait pas garder un dossier/ : /unsafely-treat-insecure-origin-as-secure/);
  const input = $("#cvisitInput");
  const file = (path) => Object.assign(new window.File(["x"], path.split("/").pop(), { type: "video/mp4" }), { webkitRelativePath: path });
  Object.defineProperty(input, "files", { value: [file("Vidéos/2025/2025-05-01-190800.mp4"), file("Vidéos/notes.txt")], configurable: true });
  input.dispatchEvent(new Event("change"));
  await wait();
  assert.match($("#croots").textContent, /Vidéos/);
  assert.match($("#cinfo").textContent, /1 fichier/);
  const found = await panel._findSource({ name: "2025-05-01-190800_original_boomerang.gif" });
  assert.equal(found.name, "2025-05-01-190800.mp4");
});

test("a clicked point is followed from frame to frame, and the path meets every click", () => {
  const { trackPoint } = customElements.get("idotmatrix-studio");
  // A 5×5 red square on a textured background, moving 2 px right and 1 px down per frame.
  const tw = 64;
  const th = 48;
  const frames = Array.from({ length: 12 }, (_, f) => {
    const p = new Uint8Array(tw * th * 3);
    for (let i = 0; i < tw * th; i++) { p[i * 3] = (i * 7) % 50; p[i * 3 + 1] = (i * 13) % 60 + 40; p[i * 3 + 2] = 90; }
    for (let y = 10 + f; y < 15 + f; y++) for (let x = 8 + 2 * f; x < 13 + 2 * f; x++) p[(y * tw + x) * 3] = 250;
    return p;
  });
  const at = (f) => ({ x: (10 + 2 * f) / (tw - 1), y: (12 + f) / (th - 1) });
  const path = trackPoint(frames, tw, th, [{ i: 3, ...at(3) }], { radius: 3, search: 6 });
  for (const f of [0, 6, 11]) {
    assert.ok(Math.abs(path[f].x - at(f).x) < 0.04 && Math.abs(path[f].y - at(f).y) < 0.05, `frame ${f}`);
  }
  // Two clicks: exact on both.
  const two = trackPoint(frames, tw, th, [{ i: 1, ...at(1) }, { i: 9, ...at(9) }], { radius: 3, search: 6 });
  assert.deepEqual(two[9], at(9));
  assert.ok(Math.abs(two[5].x - at(5).x) < 0.04);
});

test("following, the square's size glides between zoom keys like its position", () => {
  const { cropAt } = customElements.get("idotmatrix-studio");
  const o = { crop: [0.25, 0.25, 0.2, 0.2], follow: true, track: [{ t: 0, x: 0.5, y: 0.5 }],
    zoom: [{ t: 0, s: 1 }, { t: 2, s: 2 }] };
  const size = (t) => +cropAt(o, t)[2].toFixed(3);
  assert.deepEqual([size(0), size(1), size(2), size(5)], [0.2, 0.3, 0.4, 0.4]);
  assert.deepEqual(cropAt(o, 2).map((v) => +v.toFixed(3)), [0.3, 0.3, 0.4, 0.4]);
  o.zoom = [{ t: 0, s: 9 }];  // never bigger than the image
  assert.equal(cropAt(o, 0)[2], 1);
  o.follow = false;
  assert.deepEqual(cropAt(o, 1), o.crop);
});

test("originals are found by name in the search folders, even from a gallery GIF's name", () => {
  const { matchSource } = customElements.get("idotmatrix-studio");
  const files = [
    { name: "2025-05-01-190800.mp4" }, { name: "2025-05-01.mp4" }, { name: "notes.txt" },
    { name: "Chat.MOV", size: 5 }, { name: "chat.mov", size: 9 },
  ];
  const find = (name, size, exact) => matchSource({ name, size }, files, exact)?.name ?? null;
  assert.equal(find("2025-05-01-190800_original_boomerang.gif"), "2025-05-01-190800.mp4");
  // Gallery slugs turn "-" into "_".
  assert.equal(find("2025_05_01_190800_boomerang"), "2025-05-01-190800.mp4");
  assert.equal(find("2025-05-01-190800.gif"), "2025-05-01-190800.mp4");
  assert.equal(find("chat.mov", 9), "chat.mov");
  assert.equal(find("2025-05-01-190800_x.gif", null, true), null);
  assert.equal(find("notes"), null);
});

test("🔗 in the gallery adds the original found in the search folders, linked to its GIF, sender shown", async () => {
  const { $, panel, calls } = await studio({
    "idotmatrix/studio/gallery": { items: [
      { file: "b.gif", title: "2025-05-01-190800_original_boomerang", folder: "Vacances", frames: 9, url: "/b.gif",
        modified: 1, size_bytes: 9, estimate_s: 1, device: "PC bureau", user: "Denis" },
    ] },
  });
  panel._searchFolders = async () => [{ id: "d1", name: "Vidéos" }];
  panel._sourceIndex = async () => [{ name: "2025-05-01-190800.mp4", size: null,
    handle: { getFile: async () => new window.File(["xx"], "2025-05-01-190800.mp4", { type: "video/mp4" }) } }];
  panel._loadFile = async (original) => { original.src = { kind: "video", width: 64, height: 64 }; };
  panel._renderGallery();
  await wait();
  assert.match($('.item[data-file="b.gif"]').textContent, /📤 PC bureau · Denis/);
  assert.deepEqual([...$("#gdev").options].map((o) => o.value), ["*", "PC bureau"]);
  $('.item[data-file="b.gif"] [data-act="link"]').click();
  await wait(50);
  const original = panel.originals.find((o) => o.name === "2025-05-01-190800.mp4");
  assert.ok(original);
  assert.equal(original.folder, "Vacances");
  const clip = panel.clips.find((c) => c.originalId === original.id);
  assert.equal(clip.pushed, "b.gif");
  assert.equal($('.item[data-file="b.gif"] [data-act="link"]'), null, "linked: no more 🔗");
  assert.ok(calls.length);
  // Another GIF of the same source reuses that original instead of adding a twin.
  panel.state.items.push({ file: "c.gif", title: "2025-05-01-190800_autre", folder: "", frames: 2, url: "/c.gif", modified: 1, size_bytes: 9 });
  const clip2 = await panel._linkGalleryItem(panel.state.items.at(-1));
  assert.equal(clip2.originalId, original.id);
  assert.equal(panel.originals.filter((o) => o.name === "2025-05-01-190800.mp4").length, 1);
});

test("a video this browser cannot read waits to be used: no conversion while relinking or drawing thumbnails", async () => {
  const { $, panel } = await studio();
  $('nav button[data-tab="workspace"]').click();
  await wait();
  const original = panel.originals[0];
  Object.assign(original, { missing: true, size: 2 });
  let converted = 0;
  panel._ensureSource = async () => { converted += 1; return {}; };
  await panel._relink(original, new window.File(["xx"], "chat.mp4", { type: "video/mp4" }));
  assert.equal(converted, 0);
  assert.equal(original.missing, false);
  original.needsCopy = true;
  panel._renderTree();
  const row = $('.orig[data-orig="o1"]');
  assert.match(row.textContent, /format à convertir/);
  row.querySelector('[data-act="convert"]').click();
  await wait();
  assert.equal(converted, 1);
});

test("⏭ skips to the next GIF of a routine driven by Home Assistant, not of a display carousel", async () => {
  const showing = { active: "r1", mode: "ha", state: "showing", current: "a.gif", next_at: 9e9 };
  const { $, calls } = await studio({
    "idotmatrix/studio/routines": { routines: [
      { id: "r1", name: "Matin", files: ["a.gif"], interval: 600, order: "random", mode: "ha" },
      { id: "r2", name: "Nuit", files: ["a.gif"], interval: 600, order: "random", mode: "carousel" },
    ], status: showing },
    "idotmatrix/studio/status": { display: "Cadre", displays: [], connected: true, screen_on: true,
      routine: showing, routine_name: "Matin", schedule_status: {} },
  });
  await wait(300);  // the status bar refreshes after 250 ms
  $('.sacts [data-sact="next"]').click();
  await wait();
  $('nav button[data-tab="routines"]').click();
  await wait();
  assert.equal($('[data-routine="r2"] [data-act="next"]'), null);
  $('[data-routine="r1"] [data-act="next"]').click();
  await wait();
  assert.equal(calls.filter((m) => m.type === "idotmatrix/studio/routine_next").length, 2);
});

test("no ⏭ while the display rotates its own carousel", async () => {
  const { $ } = await studio({
    "idotmatrix/studio/status": { display: "Cadre", displays: [], connected: true, screen_on: true,
      routine: { active: "r2", mode: "carousel", state: "carousel" }, routine_name: "Nuit", schedule_status: {} },
  });
  await wait(300);
  assert.ok($('.sacts [data-sact="stop"]'));
  assert.equal($('.sacts [data-sact="next"]'), null);
});

test("a routine's next GIFs show as thumbnails; a click shows that one now", async () => {
  const showing = { active: "r1", mode: "ha", state: "showing", current: "a.gif", upcoming: ["b.gif", "c.gif"], next_at: 9e9 };
  const { $, panel, calls } = await studio({
    "idotmatrix/studio/routines": { routines: [{ id: "r1", name: "Matin", files: ["a.gif", "b.gif", "c.gif"], interval: 600, order: "random", mode: "ha" }], status: showing },
    "idotmatrix/studio/status": { display: "Cadre", displays: [], connected: true, screen_on: true, routine: showing, routine_name: "Matin", schedule_status: {} },
  });
  await wait(300);
  const strip = () => [...panel.shadowRoot.querySelectorAll("#supnext .th")];
  assert.deepEqual(strip().map((b) => b.querySelector("img").dataset.thumb), ["a.gif", "b.gif", "c.gif"]);
  assert.ok(strip()[0].classList.contains("now") && !strip()[0].dataset.upnext);
  await wait();
  assert.equal(strip()[0].querySelector("img").src.endsWith("/signed"), true);  // the gallery's GIF, signed
  strip()[2].click();
  await wait();
  assert.deepEqual(calls.filter((m) => m.type === "idotmatrix/studio/routine_next").map((m) => m.file), ["c.gif"]);
  $('nav button[data-tab="routines"]').click();
  await wait();
  const row = [...panel.shadowRoot.querySelectorAll('[data-routine="r1"] .upnext [data-upnext]')];
  assert.deepEqual(row.map((b) => b.dataset.upnext), ["b.gif", "c.gif"]);
  row[0].click();
  await wait();
  assert.deepEqual(calls.filter((m) => m.type === "idotmatrix/studio/routine_next").map((m) => m.file), ["c.gif", "b.gif"]);
});

test("a display carousel shows its slots with the one it probably shows", async () => {
  const started = Date.now() / 1000 - 125;  // 2 intervals of 60 s ago, and a bit
  const { panel } = await studio({
    "idotmatrix/studio/status": { display: "Cadre", displays: [], connected: true, screen_on: true, schedule_status: {},
      routine: { active: "r2", mode: "carousel", state: "carousel", carousel: ["a.gif", "b.gif", "c.gif", "d.gif"], carousel_at: started, interval: 60 }, routine_name: "Nuit" },
  });
  await wait(300);
  const slots = [...panel.shadowRoot.querySelectorAll("#supnext .th")];
  assert.deepEqual(slots.map((b) => b.textContent), ["1", "2", "3", "4"]);
  assert.deepEqual(slots.map((b) => b.classList.contains("est")), [false, false, true, false]);
  assert.ok(slots.every((b) => !b.dataset.upnext));  // no command reaches a slot
});

test("the 📜 tab lists the log, filters it, exports it as text, and browser entries reach the Pi", async () => {
  const entries = [
    { seq: 1, t: 1700000000, source: "pi", kind: "encode", msg: "Chat : 120 images → 80, 210 Ko", data: { frames_in: 120, gif: { first_frame_bytes: 4000 } } },
    { seq: 2, t: 1700000010, source: "pi", kind: "transfer", msg: "chat.gif → Salon : 52 paquets", data: { packets: 52 } },
    { seq: 3, t: 1700000020, source: "browser", kind: "source", msg: "Original chat.mp4 lu" },
  ];
  const { $, panel, calls } = await studio({ "idotmatrix/studio/log": { entries } });
  $('nav button[data-tab="log"]').click();
  await wait();
  const rows = () => [...panel.shadowRoot.querySelectorAll("#log .logrow")];
  assert.equal(rows().length, 3);
  assert.match(rows()[0].textContent, /Original chat\.mp4 lu/);  // newest first
  $("#lkind").value = "encode";
  $("#lkind").dispatchEvent(new Event("change"));
  assert.equal(rows().length, 1);
  assert.match(rows()[0].querySelector("pre").textContent, /first_frame_bytes/);
  const text = panel._logText();
  assert.match(text, /\[pi\] encode: Chat : 120 images/);
  assert.match(text, /"frames_in":120/);
  // A new entry from the Pi shows up at once.
  panel._onLog({ seq: 4, t: 1700000030, source: "pi", kind: "encode", msg: "Chien : 30 images" });
  assert.equal(rows().length, 2);
  panel._log("browser", "planche envoyée", { upload_ms: 120 });
  await wait(600);
  const sent = calls.filter((m) => m.type === "idotmatrix/studio/log_add").flatMap((m) => m.entries);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].data.upload_ms, 120);
  assert.match(sent[0].msg, /^planche envoyée · /);
});

test("overlapping slots: the strip shows the winner on top and a slot's priority can be set", async () => {
  const blocks = [
    { from: "00:00", to: "00:00", action: "routine", routine_id: "r1", days: null },
    { from: "19:00", to: "20:00", action: "routine", routine_id: "r2", days: null },
  ];
  const { $, panel } = await studio({
    "idotmatrix/studio/routines": { routines: [
      { id: "r1", name: "Fond", files: ["a.gif"], interval: 600, order: "random", mode: "ha" },
      { id: "r2", name: "Violon", files: ["a.gif"], interval: 600, order: "random", mode: "ha" },
    ], status: {} },
    "idotmatrix/studio/status": { display: "Cadre", displays: [], connected: true, screen_on: true, routine: {},
      schedule: { enabled: true, blocks, gaps: "off" }, schedule_status: {} },
  });
  await wait(300);
  $('nav button[data-tab="routines"]').click();
  await wait(300);
  const drawn = () => [...panel.shadowRoot.querySelectorAll("#day .blk")].map((b) => b.dataset.i);
  assert.deepEqual(drawn(), ["0", "1"]);  // the short slot on top of the all-day one
  const select = $('#sblocks .srow[data-i="0"] select[data-k="priority"]');
  select.value = "2";
  select.dispatchEvent(new Event("change", { bubbles: true }));
  assert.equal(panel._sched.blocks[0].priority, 2);
  assert.deepEqual(drawn(), ["1", "0"]);  // now the all-day one wins
  assert.match($("#shint").textContent, /priorité la plus haute/);
});

test("render presets are recognised from a clip's settings; anything else is « Personnalisé »", () => {
  const { renderOf, RENDERS } = customElements.get("idotmatrix-studio");
  for (const render of RENDERS) {
    const opts = Object.fromEntries(["max_fps", "colors", "fuzz", "merge_similar", "dither"].map((k) => [k, render[k]]));
    assert.equal(renderOf(opts), render.key);
  }
  assert.equal(renderOf({ fuzz: 24 }), "custom");  // the old default: 256 colours, no cap
  assert.equal(renderOf({ max_fps: 10, colors: 64, fuzz: 24, dither: false }), "rapide");
});

test("the log describes a clip second by second", async () => {
  const { panel, $, calls } = await studio();
  const still = (v) => ({ data: { width: 2, height: 2, data: new Uint8ClampedArray(16).fill(v) } });
  const frames = [0, 0.5, 1, 1.5, 2].map((t, i) => ({ ...still(i < 3 ? 0 : 200), t, ms: 500 }));
  const clip = { title: "Chat", opts: { crop: [0.25, 0, 0.5, 1] }, src: { width: 400, height: 200 } };
  const info = panel._clipSeconds(clip, frames);
  assert.deepEqual(info.source_size, [400, 200]);
  assert.deepEqual(info.per_second.map((s) => [s.t, s.crop, s.motion]), [[0, [100, 0, 200, 200], 0], [1, [100, 0, 200, 200], 50], [2, [100, 0, 200, 200], 0]]);
});

test("« Refaire en Équilibré » redoes the Pi's GIFs from their sources here, after a second tap", async () => {
  const { $, panel } = await studio();
  const original = panel.originals[0];
  original.file = new window.File(["x"], "chat.mp4", { type: "video/mp4" });
  Object.assign(original, { missing: false });
  const clip = panel.clips[0];
  Object.assign(clip, { pushed: "chat.gif", opts: { ...clip.opts, colors: 256, fuzz: 0, max_fps: 0, merge_similar: false } });
  const pushed = [];
  panel._push = (c, display) => { pushed.push([c.id, display]); return Promise.resolve(true); };
  $('nav button[data-tab="workspace"]').click();
  await wait();
  assert.match($("#redoAll").textContent, /\(1\)/);
  $("#redoAll").click();                       // first tap only arms it
  assert.deepEqual(pushed, []);
  $("#redoAll").click();
  assert.deepEqual(pushed, [["c1", false]]);
  assert.deepEqual([clip.opts.colors, clip.opts.fuzz, clip.opts.max_fps, clip.dirty], [128, 8, 15, true]);
});

test("« Envoyer en nouveau clip » sends the edit as a new clip and puts the edited one back", async () => {
  const { panel } = await studio();
  const clip = panel.clips[0];
  Object.assign(clip, { pushed: "chat.gif", opts: { ...clip.opts, speed: 1 } });
  panel._opened = { opts: structuredClone(clip.opts), title: clip.title, dirty: false };
  panel.current = clip;
  clip.opts.speed = 2;                            // the edit
  const pushed = [];
  panel._push = (c, display) => { pushed.push([c, display]); return Promise.resolve(true); };
  panel._main().innerHTML = `<input id="title" value="${clip.title}">`;
  const opened = [];
  panel._openEditor = async (c) => { opened.push(c); };
  await panel._saveAsNewClip();
  const [[copy, display]] = pushed;
  assert.equal(display, false);
  assert.notEqual(copy.id, clip.id);
  assert.deepEqual([copy.opts.speed, copy.title, copy.pushed], [2, "Chat (copie)", null]);
  assert.deepEqual([clip.opts.speed, clip.pushed], [1, "chat.gif"]);   // the original and its GIF are untouched
  assert.equal(panel.clips.length, 2);
  assert.deepEqual(opened, [copy]);                                     // editing goes on, on the new clip
});

test("✋ Suivi perso records the square over the moments played through, and a loop jump erases nothing", async () => {
  const { panel } = await studio();
  const clip = panel.clips[0];
  const auto = Array.from({ length: 30 }, (_, i) => ({ t: i / 10, x: 0.5, y: 0.5 }));   // a dense automatic path
  Object.assign(clip.opts, { crop: [0.25, 0, 0.5, 1], follow: true, manual: true, track: auto, zoom: [] });
  panel.current = clip;
  panel._drawKeys = () => {};
  const drag = { current: [0.1, 0, 0.5, 1], lastT: 1.0, manual: true };
  for (const t of [1.1, 1.2, 1.5, 2.0]) panel._recordCrop(drag, t);   // held while the video plays
  const between = clip.opts.track.filter((k) => k.t > 1.0 && k.t <= 2.0);
  assert.deepEqual(between.map((k) => k.t), [1.1, 1.2, 1.5, 2.0]);       // every step kept, the automatic ones gone
  assert.ok(between.every((k) => k.x === 0.35), "the stretch played through follows the held square");
  assert.ok(clip.opts.track.some((k) => k.t === 0.5 && k.x === 0.5), "before it, the path is untouched");
  assert.ok(clip.opts.track.some((k) => k.t === 2.5 && k.x === 0.5), "after it too");
  panel._recordCrop(drag, 0.2);                                           // the loop jumped back to the start
  assert.ok(clip.opts.track.some((k) => k.t === 1.5 && k.x === 0.35), "the jump did not erase the recording");
  assert.deepEqual(clip.opts.zoom.map((k) => k.s), [1, 1, 1, 1, 1]);
});

test("search, filters, folders and the selection bar sit in one bar that stays in view", async () => {
  const { $, panel } = await studio();
  for (const id of ["gq", "gkind", "gfolders", "gselbar"]) assert.ok($(`.filterbar #${id}`), id);
  $('nav button[data-tab="workspace"]').click();
  await wait();
  for (const id of ["q", "fstatus", "wfolders", "wselbar"]) assert.ok($(`.filterbar #${id}`), id);
  assert.ok(panel._topObserver);  // keeps the bar right under the header and status bar
});

test("the editor asks the Pi for one preview at a time, then only the latest", async () => {
  const { panel } = await studio();
  panel.state.tab = "editor";
  panel.shadowRoot.querySelector("main").innerHTML = `<div id="final"></div>`;
  const w = { id: "c1", opts: {}, frames: [{ ms: 100 }] };
  panel.current = w;
  let release;
  const asked = [];
  panel._encode = (clip, { save }) => {
    asked.push(save);
    return new Promise((resolve) => { release = () => resolve({ superseded: true }); });
  };
  panel._estimate();
  panel._estimate();  // settings changed twice while the first preview encodes
  panel._estimate();
  await wait();
  assert.equal(asked.length, 1);
  release();
  await wait();
  assert.equal(asked.length, 2);  // the latest settings, once
  release();
  await wait();
  assert.equal(asked.length, 2);
});

test("from the editor, the clip or its original (with all its clips) goes to the workspace trash after a second tap", async () => {
  const { panel } = await studio();
  const original = panel.originals[0];
  const clip = panel.clips[0];
  const second = { ...clip, id: "c2", title: "Chat 2" };
  panel.clips.push(second);
  const button = () => { const b = document.createElement("button"); panel.shadowRoot.appendChild(b); return b; };
  panel.current = second;
  const del = button();
  panel._editorDelete("clip", del);
  assert.ok(panel.clips.includes(second), "a first tap only arms it");
  panel._editorDelete("clip", del);
  assert.ok(!panel.clips.includes(second) && panel.trash.clips.includes(second));
  assert.equal(panel.state.tab, "workspace");
  // The original takes its remaining clips with it.
  panel.current = clip;
  const delAll = button();
  panel._editorDelete("original", delAll);
  panel._editorDelete("original", delAll);
  assert.ok(!panel.originals.includes(original) && panel.trash.originals.includes(original));
  assert.ok(!panel.clips.includes(clip) && panel.trash.clips.includes(clip));
});

test("a folder can be hidden everywhere (« Tous » included) and shown again", async () => {
  let hidden = [];
  const { $, panel, chips, calls } = await studio({
    "idotmatrix/studio/gallery": () => ({ items: [
      { file: "a.gif", title: "A", folder: "Chats", frames: 2, url: "/a.gif", modified: 1, size_bytes: 9, estimate_s: 1 },
      { file: "b.gif", title: "B", folder: "", frames: 2, url: "/b.gif", modified: 1, size_bytes: 9, estimate_s: 1 },
    ], collections: [], hidden_folders: hidden }),
    "idotmatrix/studio/folder_hidden": (m) => { hidden = m.hidden ? [m.folder] : []; return { hidden_folders: hidden }; },
  });
  $('#gfolders [data-folder="Chats"]').click();
  await wait();
  $("#gfolders [data-hidefolder]").click();
  await wait();
  assert.deepEqual(calls.filter((m) => m.type === "idotmatrix/studio/folder_hidden").map((m) => [m.folder, m.hidden]), [["Chats", true]]);
  // Out of sight: no chip, and its GIF left « Tous ».
  assert.ok(!chips("gfolders").some((c) => c.includes("Chats")));
  assert.ok(chips("gfolders").includes("Tous 1"));
  assert.deepEqual([...panel.shadowRoot.querySelectorAll(".grid .item")].map((e) => e.dataset.file), ["b.gif"]);
  // 👁 shows the hidden ones, marked 🙈, until masked again.
  $("#gfolders [data-showhidden]").click();
  await wait();
  assert.ok(chips("gfolders").some((c) => c.startsWith("🙈 Chats")));
  assert.equal(panel.shadowRoot.querySelectorAll(".grid .item").length, 2);
  $('#gfolders [data-folder="Chats"]').click();
  await wait();
  $("#gfolders [data-hidefolder]").click();
  await wait();
  assert.deepEqual(calls.filter((m) => m.type === "idotmatrix/studio/folder_hidden").at(-1).hidden, false);
});

test("collections: GIFs picked from any folder with the selection bar, shown in their order, removable", async () => {
  let collections = [{ id: "k1", name: "Soirée", files: ["b.gif"] }];
  const { $, panel, calls } = await studio({
    "idotmatrix/studio/gallery": () => ({ items: [
      { file: "a.gif", title: "A", folder: "Chats", frames: 2, url: "/a.gif", modified: 1, size_bytes: 9, estimate_s: 1 },
      { file: "b.gif", title: "B", folder: "Chiens", frames: 2, url: "/b.gif", modified: 1, size_bytes: 9, estimate_s: 1 },
    ], collections: structuredClone(collections), hidden_folders: [] }),
    "idotmatrix/studio/collection_save": (m) => {
      let c = collections.find((x) => x.id === m.id);
      if (!c) collections.push(c = { id: m.id, name: m.name, files: [] });
      c.files = c.files.filter((f) => !(m.remove || []).includes(f)).concat((m.add || []).filter((f) => !c.files.includes(f)));
      return c;
    },
  });
  assert.match($("#gcols").textContent, /Soirée\s*1/);
  // Add « a.gif » (folder Chats) to « Soirée » (which holds b.gif from Chiens).
  panel.shadowRoot.querySelector('.item[data-file="a.gif"] [data-act="check"]').click();
  await wait();
  $("#gcol").value = "Soirée";
  $('#gselbar [data-sel="collect"]').click();
  await wait();
  assert.deepEqual(calls.filter((m) => m.type === "idotmatrix/studio/collection_save").at(-1), { type: "idotmatrix/studio/collection_save", id: "k1", name: "Soirée", add: ["a.gif"] });
  $('#gcols [data-col="k1"]').click();
  await wait();
  assert.deepEqual([...panel.shadowRoot.querySelectorAll(".grid .item")].map((e) => e.dataset.file), ["b.gif", "a.gif"]);
  assert.ok($('#gselbar [data-sel="uncollect"]'));
  $('#gselbar [data-sel="uncollect"]').click();
  await wait();
  assert.deepEqual(collections[0].files, ["b.gif"]);
});

test("an ensemble can take the GIFs of a collection instead of a picked list", async () => {
  const { $, calls } = await studio({
    "idotmatrix/studio/gallery": { items: [
      { file: "a.gif", title: "A", folder: "Chats", frames: 2, url: "/a.gif", modified: 1, size_bytes: 9, estimate_s: 1 },
    ], collections: [{ id: "k1", name: "Soirée", files: ["a.gif"] }], hidden_folders: [] },
    "idotmatrix/studio/routines": { routines: [], status: {} },
  });
  $('nav button[data-tab="routines"]').click();
  await wait();
  $("#newRoutine").click();
  await wait();
  const source = $("#rsource");
  source.value = "k1";
  source.dispatchEvent(new Event("change"));
  assert.equal($("#rpick").style.display, "none");
  $("#rsave").click();
  await wait();
  const saved = calls.find((m) => m.type === "idotmatrix/studio/routine_save").routine;
  assert.equal(saved.collection, "k1");
  assert.deepEqual(saved.files, []);
});

test("an error from Home Assistant without a message still says what went wrong", async () => {
  const { $ } = await studio({
    "idotmatrix/studio/folder_hidden": () => { throw { code: "unknown_command" }; },  // eslint-disable-line no-throw-literal
  });
  $('#gfolders [data-folder="Chats"]').click();
  await wait();
  $("#gfolders [data-hidefolder]").click();
  await wait();
  const shown = $(".status .transfer").textContent;
  assert.match(shown, /unknown_command/);
  assert.doesNotMatch(shown, /object Object/);
});

test("folder, collection and card actions sit in ⋯ menus that open on screen, one at a time", async () => {
  const { $, panel } = await studio();
  $('#gfolders [data-folder="Chats"]').click();
  await wait();
  const menu = $("#gfolders details.menu");
  for (const act of ["newfolder", "renamefolder", "hidefolder", "delfolder"]) assert.ok(menu.querySelector(`[data-${act}]`), act);
  const card = panel.shadowRoot.querySelector('.item[data-file="a.gif"]');
  // On the card: ▶ and ★ in view, the rest in its menu.
  assert.deepEqual([...card.querySelectorAll(".tools > button")].map((b) => b.dataset.act), ["display", "favorite"]);
  assert.deepEqual([...card.querySelectorAll(".menu-list [data-act]")].map((b) => b.dataset.act), ["edit", "link", "folder", "delete"]);
  const cardMenu = card.querySelector("details.menu");
  menu.open = true;
  menu.dispatchEvent(new Event("toggle"));
  cardMenu.open = true;
  cardMenu.dispatchEvent(new Event("toggle"));
  assert.equal(menu.open, false);  // only one open
  assert.ok(cardMenu.querySelector(".menu-list").style.top);
  $(".grid").click();
  assert.equal(cardMenu.open, false);  // a click elsewhere closes it
});

test("« Vider la corbeille » erases everything in it for good after a second tap", async () => {
  const { $, panel, synced } = await studio();
  $('nav button[data-tab="workspace"]').click();
  await wait();
  $('.orig[data-orig="o1"] [data-act="delorig"]').click();
  await wait(1200);
  $('#wfolders [data-folder="__corbeille__"]').click();
  await wait();
  $('[data-tact="purgeAll"]').click();
  assert.equal(panel._trashTotal(), 2, "a first tap only arms it");
  $('[data-tact="purgeAll"]').click();
  await wait(1200);
  assert.equal(panel._trashTotal(), 0);
  assert.equal(panel.state.filter.folder, null);  // back to the workspace, the trash chip gone
  // Gone for good on every device: sent as deletions.
  const deleted = synced.flatMap((m) => [...m.delete_originals, ...m.delete_clips]);
  assert.ok(deleted.includes("o1") && deleted.includes("c1"));
});

test("renaming or making a folder from the ⋯ menu opens the field in the chip row, not inside the closing menu", async () => {
  const { $, panel } = await studio();
  $('#gfolders [data-folder="Chats"]').click();
  await wait();
  $("#gfolders details.menu").open = true;
  $("#gfolders [data-renamefolder]").click();
  const input = $("#gfolders > .chip-input");
  assert.ok(input, "the field sits in the row");
  assert.equal($("#gfolders details.menu"), null);  // in place of the ⋯ menu
  assert.equal(input.value, "Chats");
  window.dispatchEvent(new Event("scroll"));  // closing menus no longer hides it
  assert.ok(input.isConnected);
  // The card's « Ranger » too.
  const card = panel.shadowRoot.querySelector('.item[data-file="a.gif"]');
  card.querySelector('[data-act="folder"]').click();
  await wait();
  assert.ok(card.querySelector(".tools > .chip-input"));
});

const WEATHER_SOURCES = {
  home_assistant: true, home: { name: "Maison", entity_id: "weather.forecast_home" },
  entities: [{ entity_id: "weather.forecast_home", name: "Forecast Maison" }],
  zones: [{ entity_id: "zone.travail", name: "Travail" }],
};
const PREVIEW = {
  png: "data:image/png;base64,iVBORw0KGgo=", size: 64, minute_bytes: 4762, minute_s: 1,
  forecast: { place: "Maison", condition: "rainy", temperature: 12.4, unit: "°C", high: 15, low: 6, rain: 40, fetched: 1 },
};
PREVIEW.forecasts = [PREVIEW.forecast];
const change = (el, value) => {
  if (value !== undefined) el.value = value;
  el.dispatchEvent(new Event("change", { bubbles: true }));
};

test("Météo: the tab previews Home Assistant's weather and saves its options as a weather routine", async () => {
  const { $, calls } = await studio({
    "idotmatrix/studio/routines": { routines: [], status: {} },
    "idotmatrix/studio/weather_sources": WEATHER_SOURCES,
    "idotmatrix/studio/weather_preview": PREVIEW,
    "idotmatrix/studio/routine_start": { active: "w", mode: "weather", state: "starting" },
  });
  $('nav button[data-tab="weather"]').click();
  await wait(50);
  assert.equal($('[data-p="0"] [data-k=source]').value, "home");
  assert.ok($('[data-p="0"] [data-placerow]').hidden);
  assert.match($("#wsummary").textContent, /Maison · 12°C · ↑15 ↓6 · pluie 40 %/);
  assert.match($("#wsize").textContent, /4\.7 Ko, 2 paquets Bluetooth/);
  const previews = () => calls.filter((c) => c.type === "idotmatrix/studio/weather_preview");
  assert.equal(previews()[0].weather.profiles[0].source, "home");
  assert.equal(previews()[0].minute, true);
  // A zone, the next days, the clock in orange, no seconds, brightness by the sun.
  change($('[data-p="0"] [data-k=source]'), "zone:zone.travail");
  $('input[name=wstrip][value="days"]').checked = true;
  change($('input[name=wstrip][value="days"]'));
  $("#wcolor").value = "#ff8000";
  $("#wsec").checked = false;
  $("#wbright").checked = true;
  change($("#wbright"));
  await wait(50);
  const asked = previews().at(-1).weather;
  assert.deepEqual([asked.profiles[0].source, asked.profiles[0].zone, asked.strip, asked.clock_color, asked.seconds],
    ["zone", "zone.travail", "days", "#ff8000", false]);
  assert.deepEqual(asked.brightness, { day: 100, night: 20 });
  assert.equal($("#wstart"), null);  // no button: a change goes on the display by itself
  await wait(1000);
  const saved = calls.find((c) => c.type === "idotmatrix/studio/routine_save").routine;
  assert.deepEqual([saved.mode, saved.interval, saved.files], ["weather", 1800, []]);
  assert.equal(saved.weather.profiles[0].zone, "zone.travail");
  assert.equal(calls.findLast((c) => c.type === "idotmatrix/studio/routine_start").routine_id, saved.id);
});

test("Météo: each screen its own city — changing it on a copy leaves the first one alone; the strip's 4 hours", async () => {
  const { $, calls } = await studio({
    "idotmatrix/studio/routines": { routines: [], status: {} },
    "idotmatrix/studio/weather_sources": WEATHER_SOURCES,
    "idotmatrix/studio/weather_geocode": { places: [{ name: "Crépy-en-Valois, Hauts-de-France, France", latitude: 49.23, longitude: 2.89 }] },
    "idotmatrix/studio/weather_preview": { ...PREVIEW, titles: [{ title: "Maison", key: "screen:0", screen: 0 }] },
  });
  $('nav button[data-tab="weather"]').click();
  await wait(50);
  const last = () => calls.filter((c) => c.type === "idotmatrix/studio/weather_preview").at(-1).weather;
  assert.equal($("#wswitch"), null);  // one city: nothing takes turns
  // Screen 2: a copy of screen 1, then another city for it alone.
  $('#wpagenums [data-wnum="plus"]').click();
  $('#wcopygrid [data-wcopy="0"]').click();
  await wait(50);
  assert.match($("#wprofiles").textContent, /Ville de l'écran 2.*la même que l'écran 1/s);
  change($('#wprofiles [data-k=source]'), "place");
  await wait(50);
  $('#wprofiles [data-k=q]').value = "Crépy";
  $('#wprofiles [data-find]').click();
  await wait(50);
  $('#wprofiles [data-place]').click();
  $('#wprofiles [data-k=label]').value = "Crépy";
  change($('#wprofiles [data-k=label]'));
  await wait(50);
  const w = last();
  assert.equal(w.profiles.length, 2);
  assert.equal(w.profiles[0].source, "home");  // screen 1 keeps its city
  assert.deepEqual([w.screens[0].place, w.screens[1].place], [0, 1]);
  assert.equal(w.profiles[1].place.name, "Crépy-en-Valois, Hauts-de-France, France");
  assert.equal(w.profiles[1].label, "Crépy");
  // Two cities' screens: their change typed in.
  change($("#wswitch"), "3");
  change($("#whmode"), "at");
  const at = [...document.body.querySelector("idotmatrix-studio").shadowRoot.querySelectorAll("[data-at]")];
  ["8", "12", "18", "21"].forEach((h, i) => { at[i].value = h; });
  change(at[3]);
  await wait(50);
  assert.equal(last().switch_seconds, 3);
  assert.deepEqual(last().screens.map((sc) => sc.seconds), [3, 3]);
  assert.deepEqual(last().hours_at, [8, 12, 18, 21]);
  // The copy deleted: its city goes with it.
  $("#wscrdel").click();
  $("#wscrdel").click();
  await wait(50);
  assert.equal(last().profiles.length, 1);
});

test("Météo without Home Assistant: a place is typed in, found and previewed", async () => {
  const { $, calls } = await studio({
    "idotmatrix/studio/routines": { routines: [], status: {} },
    "idotmatrix/studio/weather_sources": { home_assistant: false, entities: [], zones: [], home: null },
    "idotmatrix/studio/weather_geocode": { places: [{ name: "Lyon, Auvergne-Rhône-Alpes, France", latitude: 45.75, longitude: 4.85 }] },
    "idotmatrix/studio/weather_preview": { ...PREVIEW, forecasts: [{ ...PREVIEW.forecast, place: "Lyon" }] },
  });
  $('nav button[data-tab="weather"]').click();
  await wait(50);
  assert.equal($('[data-p="0"] [data-k=source]').value, "place");
  assert.equal($('[data-p="0"] [data-placerow]').hidden, false);
  assert.ok(!calls.some((c) => c.type === "idotmatrix/studio/weather_preview"));  // no place yet
  $('[data-p="0"] [data-k=q]').value = "Lyon";
  $('[data-p="0"] [data-find]').click();
  await wait(50);
  assert.equal(calls.findLast((c) => c.type === "idotmatrix/studio/weather_geocode").query, "Lyon");
  $('[data-p="0"] [data-place]').click();
  await wait(50);
  const asked = calls.findLast((c) => c.type === "idotmatrix/studio/weather_preview").weather;
  assert.deepEqual(asked.profiles[0].place, { name: "Lyon, Auvergne-Rhône-Alpes, France", latitude: 45.75, longitude: 4.85 });
  assert.match($("#wsummary").textContent, /Lyon/);
});

test("a weather routine is listed with the others, goes in the planning and opens in the Météo tab", async () => {
  // Saved before profiles: its one place at the top.
  const weather = { id: "w1", name: "Météo", files: [], interval: 900, order: "sequence", mode: "weather", hours: null,
    weather: { source: "place", place: { name: "Lyon", latitude: 45.75, longitude: 4.85 }, strip: "hours", hour24: true } };
  const { $, panel } = await studio({
    "idotmatrix/studio/routines": { routines: [weather], status: { active: "w1", mode: "weather", state: "showing", next_at: 2,
      weather: { place: "Lyon", temperature: 12, fetched: 1 } } },
    "idotmatrix/studio/weather_sources": WEATHER_SOURCES,
    "idotmatrix/studio/weather_preview": PREVIEW,
  });
  $('nav button[data-tab="routines"]').click();
  await wait(50);
  const row = $('[data-routine="w1"]');
  assert.match(row.textContent, /🌤 Lyon · l'heure et les secondes, les prochaines heures, météo toutes les 15 min/);
  assert.match(row.textContent, /🌤 Lyon 12°/);
  assert.equal(row.querySelector('[data-act="next"]'), null);  // nothing to skip to
  $("#saddSet").click();
  await wait();
  assert.match($("#sblocks select[data-k=what]").textContent, /🌤 Météo/);
  $('[data-routine="w1"] [data-act="edit"]').click();
  await wait(50);
  assert.equal(panel.state.tab, "weather");
  assert.equal($("#wname").value, "Météo");
  assert.equal($('[data-p="0"] [data-k=q]').value, "Lyon");
  assert.equal($("#wstop").hidden, false);
});

test("Météo: picking a part of the preview keeps only its settings, and resizes, removes or puts it back", async () => {
  const { $, calls, panel } = await studio({
    "idotmatrix/studio/routines": { routines: [], status: {} },
    "idotmatrix/studio/weather_sources": WEATHER_SOURCES,
    "idotmatrix/studio/weather_preview": { ...PREVIEW, boxes: { clock: [6, 0, 58, 14], name: [24, 15, 40, 20], today: [0, 21, 63, 37], strip: [0, 38, 63, 63] } },
  });
  $('nav button[data-tab="weather"]').click();
  await wait(50);
  const last = () => calls.findLast((c) => c.type === "idotmatrix/studio/weather_preview").weather;
  const shown = () => [...panel.shadowRoot.querySelectorAll(".wform [data-zone]")].filter((r) => r.style.display !== "none").map((r) => r.dataset.zone);
  assert.ok(shown().includes("strip") && shown().includes("clock"));  // nothing picked: every setting
  // A view from before: one screen, the weather as it was.
  assert.deepEqual(Object.keys(last().screens[0].parts), ["clock", "seconds", "date", "name", "today", "strip"]);
  $('#wzones [data-wzone="clock"]').click();
  await wait();
  assert.deepEqual([...new Set(shown())], ["clock"]);
  assert.notEqual($("#wedit").style.display, "none");
  $('#wedit [data-wedit="smaller"]').click();
  await wait(50);
  assert.equal(last().screens[0].parts.clock.size, 1);
  $("#wolOn").checked = true;
  change($("#wolOn"));
  await wait(50);
  assert.equal(last().screens[0].parts.clock.outline, "#ffffff");
  $('#wedit [data-wedit="reset"]').click();
  await wait(50);
  assert.deepEqual(last().screens[0].parts.clock, { outline: "#ffffff" });  // back in place, outlined still
  $('#wedit [data-wedit="remove"]').click();
  await wait(50);
  assert.equal(last().screens[0].parts.clock, undefined);
  // The flip cards (HTC).
  $('input[name=wstyle][value="flip"]').checked = true;
  $('input[name=wstyle][value="flip"]').dispatchEvent(new Event("change", { bubbles: true }));
  await wait(50);
  assert.equal(last().clock_style, "flip");
  $('#wzones [data-wzone=""]').click();
  await wait();
  assert.ok(shown().includes("strip"));
  $("#wgridbtn").click();
  assert.ok($("#wgridbtn").classList.contains("on"));
});

test("Météo: a part in its own box, its colour, aligned, its text on one line", async () => {
  const { $, calls } = await studio({
    "idotmatrix/studio/routines": { routines: [], status: {} },
    "idotmatrix/studio/weather_sources": WEATHER_SOURCES,
    "idotmatrix/studio/weather_preview": { ...PREVIEW, boxes: { clock: [6, 0, 58, 14], name: [24, 15, 40, 20], today: [0, 21, 63, 37], strip: [0, 38, 63, 63] } },
  });
  $('nav button[data-tab="weather"]').click();
  await wait(50);
  const last = () => calls.findLast((c) => c.type === "idotmatrix/studio/weather_preview").weather;
  $('#wzones [data-wzone="today"]').click();
  await wait();
  $('#wedit [data-wedit="box"]').click();  // its box: where it is, a little room around
  await wait(50);
  assert.deepEqual(last().screens[0].parts.today.box, [0, 20, 64, 18]);
  assert.ok($("#wboxbtn").classList.contains("on"));
  $('#wedit [data-wedit="smaller"]').click();  // the box shrinks around its middle
  await wait(50);
  assert.deepEqual(last().screens[0].parts.today.box, [2, 22, 60, 14]);
  $('#wedit [data-wplace="tl"]').click();
  await wait(50);
  assert.deepEqual(last().screens[0].parts.today.box, [0, 0, 60, 14]);
  $('#wedit [data-wmove="1,0"]').click();
  await wait(50);
  assert.deepEqual(last().screens[0].parts.today.box, [1, 0, 60, 14]);
  $("#wcolOn").checked = true;
  $("#wcol").value = "#ff0000";
  change($("#wcolOn"));
  await wait(50);
  assert.equal(last().screens[0].parts.today.color, "#ff0000");
  $('#walign [data-walign="right"]').click();
  await wait(50);
  assert.equal(last().screens[0].parts.today.align, "right");
  assert.equal($("#wlines").style.display, "none");  // the weather has no text to put on one line
  $('#wedit [data-wedit="reset"]').click();  // back in place, in its colour still
  await wait(50);
  assert.deepEqual(last().screens[0].parts.today, { color: "#ff0000" });
  // Aligning a part without a box: its row across the frame.
  $('#wzones [data-wzone="clock"]').click();
  await wait();
  $('#walign [data-walign="left"]').click();
  await wait(50);
  assert.deepEqual(last().screens[0].parts.clock, { box: [0, 0, 64, 14], align: "left" });
});

test("Météo: screens numbered above the preview, « + » adds one empty or ready-made, each filled and timed", async () => {
  const { $, calls, panel } = await studio({
    "idotmatrix/studio/routines": { routines: [], status: {} },
    "idotmatrix/studio/weather_sources": WEATHER_SOURCES,
    "idotmatrix/studio/weather_preview": { ...PREVIEW, boxes: { clock: [6, 0, 58, 14] }, page: 0,
      titles: [{ title: "Maison", key: "screen:0", screen: 0 }, { title: "Saint du jour", key: "screen:1", screen: 1, off: true }] },
  });
  $('nav button[data-tab="weather"]').click();
  await wait(50);
  const last = () => calls.findLast((c) => c.type === "idotmatrix/studio/weather_preview");
  const nums = () => [...panel.shadowRoot.querySelectorAll("#wpagenums [data-wnum]")];
  assert.deepEqual(nums().map((b) => b.textContent.trim()), ["1", "2", "+", "▶"]);
  assert.ok(nums()[1].classList.contains("off"));  // nothing to show now: greyed
  $('#wpagenums [data-wnum="plus"]').click();
  $('#wpresets [data-wpreset="saint"]').click();
  await wait(50);
  assert.deepEqual(Object.keys(last().weather.screens[1].parts), ["clock", "saint"]);  // the seconds go with the clock
  assert.equal(last().page, 1);  // the new screen, shown to be set
  // Its parts: one taken off, another added; its time and its hours.
  $('#wscrparts [data-wunpart="clock"]').click();
  $('#waddparts [data-wadd="countdown"]').click();  // lit, then +
  $('#waddparts [data-wadd="word"]').click();
  $('#waddparts [data-wadd="word"]').click();  // touched again: left
  assert.match($("#waddsel").textContent, /\+ Ajouter/);
  $("#waddsel").click();
  change($("#wscrsec"), "30");
  $("#wscrhours").checked = true;
  change($("#wscrhours"));
  await wait(50);
  const screen = last().weather.screens[1];
  assert.deepEqual(Object.keys(screen.parts), ["saint", "countdown"]);
  assert.deepEqual([screen.seconds, screen.from, screen.to], [30, 6, 10]);
  assert.equal(screen.parts.countdown.date, "weekend");
  assert.notEqual($("#wcdrow").style.display, "none");  // the countdown picked: its title and date
  $("#wcdweekend").checked = false;
  change($("#wcddate"), "2026-12-31");
  await wait(50);
  assert.equal(last().weather.screens[1].parts.countdown.date, "2026-12-31");
  // The arrows move the part picked one LED.
  $('#wscrparts [data-wpick="saint"]').click();
  $('#wedit [data-wmove="0,-1"]').click();
  await wait(50);
  assert.equal(last().weather.screens[1].parts.saint.dy, -1);
  // A copy of one already made, to change.
  $('#wpagenums [data-wnum="plus"]').click();
  assert.match($('#wcopygrid [data-wcopy="0"]').textContent, /1 · Maison/);
  $('#wcopygrid [data-wcopy="1"]').click();
  await wait(50);
  assert.deepEqual(last().weather.screens[2], last().weather.screens[1]);
  assert.equal(last().page, 2);
  $('#wscrdel').click();
  $('#wscrdel').click();
  await wait(50);
  // An empty screen; ▶ shows them in turn.
  $('#wpagenums [data-wnum="plus"]').click();
  $('#wpresets [data-wpreset="empty"]').click();
  await wait(50);
  assert.deepEqual(last().weather.screens[2].parts, {});
  $('#wpagenums [data-wnum="play"]').click();
  await wait(50);
  assert.equal(last().page, null);
});

test("Météo: today's saints and world days ticked (2 at most), the agenda read listed, appointments typed in", async () => {
  const { $, calls } = await studio({
    "idotmatrix/studio/routines": { routines: [], status: {} },
    "idotmatrix/studio/weather_sources": WEATHER_SOURCES,
    "idotmatrix/studio/weather_preview": { ...PREVIEW, boxes: { clock: [6, 0, 58, 14], agenda: [0, 16, 63, 40] },
      today: { date: "2026-11-03", saints: ["Hubert", "Sylvie"], world_days: ["A", "B", "C"], agenda: ["09:00 Dentiste"], calendars: 1 } },
  });
  $('nav button[data-tab="weather"]').click();
  await wait(50);
  const last = () => calls.findLast((c) => c.type === "idotmatrix/studio/weather_preview").weather;
  assert.match($("#wtoday").textContent, /09:00 Dentiste/);
  const days = () => [...document.body.querySelector("idotmatrix-studio").shadowRoot.querySelectorAll('[data-today="world_days"]')];
  assert.deepEqual(days().map((b) => b.checked), [true, true, false]);
  assert.ok(days()[2].disabled);  // two already: the third waits
  days()[0].checked = false;
  change(days()[0]);
  await wait(50);
  assert.deepEqual(last().pick, { date: "2026-11-03", saints: ["Hubert", "Sylvie"], world_days: ["B"] });
  // The agenda picked: its options, an appointment typed in.
  $('#wzones [data-wzone=""]').click();
  $("#waddevent").click();
  await wait();
  $("#wevents [data-etitle]").value = "Piscine";
  $("#wevents [data-etime]").value = "17:30";
  change($("#wevents [data-etime]"));
  await wait(50);
  assert.equal(last().events[0].title, "Piscine");
  assert.equal(last().events[0].time, "17:30");
});

test("Météo: while the view is on the display, a change is saved on its own and goes there live", async () => {
  const weather = { id: "w1", name: "Météo", files: [], interval: 900, order: "sequence", mode: "weather", hours: null,
    weather: { profiles: [{ source: "home" }] } };
  const { $, calls } = await studio({
    "idotmatrix/studio/routines": { routines: [weather], status: { active: "w1", mode: "weather", state: "showing" } },
    "idotmatrix/studio/status": { display: "Cadre", displays: [], connected: true, screen_on: true,
      routine: { active: "w1", mode: "weather", state: "showing" }, schedule_status: {} },
    "idotmatrix/studio/weather_sources": WEATHER_SOURCES,
    "idotmatrix/studio/weather_preview": PREVIEW,
  });
  $('nav button[data-tab="weather"]').click();
  await wait(1000);
  assert.ok(!calls.some((c) => c.type === "idotmatrix/studio/routine_save"));  // opening saves nothing
  $('input[name=wstyle][value="flip"]').checked = true;
  change($('input[name=wstyle][value="flip"]'));
  await wait(1000);
  const saved = calls.filter((c) => c.type === "idotmatrix/studio/routine_save");
  assert.equal(saved.length, 1);
  assert.equal(saved[0].routine.weather.clock_style, "flip");
  assert.ok(!calls.some((c) => c.type === "idotmatrix/studio/routine_start"));  // no restart
});
