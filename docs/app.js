/* Raiders Daily front-end — vanilla JS, no dependencies */
(function () {
  "use strict";

  var data = null;
  var content = document.getElementById("content");

  // ---------- helpers ----------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function timeAgo(isoStr) {
    if (!isoStr) return "";
    var then = new Date(isoStr).getTime();
    if (isNaN(then)) return "";
    var mins = Math.round((Date.now() - then) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return mins + " min ago";
    var hrs = Math.round(mins / 60);
    if (hrs < 24) return hrs + (hrs === 1 ? " hour ago" : " hours ago");
    var days = Math.round(hrs / 24);
    if (days < 7) return days + (days === 1 ? " day ago" : " days ago");
    return new Date(isoStr).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  function gameDate(isoStr, withTime) {
    var d = new Date(isoStr);
    if (isNaN(d.getTime())) return "";
    var opts = { weekday: "short", month: "short", day: "numeric" };
    var s = d.toLocaleDateString(undefined, opts);
    if (withTime && (d.getHours() !== 0 || d.getMinutes() !== 0)) {
      s += " · " + d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    }
    return s;
  }

  // ---------- card renderers ----------
  function newsCard(n) {
    return '<a class="card" href="' + esc(n.url) + '" target="_blank" rel="noopener">' +
      '<div class="meta"><span class="source">' + esc(n.source) + "</span><span>" + timeAgo(n.published) + "</span></div>" +
      "<h3>" + esc(n.title) + "</h3>" +
      (n.summary ? '<p class="summary">' + esc(n.summary) + "</p>" : "") +
      "</a>";
  }

  function podcastCard(p) {
    return '<div class="card">' +
      '<div class="meta"><span class="source">' + esc(p.show) + "</span><span>" + timeAgo(p.published) + "</span>" +
      (p.duration ? "<span>" + esc(p.duration) + "</span>" : "") + "</div>" +
      "<h3>" + esc(p.title) + "</h3>" +
      (p.summary ? '<p class="summary">' + esc(p.summary) + "</p>" : "") +
      '<audio controls preload="none" src="' + esc(p.audio_url) + '"></audio>' +
      (p.url ? '<p class="pod-links"><a href="' + esc(p.url) + '" target="_blank" rel="noopener">Episode page ↗</a></p>' : "") +
      "</div>";
  }

  function videoCard(v) {
    return '<a class="card video-card" href="' + esc(v.url) + '" target="_blank" rel="noopener">' +
      '<img src="' + esc(v.thumbnail) + '" alt="" loading="lazy">' +
      '<div class="video-body"><div class="meta"><span class="source">' + esc(v.channel) + "</span><span>" + timeAgo(v.published) + "</span></div>" +
      "<h3>" + esc(v.title) + "</h3></div></a>";
  }

  function redditCard(r) {
    return '<a class="card" href="' + esc(r.url) + '" target="_blank" rel="noopener">' +
      '<div class="meta"><span class="source">r/raiders</span><span>' + esc(r.author) + "</span><span>" + timeAgo(r.published) + "</span></div>" +
      "<h3>" + esc(r.title) + "</h3></a>";
  }

  function gameBanner(team) {
    var g = team && team.next_game;
    if (!g) return "";
    var live = g.state === "in";
    var score = "";
    if (live && g.competitors && g.competitors.length === 2) {
      score = g.competitors.map(function (c) { return esc(c.team) + " " + esc(c.score || 0); }).join(" — ");
    }
    return '<div class="game-banner">' +
      '<div class="label">' + (live ? "🏈 Game in progress" : "Next game") + "</div>" +
      '<div class="matchup">' + esc(g.name || g.short_name) + "</div>" +
      '<div class="when">' + (live ? score + " · " + esc(g.detail || "") : gameDate(g.date, true)) + "</div>" +
      "</div>";
  }

  function scheduleRow(g) {
    var result;
    if (g.state === "post" && g.competitors && g.competitors.length === 2) {
      var lv = null, opp = null;
      g.competitors.forEach(function (c) { if (c.team === "LV") lv = c; else opp = c; });
      if (lv && opp) {
        var won = lv.winner === true;
        var cls = won ? "win" : (opp.winner === true ? "loss" : "");
        var letter = won ? "W" : (opp.winner === true ? "L" : "T");
        result = '<span class="' + cls + '">' + letter + " " + esc(lv.score) + "–" + esc(opp.score) + "</span>";
      } else {
        result = esc(g.detail || "Final");
      }
    } else {
      result = new Date(g.date).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    }
    return "<tr><td class='date'>" + gameDate(g.date) + "</td><td>" + esc(g.short_name || g.name) + "</td><td class='result'>" + result + "</td></tr>";
  }

  // ---------- tab renderers ----------
  function section(title, inner) {
    return '<h2 class="section-title">' + title + "</h2>" + inner;
  }
  function empty(what) {
    return '<p class="error-note">' + what + " is temporarily unavailable — check back later.</p>";
  }

  var tabs = {
    today: function () {
      var h = gameBanner(data.team);
      h += section("Top stories", data.news.length ? data.news.slice(0, 7).map(newsCard).join("") : empty("News"));
      if (data.podcasts.length) h += section("Latest podcast", podcastCard(data.podcasts[0]));
      if (data.videos.length) h += section("Latest videos", '<div class="video-grid">' + data.videos.slice(0, 3).map(videoCard).join("") + "</div>");
      if (data.reddit.length) h += section("Fans are talking about", data.reddit.slice(0, 3).map(redditCard).join(""));
      return h;
    },
    news: function () {
      return data.news.length ? data.news.map(newsCard).join("") : empty("News");
    },
    podcasts: function () {
      return data.podcasts.length ? data.podcasts.map(podcastCard).join("") : empty("Podcasts");
    },
    videos: function () {
      return data.videos.length ? '<div class="video-grid">' + data.videos.map(videoCard).join("") + "</div>" : empty("Videos");
    },
    reddit: function () {
      return data.reddit.length ? data.reddit.map(redditCard).join("") : empty("The fan forum");
    },
    team: function () {
      var t = data.team || {};
      var h = '<div class="team-summary">' +
        (t.logo ? '<img src="' + esc(t.logo) + '" alt="Raiders logo">' : "") +
        '<div><div class="line">Las Vegas Raiders' + (t.record ? " · " + esc(t.record) : "") + "</div>" +
        '<div class="sub">' + esc(t.standing || "") + "</div></div></div>";
      h += gameBanner(t);
      if (t.schedule && t.schedule.length) {
        h += section((t.season ? esc(t.season) + " " : "") + "Schedule",
          '<table class="schedule">' + t.schedule.map(scheduleRow).join("") + "</table>");
      } else {
        h += empty("The schedule");
      }
      return h;
    },
  };

  function show(tabName) {
    document.querySelectorAll(".tab").forEach(function (b) {
      b.classList.toggle("active", b.dataset.tab === tabName);
    });
    content.innerHTML = tabs[tabName]();
    window.scrollTo(0, 0);
  }

  // ---------- wiring ----------
  document.getElementById("tabs").addEventListener("click", function (e) {
    var btn = e.target.closest(".tab");
    if (btn && data) show(btn.dataset.tab);
  });

  var fontBtn = document.getElementById("font-toggle");
  function applyFont() {
    document.documentElement.classList.toggle("large", localStorage.getItem("rd-large") === "1");
  }
  fontBtn.addEventListener("click", function () {
    localStorage.setItem("rd-large", localStorage.getItem("rd-large") === "1" ? "0" : "1");
    applyFont();
  });
  applyFont();

  fetch("data.json?v=" + Date.now())
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (d) {
      data = d;
      var stamp = document.getElementById("updated-stamp");
      stamp.textContent = "Updated " + timeAgo(d.updated_at);
      show("today");
    })
    .catch(function (err) {
      content.innerHTML = '<p class="error-note">Could not load today\'s content (' + esc(err.message) +
        "). Pull down to refresh or try again in a few minutes.</p>";
    });
})();
