// Small progressive enhancements. Every page works without this file.

document.addEventListener("change", (e) => {
  const input = e.target.closest("input[type=file][data-previews]");
  if (!input) return;
  const form = input.closest("form");
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
  const submit = form.querySelector("button[type=submit]");
  if (submit) submit.disabled = files.length === 0;
  if (input.files.length > max) alert(`Only the first ${max} photos will be used.`);
});

document.addEventListener("submit", (e) => {
  const form = e.target;
  if (!form.matches("[data-busy]")) return;
  form.classList.add("working");
  form.querySelectorAll("button").forEach((b) => (b.disabled = true));
});

// Decision buttons fill in the hidden "decision" field of their form.
document.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-decision]");
  if (!btn) return;
  btn.form.querySelector("input[name=decision]").value = btn.dataset.decision;
});
