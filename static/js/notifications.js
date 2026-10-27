// Header notification bell: open/close, live unread count, mark all as read.
(function () {
  "use strict";

  var POLL_MS = 60000;

  function csrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (match) return decodeURIComponent(match[1]);
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  function init() {
    var root = document.querySelector(".notif");
    if (!root) return;
    var bell = root.querySelector(".notif__bell");
    var panel = root.querySelector(".notif__panel");
    var count = root.querySelector(".notif__count");
    var list = root.querySelector(".notif__list");
    var readAll = root.querySelector(".notif__readall");

    function setCount(n) {
      count.hidden = n === 0;
      count.textContent = n > 99 ? "99+" : String(n);
      bell.setAttribute("aria-label", n ? "Notifications, " + n + " unread" : "Notifications");
    }

    function render(items) {
      list.replaceChildren();
      if (!items.length) {
        list.appendChild(el("li", "notif__empty", "You're all caught up."));
        return;
      }
      items.forEach(function (n) {
        var li = el("li");
        var a = el("a", "notif__item notif__item--" + n.kind + (n.is_read ? "" : " is-unread"));
        a.href = n.open_url;
        a.appendChild(el("span", "notif__icon"));
        var text = el("span", "notif__text");
        text.appendChild(el("span", "notif__title", n.title));
        if (n.body) text.appendChild(el("span", "notif__body", n.body));
        text.appendChild(el("span", "notif__when", n.when));
        a.appendChild(text);
        li.appendChild(a);
        list.appendChild(li);
      });
    }

    function open(show) {
      panel.hidden = !show;
      bell.setAttribute("aria-expanded", String(show));
      if (show) {
        var first = panel.querySelector("a, button");
        if (first) first.focus();
      }
    }

    bell.addEventListener("click", function (e) {
      e.stopPropagation();
      open(panel.hidden);
    });
    document.addEventListener("click", function (e) {
      if (!panel.hidden && !root.contains(e.target)) open(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !panel.hidden) {
        open(false);
        bell.focus();
      }
    });

    readAll.addEventListener("click", function () {
      fetch(root.dataset.readAll, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "fetch" },
        credentials: "same-origin",
      }).then(function (r) {
        if (!r.ok) return;
        setCount(0);
        list.querySelectorAll(".is-unread").forEach(function (a) { a.classList.remove("is-unread"); });
      });
    });

    function poll() {
      if (document.hidden) return;
      fetch(root.dataset.feed, { credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (!data) return;
          setCount(data.unread);
          if (panel.hidden) render(data.items);
        })
        .catch(function () {});
    }
    setInterval(poll, POLL_MS);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
