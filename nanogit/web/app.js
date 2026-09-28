/* nanoGit — the whole page, no framework, no build step.
   Every call into the app is a small JSON request; every reply is turned into
   plain sentences. Nothing here knows what a commit is. */

const $ = (id) => document.getElementById(id);

const state = {
  folder: "",
  survey: null,
  status: null,
  readiness: null,
  settings: {},
  health: null,
  browsePath: "",
  browseParent: "",
  busy: false,
};

/* ------------------------------------------------------------------- utils */
function api(path, body) {
  const options = body === undefined
    ? { method: "GET" }
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) };
  return fetch(path, options).then(async (response) => {
    let data = {};
    try { data = await response.json(); } catch (err) { data = { error: "The app sent back something unreadable." }; }
    return data;
  }).catch(() => ({ error: "nanoGit is not answering. Is the window it started in still open?" }));
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function toast(message, kind) {
  const box = el("div", "toast" + (kind ? " " + kind : ""), message);
  $("toasts").appendChild(box);
  setTimeout(() => box.remove(), kind === "bad" ? 9000 : 5000);
}

function showLog(container, lines, kind) {
  container.textContent = "";
  (lines || []).forEach((line) => {
    const row = el("div", "log-line" + (kind ? " " + kind : ""));
    row.appendChild(el("span", "bullet", kind === "bad" ? "✕" : "✓"));
    row.appendChild(el("span", "", line));
    container.appendChild(row);
  });
}

function shortPath(path) {
  if (!path) return "";
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.length > 4 ? "…/" + parts.slice(-4).join("/") : path;
}

function busy(on, label) {
  state.busy = on;
  document.querySelectorAll("button").forEach((b) => {
    if (b.dataset.always === "1") return;
    b.disabled = on || b.dataset.wasDisabled === "1";
  });
  if (on && label) toast(label);
}

/* ---------------------------------------------------------------- the steps */
const ORDER = ["find", "look", "keep", "online"];

function show(step) {
  ORDER.forEach((name) => {
    const panel = $("panel-" + name);
    if (panel) panel.hidden = name !== step;
  });
  const at = ORDER.indexOf(step);
  document.querySelectorAll(".step").forEach((button) => {
    const index = ORDER.indexOf(button.dataset.step);
    button.classList.toggle("active", index === at);
    button.classList.toggle("done", index < at);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

document.querySelectorAll(".step").forEach((button) => {
  button.addEventListener("click", () => {
    const target = button.dataset.step;
    if (target === "find") return show("find");
    if (!state.folder) return toast("Pick a folder first.", "bad");
    if (target === "look" && state.survey) return show("look");
    if (target === "keep" && state.status && state.status.tracked) return openKeep(state.folder);
    if (target === "online" && state.status && state.status.tracked) return openOnline(state.folder);
    toast("That step is not ready yet.", "bad");
  });
});

/* ----------------------------------------------------------------- start-up */
async function boot() {
  const health = await api("/api/health");
  state.health = health;
  state.settings = health.settings || {};

  const gitPill = $("gitPill");
  if (health.git && health.git.found) {
    gitPill.textContent = "git " + health.git.version;
    gitPill.className = "pill good";
  } else {
    gitPill.textContent = "git missing";
    gitPill.className = "pill bad";
    const banner = $("gitMissing");
    banner.className = "card danger";
    banner.hidden = false;
    const h = el("h3", "", "This computer does not have git on it");
    const p = el("p", "muted", health.git ? health.git.sentence : "git was not found.");
    banner.appendChild(h);
    banner.appendChild(p);
    $("startBtn").disabled = true;
  }

  const gh = health.gh || {};
  const ghPill = $("ghPill");
  if (gh.logged_in) {
    ghPill.textContent = "GitHub: " + gh.account;
    ghPill.className = "pill good";
  } else {
    ghPill.textContent = gh.installed ? "GitHub: not signed in" : "GitHub: tool missing";
    ghPill.className = "pill warn";
  }

  if (health.picker && !health.picker.ok) $("chooseBtn").title = health.picker.why;

  $("setName").value = state.settings.author_name || "";
  $("setEmail").value = state.settings.author_email || "";
  $("dataDirLine").textContent = "nanoGit keeps its own notes in " + (state.settings.data_dir || "your home folder") + ".";
  $("repoPrivate").checked = state.settings.publish_private !== false;

  loadRecent();
}

async function loadRecent() {
  const data = await api("/api/recent");
  const list = $("recentList");
  list.textContent = "";
  const folders = data.folders || [];
  $("recentCard").hidden = folders.length === 0;
  folders.forEach((item) => {
    const button = el("button", "item");
    button.appendChild(el("span", "icon", "🕘"));
    const body = el("div", "body");
    body.appendChild(el("div", "title", item.note || shortPath(item.path)));
    body.appendChild(el("div", "sub", item.path));
    button.appendChild(body);
    button.addEventListener("click", () => openFolder(item.path));
    list.appendChild(button);
  });
}

/* -------------------------------------------------- dragging a real folder */
const drop = $("drop");
["dragenter", "dragover"].forEach((name) =>
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.add("over");
  })
);
["dragleave", "drop"].forEach((name) =>
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.remove("over");
  })
);

