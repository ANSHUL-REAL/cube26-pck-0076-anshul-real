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

document.addEventListener("click", (e) => {
  // Decision buttons fill in the hidden "decision" field of their form.
  const btn = e.target.closest("button[data-decision]");
  if (btn) btn.form.querySelector("input[name=decision]").value = btn.dataset.decision;

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

  // "Copy link" on a record: for sending to a teammate who can sign in.
  const copy = e.target.closest("button[data-copy-link]");
  if (copy && navigator.clipboard) {
    navigator.clipboard.writeText(location.href).then(() => {
      copy.textContent = "Link copied";
      setTimeout(() => (copy.textContent = "Copy link"), 2000);
    });
  }
});
