// Small progressive enhancements. Every page works without this file.

function showPreviews(input) {
  const form = input.closest("form");
  if (!input.dataset.previews) {
    // A plain file (the orders CSV): just show its name.
    const label = form.querySelector("[data-count]");
    if (label && input.files.length) label.textContent = input.files[0].name;
    return;
  }
  const box = document.getElementById(input.dataset.previews);
  const max = Number(input.dataset.max || 3);
  const files = Array.from(input.files).slice(0, max);
  box.innerHTML = "";
  files.forEach((file) => {
    const img = document.createElement("img");
    img.alt = file.name;
    img.src = URL.createObjectURL(file);
    box.appendChild(img);
  });
  const label = form.querySelector("[data-count]");
  if (label) {
    label.textContent = files.length
      ? `${files.length} photo${files.length > 1 ? "s" : ""} ready`
      : "Take or choose a photo";
  }
  if (input.files.length > max) alert(`Only the first ${max} photos will be used.`);
}

document.addEventListener("change", (e) => {
  const input = e.target.closest("input[type=file]");
  if (input) showPreviews(input);
});

// Drag photos onto the drop zone (desktop).
["dragenter", "dragover"].forEach((type) =>
  document.addEventListener(type, (e) => {
    const zone = e.target.closest && e.target.closest("[data-drop]");
    if (!zone) return;
    e.preventDefault();
    zone.classList.add("over");
  })
);
["dragleave", "drop"].forEach((type) =>
  document.addEventListener(type, (e) => {
    const zone = e.target.closest && e.target.closest("[data-drop]");
    if (!zone) return;
    e.preventDefault();
    zone.classList.remove("over");
    if (type === "drop" && e.dataTransfer.files.length) {
      const input = zone.querySelector("input[type=file]");
      input.files = e.dataTransfer.files;
      showPreviews(input);
    }
  })
);

document.addEventListener("submit", (e) => {
  const form = e.target;
  if (!form.matches("[data-busy]")) return;
  form.classList.add("working");
  // Disable after the submit has captured the clicked button's value.
  setTimeout(() => form.querySelectorAll("button").forEach((b) => (b.disabled = true)), 0);
});

// Going back to a page (Safari keeps it in memory): undo the "working" state of its forms.
window.addEventListener("pageshow", (e) => {
  if (!e.persisted) return;
  document.querySelectorAll("form.working").forEach((form) => {
    form.classList.remove("working");
    form.querySelectorAll("button").forEach((b) => (b.disabled = false));
  });
});

function copied(button) {
  button.textContent = "Link copied";
  setTimeout(() => (button.textContent = "Copy link"), 2000);
}

document.addEventListener("click", (e) => {
  // "Show" / "Hide" on the access code field.
  const reveal = e.target.closest("button[data-reveal]");
  if (reveal) {
    const input = document.getElementById(reveal.dataset.reveal);
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    reveal.textContent = show ? "Hide" : "Show";
    reveal.setAttribute("aria-pressed", String(show));
    input.focus();
  }

  // "Copy link" on a record: for sending to a teammate who can sign in. The clipboard needs
  // HTTPS; on plain HTTP (a phone on the local network) the link is shown to copy by hand.
  const copy = e.target.closest("button[data-copy-link]");
  if (copy) {
    const url = new URL(copy.dataset.copyLink || location.href, location.href).href;
    const byHand = () => window.prompt("Copy this link:", url);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(() => copied(copy), byHand);
    } else {
      byHand();
    }
  }
});

// Filter tabs that don't fit (phones) scroll sideways: fade the edge that has more tabs past it,
// and bring the selected tab into view.
function markTabs(tabs) {
  const rest = tabs.scrollWidth - tabs.clientWidth - tabs.scrollLeft;
  tabs.classList.toggle("fade-end", rest > 2);
  tabs.classList.toggle("fade-start", tabs.scrollLeft > 2);
}

function showSelectedTab(tabs) {
  const on = tabs.querySelector(".on");
  if (on) {
    const over = on.getBoundingClientRect().right - tabs.getBoundingClientRect().right;
    if (over > 0) tabs.scrollLeft += over + 40;
  }
  markTabs(tabs);
}

document.querySelectorAll(".tabs").forEach((tabs) => {
  showSelectedTab(tabs);
  tabs.addEventListener("scroll", () => markTabs(tabs), { passive: true });
});
// The web font can arrive after this runs and make the tabs wider: measure again then.
if (document.fonts) document.fonts.ready.then(() => document.querySelectorAll(".tabs").forEach(showSelectedTab));
window.addEventListener("resize", () => document.querySelectorAll(".tabs").forEach(markTabs));