drop.addEventListener("drop", async (event) => {
  const items = event.dataTransfer && event.dataTransfer.items;
  let name = "";
  let sawFile = false;
  if (items && items.length) {
    for (const item of items) {
      const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
      if (entry && entry.isDirectory) { name = entry.name; break; }
      if (entry) sawFile = true;
    }
  }
  if (!name && event.dataTransfer.files && event.dataTransfer.files.length) {
    const first = event.dataTransfer.files[0];
    if (first.type || first.name.includes(".")) sawFile = true;
    else name = first.name;
  }
  if (!name) {
    toast(sawFile
      ? "That is a file. Drag the folder that contains it instead."
      : "nanoGit needs a folder. Try dragging one from your desktop or file manager.", "bad");
    return;
  }
  findByDrag(name);
});

async function findByDrag(name) {
  busy(true, "Looking for a folder called “" + name + "”…");
  const data = await api("/api/locate", { name });
  busy(false);
  const matches = data.matches || [];
  if (matches.length === 1) {
    toast("Found it: " + matches[0], "good");
    return openFolder(matches[0]);
  }
  if (matches.length > 1) {
    const list = $("recentList");
    $("recentCard").hidden = false;
    list.textContent = "";
    list.appendChild(el("div", "label", "More than one folder is called “" + name + "”. Which one?"));
    matches.forEach((path) => {
      const button = el("button", "item");
      button.appendChild(el("span", "icon", "📁"));
      const body = el("div", "body");
      body.appendChild(el("div", "title", path.split(/[\\/]/).pop()));
      body.appendChild(el("div", "sub", path));
      button.appendChild(body);
      button.addEventListener("click", () => openFolder(path));
      list.appendChild(button);
    });
    show("find");
    return;
  }
  toast("Your browser will not say where a dragged folder lives, and nanoGit could not find "
      + "“" + name + "” by name. Pick it from the list instead.", "bad");
  openBrowser("", name);
}

/* ---------------------------------------------------- finding the folder */
$("chooseBtn").addEventListener("click", async () => {
  busy(true, "Opening your system's folder window…");
  const picked = await api("/api/pick-folder", { from: state.folder || "" });
  busy(false);
  if (picked.ok && picked.path) return openFolder(picked.path);
  if (picked.ok && picked.cancelled) return;
  if (picked.why) toast(picked.why);
  openBrowser(state.browsePath || "");
});

$("typeBtn").addEventListener("click", () => {
  $("typeCard").hidden = !$("typeCard").hidden;
  if (!$("typeCard").hidden) $("pathInput").focus();
});
$("pathBrowse").addEventListener("click", () => openBrowser(state.browsePath || ""));
$("pathGo").addEventListener("click", () => {
  const value = $("pathInput").value.trim();
  if (!value) return toast("Type the address of a folder first.", "bad");
  openFolder(value);
});
$("pathInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter") $("pathGo").click();
});

