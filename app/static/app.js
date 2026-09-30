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
  const label = button.dataset.label || (button.dataset.label = button.textContent);
  button.textContent = "Link copied";
  setTimeout(() => (button.textContent = label), 2000);
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

  if (e.target.closest("button[data-print]")) window.print();

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

// Printing a record: the folded evidence details go on paper too, then fold up again.
window.addEventListener("beforeprint", () => {
  document.querySelectorAll("details[data-print-open]:not([open])").forEach((d) => {
    d.open = true;
    d.dataset.printOpened = "1";
  });
  document.querySelectorAll("[data-print-time]").forEach((el) => (el.textContent = new Date().toLocaleString()));
});
window.addEventListener("afterprint", () => {
  document.querySelectorAll("details[data-print-opened]").forEach((d) => {
    d.open = false;
    delete d.dataset.printOpened;
  });
});

// Sending the photos (Evidence Contract 1.1, section 4). Shows upload progress, tries again when
// the connection drops (warehouse wifi), and once the photos are up offers a way to keep packing:
// the server finishes the check and saves the record either way. Without this the form posts normally.
document.addEventListener("submit", (e) => {
  const form = e.target;
  if (!form.matches("[data-upload]") || !window.FormData || !window.XMLHttpRequest) return;
  e.preventDefault();
  const data = new FormData(form);
  if (e.submitter && e.submitter.name) data.append(e.submitter.name, e.submitter.value);
  const text = form.querySelector("[data-busy-text]");
  const keep = form.querySelector("[data-keep-going]");
  const say = (msg) => {
    if (text) text.textContent = msg;
  };
  const started = Date.now();
  let tries = 0;

  function giveUp() {
    form.classList.remove("working");
    form.querySelectorAll("button").forEach((b) => (b.disabled = false));
    let note = form.querySelector("[data-upload-error]");
    if (!note) {
      note = document.createElement("div");
      note.className = "callout error upload-error";
      note.dataset.uploadError = "";
      note.setAttribute("role", "alert");
      form.prepend(note);
    }
    note.textContent = "The photos couldn't be sent. Check the connection, then tap the button again. Nothing was lost.";
  }

  function send() {
    tries += 1;
    const xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable && ev.total > 50000) say(`Sending the photos: ${Math.round((ev.loaded / ev.total) * 100)}%`);
    };
    xhr.upload.onload = () => {
      say("Checking the box. This usually takes a few seconds.");
      if (keep) setTimeout(() => (keep.hidden = false), Math.max(0, 2000 - (Date.now() - started)));
    };
    xhr.onload = () => {
      // A result redirects to the record; anything else (a photo to retake, an error) is a page to show.
      const action = new URL(form.action, location.href).pathname;
      if (xhr.responseURL && new URL(xhr.responseURL).pathname !== action) {
        location.href = xhr.responseURL;
        return;
      }
      document.open();
      document.write(xhr.responseText);
      document.close();
    };
    xhr.onerror = () => {
      if (tries > 3) {
        giveUp();
        return;
      }
      say(`The connection dropped. Trying again (${tries} of 3)`);
      setTimeout(send, 1000 * 2 ** (tries - 1));
    };
    xhr.send(data);
  }
  send();
});

// Guided photos with the rear camera (section 4): a frame on screen and what each shot should
// show. The camera needs HTTPS (or localhost); without it the button stays hidden and the photo
// picker works as before.
(function () {
  const view = document.querySelector("[data-camera]");
  const open = document.querySelector("[data-camera-open]");
  if (!view || !open || !window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
  const input = open.closest("form").querySelector("input[type=file]");
  const video = view.querySelector("[data-camera-video]");
  const plan = JSON.parse(view.querySelector("[data-camera-plan]").textContent);
  const guide = view.querySelector("[data-camera-guide]");
  const count = view.querySelector("[data-camera-count]");
  const strip = view.querySelector("[data-camera-shots]");
  const done = view.querySelector("[data-camera-done]");
  const shoot = view.querySelector("[data-camera-shoot]");
  let stream = null;
  let shots = [];
  let saving = false; // a shot is still being turned into a JPEG
  open.hidden = false;
  video.addEventListener("loadeddata", () => show());

  function show() {
    const n = shots.length;
    count.textContent = n < plan.length ? `Photo ${n + 1} of ${plan.length}` : `${n} photos taken`;
    guide.textContent = n < plan.length ? plan[n] : "That's every photo this check uses.";
    const ready = video.videoWidth > 0;
    if (!ready) guide.textContent = "Starting the camera";
    shoot.disabled = !ready || saving || n >= plan.length;
    done.disabled = saving || n === 0;
    done.textContent = n ? `Use ${n} photo${n > 1 ? "s" : ""}` : "Use photos";
    strip.innerHTML = "";
    shots.forEach((blob, i) => {
      const img = document.createElement("img");
      img.src = URL.createObjectURL(blob);
      img.alt = `Photo ${i + 1}`;
      strip.appendChild(img);
    });
  }

  function close() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    view.hidden = true;
    document.body.classList.remove("camera-on");
    open.focus();
  }

  open.addEventListener("click", async () => {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1440 } },
        audio: false,
      });
    } catch (err) {
      alert("The camera didn't start. Allow camera access, or choose a photo instead.");
      return;
    }
    video.srcObject = stream;
    shots = [];
    view.hidden = false;
    document.body.classList.add("camera-on");
    show();
    video.play().catch(() => {});
  });

  shoot.addEventListener("click", () => {
    if (!video.videoWidth || saving) return;
    saving = true;
    show();
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      saving = false;
      if (blob) shots.push(blob);
      show();
    }, "image/jpeg", 0.92);
  });

  view.querySelector("[data-camera-cancel]").addEventListener("click", close);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !view.hidden) close();
  });

  done.addEventListener("click", () => {
    const files = new DataTransfer();
    shots.forEach((blob, i) => files.items.add(new File([blob], `photo-${i + 1}.jpg`, { type: "image/jpeg" })));
    input.files = files.files;
    showPreviews(input);
    close();
  });
})();
