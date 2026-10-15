/*
 * Pawsitivity chat widget. Embed on any page with one line:
 *
 *   <script src="https://chat.coexistwithpawsitivity.com/widget.js" data-color="#2f6f4f" defer></script>
 *
 * Optional attributes: data-color, data-title, data-position="left|right", data-api (override API origin)
 * Runs inside a Shadow DOM so the website's CSS and the widget's CSS never clash.
 */
(function () {
  if (window.__pawsitivityChat) return;
  window.__pawsitivityChat = true;

  var script = document.currentScript;
  var api = (script && script.dataset.api) || (script ? new URL(script.src).origin : "");
  var color = (script && script.dataset.color) || "#2f6f4f";
  var title = (script && script.dataset.title) || "Pawsitivity Assistant";
  var side = (script && script.dataset.position) === "left" ? "left" : "right";
  var history = [];
  var busy = false;

  var host = document.createElement("div");
  host.id = "pawsitivity-chat";
  document.body.appendChild(host);
  var root = host.attachShadow({ mode: "open" });

  root.innerHTML =
    "<style>" +
    ":host{all:initial}" +
    "*{box-sizing:border-box;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}" +
    ".fab{position:fixed;bottom:20px;" + side + ":20px;width:58px;height:58px;border-radius:50%;border:0;cursor:pointer;" +
    "background:" + color + ";color:#fff;font-size:26px;box-shadow:0 6px 20px rgba(0,0,0,.2);z-index:2147483000}" +
    ".panel{position:fixed;bottom:90px;" + side + ":20px;width:min(380px,calc(100vw - 32px));height:min(560px,calc(100vh - 120px));" +
    "background:#fff;color:#1d1d1d;border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.25);display:none;flex-direction:column;" +
    "overflow:hidden;z-index:2147483000}" +
    ".panel.open{display:flex}" +
    ".head{background:" + color + ";color:#fff;padding:14px 16px;font-weight:600;display:flex;justify-content:space-between;align-items:center}" +
    ".head button{background:none;border:0;color:#fff;font-size:20px;cursor:pointer}" +
    ".log{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px;background:#f7f7f5}" +
    ".msg{max-width:85%;padding:10px 12px;border-radius:14px;line-height:1.45;font-size:14px;white-space:pre-wrap;word-wrap:break-word}" +
    ".bot{background:#fff;border:1px solid #e6e6e1;align-self:flex-start;border-bottom-left-radius:4px}" +
    ".me{background:" + color + ";color:#fff;align-self:flex-end;border-bottom-right-radius:4px}" +
    ".src{font-size:12px;margin-top:6px;color:#555}.src a{color:" + color + "}" +
    ".typing{opacity:.6;font-style:italic}" +
    "form{display:flex;gap:8px;padding:10px;border-top:1px solid #eee;background:#fff}" +
    "input{flex:1;border:1px solid #d6d6d0;border-radius:10px;padding:10px 12px;font-size:14px;outline-color:" + color + "}" +
    "form button{background:" + color + ";color:#fff;border:0;border-radius:10px;padding:0 14px;font-size:14px;cursor:pointer}" +
    "form button:disabled{opacity:.5;cursor:default}" +
    ".note{font-size:11px;color:#777;text-align:center;padding:0 10px 8px;background:#fff}" +
    "@media (prefers-color-scheme: dark){.panel{background:#1f1f1f;color:#eee}.log{background:#181818}" +
    ".bot{background:#262626;border-color:#333;color:#eee}form,.note{background:#1f1f1f}" +
    "input{background:#2a2a2a;color:#eee;border-color:#3a3a3a}.src{color:#aaa}}" +
    "</style>" +
    '<button class="fab" aria-label="Open chat" title="' + title + '">&#128062;</button>' +
    '<section class="panel" role="dialog" aria-label="' + title + '">' +
    '<div class="head"><span></span><button aria-label="Close chat">&times;</button></div>' +
    '<div class="log" aria-live="polite"></div>' +
    '<form><input type="text" maxlength="800" placeholder="Ask a question..." aria-label="Your question" />' +
    '<button type="submit">Send</button></form>' +
    '<div class="note">AI assistant. Answers can be wrong, please check important details.</div>' +
    "</section>";

  var fab = root.querySelector(".fab");
  var panel = root.querySelector(".panel");
  var log = root.querySelector(".log");
  var form = root.querySelector("form");
  var input = root.querySelector("input");
  var sendBtn = root.querySelector("form button");
  root.querySelector(".head span").textContent = title;

  function add(text, who, sources) {
    var el = document.createElement("div");
    el.className = "msg " + who;
    el.textContent = text; // textContent, never innerHTML: no HTML injection from answers
    if (sources && sources.length) {
      var s = document.createElement("div");
      s.className = "src";
      s.appendChild(document.createTextNode("Sources: "));
      sources.forEach(function (src, i) {
        if (i) s.appendChild(document.createTextNode(", "));
        if (src.url && /^https?:\/\//.test(src.url)) {
          var a = document.createElement("a");
          a.href = src.url; a.target = "_blank"; a.rel = "noopener";
          a.textContent = src.title || src.url;
          s.appendChild(a);
        } else {
          s.appendChild(document.createTextNode(src.title));
        }
      });
      el.appendChild(s);
    }
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  var greeted = false;
  function open() {
    panel.classList.add("open");
    fab.setAttribute("aria-label", "Close chat");
    input.focus();
    if (!greeted) {
      greeted = true;
      fetch(api + "/api/config").then(function (r) { return r.json(); })
        .then(function (c) { add(c.greeting, "bot"); })
        .catch(function () { add("Hi! Ask me anything about Coexist with Pawsitivity.", "bot"); });
    }
  }
  function close() { panel.classList.remove("open"); fab.setAttribute("aria-label", "Open chat"); }

  fab.addEventListener("click", function () { panel.classList.contains("open") ? close() : open(); });
  root.querySelector(".head button").addEventListener("click", close);
  panel.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text || busy) return;
    busy = true; sendBtn.disabled = true; input.value = "";
    add(text, "me");
    var typing = add("...", "bot typing");
    fetch(api + "/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history: history.slice(-6) })
    })
      .then(function (r) {
        if (r.status === 429) return { answer: "You are sending messages very fast. Please wait a moment.", sources: [] };
        if (!r.ok && r.status !== 503) throw new Error(r.status);
        return r.json();
      })
      .then(function (data) {
        typing.remove();
        add(data.answer, "bot", data.sources);
        if (data.status !== "error") {
          history.push({ role: "user", content: text }, { role: "assistant", content: data.answer });
        }
      })
      .catch(function () {
        typing.remove();
        add("Sorry, something went wrong. Please try again later.", "bot");
      })
      .finally(function () { busy = false; sendBtn.disabled = false; input.focus(); });
  });
})();