async function openFolder(path) {
  busy(true, "Looking inside…");
  const facts = await api("/api/survey", { path });
  busy(false);
  if (!facts.ok) return toast(facts.error || "Could not read that folder.", "bad");
  state.folder = facts.path;
  state.survey = facts;
  state.status = facts.status || {};
  $("pathInput").value = facts.path;
  renderLook(facts);
  show("look");
}

function renderLook(facts) {
  $("lookTitle").textContent = facts.title || facts.name;
  $("lookPath").textContent = facts.path;
  $("nameInput").value = facts.title || facts.name;
  $("descInput").value = facts.description || "";

  const factsBox = $("facts");
  factsBox.textContent = "";
  const add = (key, value, sub) => {
    const box = el("div", "fact");
    box.appendChild(el("div", "k", key));
    box.appendChild(el("div", "v", value));
    if (sub) box.appendChild(el("div", "s", sub));
    factsBox.appendChild(box);
  };
  add("Files", facts.file_count.toLocaleString(), facts.truncated ? "more than shown" : "counted");
  add("Size", facts.total_size_text, facts.biggest && facts.biggest.length ? "largest: " + facts.biggest[0].size_text : "");
  add("Looks like", facts.kind.replace(/^an? /, ""), facts.because);
  add("Already tracked", facts.is_repo ? "yes" : "no", facts.is_repo ? "nanoGit found .git inside" : "nanoGit will start one");

  const chips = $("breakdown");
  chips.textContent = "";
  (facts.breakdown || []).forEach((part) => {
    const chip = el("span", "chip");
    chip.appendChild(el("b", "", String(part.count)));
    chip.appendChild(document.createTextNode(" " + part.what));
    chips.appendChild(chip);
  });

  const secretsCard = $("secretsCard");
  const secretsList = $("secretsList");
  secretsList.textContent = "";
  const secrets = facts.secrets || [];
  secretsCard.hidden = secrets.length === 0;
  if (secrets.length) {
    secrets.forEach((item) => {
      const row = el("div", "item");
      row.appendChild(el("span", "icon", "🔒"));
      const body = el("div", "body");
      body.appendChild(el("div", "title", item.path));
      body.appendChild(el("div", "sub", item.what + " — " + item.why));
      row.appendChild(body);
      secretsList.appendChild(row);
    });
  }

  const bigCard = $("bigCard");
  const bigList = $("bigList");
  bigList.textContent = "";
  const big = facts.big_files || [];
  bigCard.hidden = big.length === 0;
  if (big.length) {
    big.forEach((item) => {
      const row = el("div", "item");
      row.appendChild(el("span", "icon", item.blocking ? "🚫" : "⚠︎"));
      const body = el("div", "body");
      body.appendChild(el("div", "title", item.path));
      body.appendChild(el("div", "sub", item.size_text + (item.blocking ? " — too large for GitHub" : " — large, will be left out")));
      row.appendChild(body);
      bigList.appendChild(row);
    });
  }

  const tracked = facts.is_repo;
  $("alreadyCard").hidden = !tracked;
  if (tracked) {
    $("alreadyText").textContent = facts.path + " already has a history. nanoGit will not start a new one — "
      + "it will add anything missing (a README, a .gitignore) and save a fresh checkpoint.";
    $("goToKeep").onclick = () => openKeep(facts.path);
  }
  $("startBtn").textContent = tracked ? "Save a fresh checkpoint" : "Keep this folder safe";

  if (facts.inside_other_repo) {
    $("startExplain").textContent = "Careful: this folder sits inside " + facts.inside_other_repo
      + ", which is already tracked. nanoGit will refuse, because one folder inside another makes both confusing.";
  } else if (facts.secrets && facts.secrets.length) {
    $("startExplain").textContent = "One press writes the README, adds " + facts.secrets.length
      + " private-looking file" + (facts.secrets.length === 1 ? "" : "s") + " to the leave-out list, starts the "
      + "history and saves the first checkpoint. Nothing is deleted and nothing is uploaded.";
  } else {
    $("startExplain").textContent = "One press writes the README, starts the history and saves the first "
      + "checkpoint. Nothing is deleted and nothing is uploaded.";
  }

  $("startLogCard").hidden = true;
}

$("openFolder").addEventListener("click", () => reveal(state.folder));
$("openFolder2").addEventListener("click", () => reveal(state.folder));
$("pickAnother").addEventListener("click", () => show("find"));

async function reveal(path) {
  if (!path) return;
  const result = await api("/api/reveal", { path });
  if (!result.ok) toast(result.error || "Could not open that folder.", "bad");
}

/* ---------------------------------------------------- keeping it safe */
$("startBtn").addEventListener("click", async () => {
  if (!state.folder) return;
  busy(true, "Working…");
  const result = await api("/api/start", {
    path: state.folder,
    name: $("nameInput").value.trim(),
    description: $("descInput").value.trim(),
    author_name: $("rememberAuthor").checked ? state.settings.author_name || "" : "",
    author_email: $("rememberAuthor").checked ? state.settings.author_email || "" : "",
    remember_author: $("rememberAuthor").checked,
  });
  busy(false);
  const card = $("startLogCard");
  card.hidden = false;
  if (result.ok) {
    showLog($("startLog"), result.steps || [], "");
    state.status = result.status || state.status;
    if (result.survey) state.survey = result.survey;
    toast("Done. This folder is being looked after.", "good");
  } else {
    showLog($("startLog"), [result.error || "That did not work."], "bad");
    toast(result.error || "That did not work.", "bad");
  }
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });
});

$("afterStart").addEventListener("click", () => openKeep(state.folder));

/* ------------------------------------------------------------ checkpoints */
async function openKeep(path) {
  busy(true, "Reading the history…");
  const status = await api("/api/status?path=" + encodeURIComponent(path));
  const history = await api("/api/history?path=" + encodeURIComponent(path));
  busy(false);
  if (!status.ok) return toast(status.error || "Could not read that folder.", "bad");
  state.folder = status.path;
  state.status = status;
  state.history = history.entries || [];
  renderKeep();
  show("keep");
}

function renderKeep() {
  const status = state.status;
  $("keepTitle").textContent = status.name;
  $("keepPath").textContent = status.path;

  const factsBox = $("keepFacts");
  factsBox.textContent = "";
  const add = (key, value, sub) => {
    const box = el("div", "fact");
    box.appendChild(el("div", "k", key));
    box.appendChild(el("div", "v", value));
    if (sub) box.appendChild(el("div", "s", sub));
    factsBox.appendChild(box);
  };
  add("Checkpoints", String(status.checkpoints || 0), status.first_when ? "first one " + status.first_when.slice(0, 10) : "");
  add("Unsaved changes", String((status.changes || []).length), (status.changes || []).length ? "worth a checkpoint" : "all saved");
  add("Online", status.remote ? "yes" : "not yet", status.remote ? shortPath(status.remote) : "press the button on the right");
  add("Signed as", status.identity && status.identity.name ? status.identity.name : "not set", (status.identity || {}).email || "");

  $("changeSummary").textContent = status.change_summary || "";
  const list = $("changeList");
  list.textContent = "";
  (status.changes || []).slice(0, 12).forEach((change) => {
    const row = el("div", "item");
    const icon = change.kind === "new" ? "➕" : change.kind === "gone" ? "➖" : "✎";
    row.appendChild(el("span", "icon", icon));
    const body = el("div", "body");
    body.appendChild(el("div", "title", change.path));
    body.appendChild(el("div", "sub", change.kind));
    row.appendChild(body);
    list.appendChild(row);
  });
  if ((status.changes || []).length > 12) {
    list.appendChild(el("div", "faint", "…and " + (status.changes.length - 12) + " more"));
  }
  $("checkpointBtn").disabled = (status.changes || []).length === 0;
  loadDiffPreview();

  $("onlineTease").textContent = status.remote
    ? "This folder already has a home online. Sending the new checkpoints up is one press."
    : "One press creates a repository under your GitHub account and sends the folder up. Private by default.";

  renderHistory();
}

function renderHistory() {
  const wrap = $("historyWrap");
  wrap.textContent = "";
  const entries = state.history || [];
  if (!entries.length) {
    wrap.appendChild(el("p", "muted", "No checkpoints yet. Press “Save a checkpoint” and one will appear here."));
    return;
  }
  const table = el("table", "history");
  const head = el("tr");
  ["When", "What was saved", "Version", ""].forEach((text) => head.appendChild(el("th", "", text)));
  table.appendChild(head);

  entries.forEach((entry) => {
    const row = el("tr", entry.was_first ? "first" : "");
    row.appendChild(el("td", "", entry.when_text || entry.when));
    row.appendChild(el("td", "", (entry.was_first ? "★ " : "") + entry.message));
    row.appendChild(el("td", "sha", entry.short));
    const action = el("td");
    if (entry.was_first) {
      action.appendChild(el("span", "faint", "the first"));
    } else {
      const button = el("button", "btn tiny", "Go back");
      button.addEventListener("click", () => goBack(entry));
      action.appendChild(button);
    }
    row.appendChild(action);
    table.appendChild(row);
  });
  wrap.appendChild(table);
}

$("checkpointBtn").addEventListener("click", async () => {
  busy(true, "Saving…");
  const result = await api("/api/checkpoint", { path: state.folder, message: $("messageInput").value.trim() });
  busy(false);
  if (!result.ok) {
    showLog($("changeList"), [result.error || "Could not save."], "bad");
    return toast(result.error || "Could not save.", "bad");
  }
  $("messageInput").value = "";
  toast(result.steps[0] || "Saved.", result.ok ? "good" : "bad");
  await openKeep(state.folder);
});

async function goBack(entry) {
  const sure = confirm(
    "Put the files back to how they were " + (entry.when_text || entry.when) + "?\n\n" +
    "Your current work is saved first, so nothing is lost. Files you added after that checkpoint " +
    "are kept where they are."
  );
  if (!sure) return;
  busy(true, "Going back…");
  const result = await api("/api/go-back", { path: state.folder, sha: entry.sha });
  busy(false);
  if (!result.ok) return toast(result.error || "Could not go back.", "bad");
  result.steps.forEach((line) => toast(line, "good"));
  await openKeep(state.folder);
}

$("toOnline").addEventListener("click", () => openOnline(state.folder));
$("goToKeep").addEventListener("click", () => openKeep(state.folder));

/* --------------------------------------------------------------- online */
async function openOnline(path) {
  busy(true, "Checking…");
  const ready = await api("/api/readiness?path=" + encodeURIComponent(path));
  busy(false);
  if (!ready.ok) return toast(ready.error || "Could not check that folder.", "bad");
  state.readiness = ready;
  renderReady();
  show("online");
}

function renderReady() {
  const ready = state.readiness;
  $("readyText").textContent = ready.explain || "";
  const extra = $("readyExtra");
  extra.textContent = "";

  if (ready.secrets && ready.secrets.length) {
    const card = el("div", "card danger tight");
    card.appendChild(el("h3", "", "⚠︎ " + ready.secrets.length + " file"
      + (ready.secrets.length === 1 ? "" : "s") + " in this folder look private"));
    const list = el("div", "list");
    ready.secrets.slice(0, 8).forEach((item) => {
      const row = el("div", "item");
      row.appendChild(el("span", "icon", "🔒"));
      const body = el("div", "body");
      body.appendChild(el("div", "title", item.path));
      body.appendChild(el("div", "sub", item.what));
      row.appendChild(body);
      list.appendChild(row);
    });
    card.appendChild(list);
    const row = el("div", "row");
    row.style.marginTop = "12px";
    const leave = el("button", "btn good", "Leave them out and continue");
    leave.addEventListener("click", () => leaveOut(ready.secrets.map((item) => item.path)));
    const anyway = el("button", "btn danger", "Upload them anyway");
    anyway.addEventListener("click", () => {
      state.allowSecrets = true;
      toast("Understood — pressing the button now will include them.", "bad");
    });
    row.appendChild(leave);
    row.appendChild(anyway);
    card.appendChild(row);
    extra.appendChild(card);
  }

  if (ready.blocking_files && ready.blocking_files.length) {
    const card = el("div", "card danger tight");
    card.appendChild(el("h3", "", "🚫 " + ready.blocking_files[0].path + " is "
      + ready.blocking_files[0].size_text));
    card.appendChild(el("p", "muted", "GitHub will not accept a file that big. Add it to the leave-out list, "
      + "or move it out of the folder, and come back."));
    const row = el("div", "row");
    const fix = el("button", "btn", "Leave that file out");
    fix.addEventListener("click", () => leaveOut(ready.blocking_files.map((item) => item.path)));
    row.appendChild(fix);
    card.appendChild(row);
    extra.appendChild(card);
  }

  $("publishCard").hidden = !ready.tracked;
  if (ready.tracked) {
    $("repoName").value = ready.name || "";
    $("repoDesc").value = ready.description || "";
    $("repoPrivate").checked = ready.remote ? $("repoPrivate").checked : state.settings.publish_private !== false;
    $("publishBtn").textContent = ready.remote ? "Send the new checkpoints up" : "Create it and send everything up";
  }
  $("publishLogCard").hidden = true;
}

async function leaveOut(patterns) {
  const result = await api("/api/leave-out", { path: state.folder, patterns });
  if (!result.ok) return toast(result.error || "Could not change the leave-out list.", "bad");
  toast(result.sentence, "good");
  await openOnline(state.folder);
}

$("publishBtn").addEventListener("click", async () => {
  busy(true, "Talking to GitHub…");
  const result = await api("/api/publish", {
    path: state.folder,
    name: $("repoName").value.trim(),
    description: $("repoDesc").value.trim(),
    private: $("repoPrivate").checked,
    allow_secrets: !!state.allowSecrets,
  });
  busy(false);
  const card = $("publishLogCard");
  card.hidden = false;
  const link = $("publishLink");
  link.textContent = "";
  if (result.ok) {
    showLog($("publishLog"), result.steps || [], "");
    if (result.url) {
      const anchor = el("a", "", result.url);
      anchor.href = result.url;
      anchor.target = "_blank";
      anchor.rel = "noreferrer";
      link.appendChild(anchor);
    }
    toast("It is online.", "good");
  } else {
    showLog($("publishLog"), [result.error || "That did not work."], "bad");
    if (result.manual) {
      const pre = el("pre", "code", result.manual);
      link.appendChild(el("p", "muted", "If you would rather do it by hand, these are the exact lines:"));
      link.appendChild(pre);
    }
    if (result.secrets) state.allowSecrets = false;
  }
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });
});

$("manualBtn").addEventListener("click", () => {
  const name = $("repoName").value.trim() || "my-project";
  const private_ = $("repoPrivate").checked;
  const lines = [
    (private_ ? "# on github.com, create a *private* repository called " : "# on github.com, create a repository called ") + name,
    'cd "' + state.folder + '"',
    "git remote add origin https://github.com/<your-name>/" + name + ".git",
    "git branch -M main",
    "git push -u origin main",
  ];
  const link = $("publishLink");
  link.textContent = "";
  $("publishLogCard").hidden = false;
  link.appendChild(el("p", "muted", "These are the same steps, done by hand in a terminal:"));
  link.appendChild(el("pre", "code", lines.join("\n")));
});

/* ------------------------------------------------------ the folder picker */
function openBrowser(path, hint) {
  state.browsePath = path;
  $("browserBack").hidden = false;
  if (hint) toast("Looking for a folder called “" + hint + "”.");
  loadBrowse(path);
}

async function loadBrowse(path) {
  const data = await api("/api/browse?path=" + encodeURIComponent(path || ""));
  if (!data.ok) return toast(data.error || "Cannot read that folder.", "bad");
  state.browsePath = data.path;
  state.browseParent = data.parent;

  const crumbs = $("crumbs");
  crumbs.textContent = "";
  (data.places || []).forEach((place) => {
    const button = el("button", "btn tiny ghost", place);
    button.addEventListener("click", () => loadBrowse(place));
    crumbs.appendChild(button);
  });
  if (data.path) {
    crumbs.appendChild(el("span", "faint", "→ " + data.path));
    if (data.parent) {
      const up = el("button", "btn tiny", "↑ up one");
      up.addEventListener("click", () => loadBrowse(data.parent));
      crumbs.appendChild(up);
    }
  } else {
    crumbs.appendChild(el("span", "faint", "→ choose where to start"));
  }

  const browser = $("browser");
  browser.textContent = "";
  const folders = data.folders || [];
  if (!folders.length) {
    browser.appendChild(el("p", "muted", data.path
      ? "No folders inside this one. Press “Use this folder” if this is the one you meant."
      : "Pick a place above to start."));
  }
  folders.forEach((folder) => {
    const button = el("button", "item");
    button.appendChild(el("span", "icon", folder.mark === "tracked" ? "🕘" : "📁"));
    const body = el("div", "body");
    body.appendChild(el("div", "title", folder.name));
    body.appendChild(el("div", "sub", folder.mark === "tracked" ? "already tracked by nanoGit" : "double-click to go in"));
    button.appendChild(body);
    button.addEventListener("dblclick", () => loadBrowse(folder.path));
    button.addEventListener("click", () => {
      state.browsePath = folder.path;
      browser.querySelectorAll(".item").forEach((other) => (other.style.borderColor = ""));
      button.style.borderColor = "var(--accent)";
    });
    browser.appendChild(button);
  });
}

$("useFolder").addEventListener("click", () => {
  if (!state.browsePath) return toast("Go into a folder first.", "bad");
  $("browserBack").hidden = true;
  openFolder(state.browsePath);
});
$("browserClose").addEventListener("click", () => ($("browserBack").hidden = true));

/* ------------------------------------------------------------- settings */
$("settingsBtn").addEventListener("click", () => ($("settingsBack").hidden = false));
$("settingsClose").addEventListener("click", () => ($("settingsBack").hidden = true));
$("saveSettings").addEventListener("click", async () => {
  const result = await api("/api/settings", {
    author_name: $("setName").value.trim(),
    author_email: $("setEmail").value.trim(),
    remember_author: true,
  });
  state.settings = result.settings || state.settings;
  $("settingsBack").hidden = true;
  toast("Saved.", "good");
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  $("browserBack").hidden = true;
  $("settingsBack").hidden = true;
});

boot();

async function loadDiffPreview() {
  const wrap = $("diffList");
  if (!wrap || !state.folder) { if (wrap) wrap.textContent = ""; return; }
  try {
    const data = await api("/api/preview?path=" + encodeURIComponent(state.folder));
    wrap.textContent = "";
    if (data.why) { wrap.appendChild(el("div", "faint", data.why)); return; }
    (data.files || []).forEach((file) => {
      if (!file.lines || !file.lines.length) return;
      const head = el("div", "item");
      head.appendChild(el("div", "body", file.path));
      wrap.appendChild(head);
      file.lines.forEach((line) => wrap.appendChild(el("div", "faint", "    " + line)));
    });
  } catch (err) { wrap.textContent = ""; }
}
