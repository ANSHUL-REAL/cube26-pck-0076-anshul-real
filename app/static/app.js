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
  // Light / dark. Saved in this browser; until chosen, the page follows the device.
  if (e.target.closest("button[data-theme-toggle]")) {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (err) { /* private mode: not remembered */ }
  }

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

// Sending the photos (Evidence Contract 1.1, section 4). Shows upload progress and tries again
// when the connection drops before the photos arrive (warehouse wifi). Within 2 s there's always
// a way past the wait: "Stop sending" while the photos are on their way, then "Keep packing" once
// they've arrived (the server finishes the check and saves the record either way). Without this
// script the form posts normally.
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
  let tries = 0;
  let uploaded = false; // once the photos have arrived, a retry could save the box twice
  let xhr = null;
  let stop = null;

  function reset() {
    form.classList.remove("working");
    form.querySelectorAll("button").forEach((b) => (b.disabled = false));
    if (stop) stop.remove();
    if (keep) keep.hidden = true;
  }

  function note(message) {
    let el = form.querySelector("[data-upload-error]");
    if (!el) {
      el = document.createElement("div");
      el.className = "callout error upload-error";
      el.dataset.uploadError = "";
      el.setAttribute("role", "alert");
      form.prepend(el);
    }
    el.textContent = message;
  }

  function offerWayPast() {
    if (uploaded) {
      if (stop) stop.remove();
      if (keep) keep.hidden = false;
      return;
    }
    if (stop) return;
    stop = document.createElement("p");
    stop.className = "keep-going";
    stop.append("Slow connection. ");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "linkish";
    button.textContent = "Stop sending";
    button.addEventListener("click", () => {
      if (xhr) xhr.abort();
      reset();
      note("Sending stopped. Your photos are still selected: tap the button again when the connection is better.");
    });
    stop.append(button, ". Your photos stay selected.");
    form.append(stop);
  }

  function send() {
    tries += 1;
    xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable && ev.total > 50000) say(`Sending the photos: ${Math.round((ev.loaded / ev.total) * 100)}%`);
    };
    xhr.upload.onload = () => {
      uploaded = true;
      say("Checking the box. This usually takes a few seconds.");
      if (stop) offerWayPast(); // already past 2 s: swap "Stop sending" for "Keep packing"
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
      if (uploaded) {
        reset();
        note("The connection dropped after the photos were sent, so the check may already be saved. Open this order again to see it before checking again.");
        return;
      }
      if (tries > 3) {
        reset();
        note("The photos couldn't be sent. Check the connection, then tap the button again. Nothing was lost.");
        return;
      }
      say(`The connection dropped. Trying again (${tries} of 3)`);
      setTimeout(send, 1000 * 2 ** (tries - 1));
    };
    xhr.send(data);
  }
  setTimeout(() => {
    if (form.classList.contains("working")) offerWayPast();
  }, 2000);
  send();
});

// Guided photos with the rear camera (section 4): a frame on screen and what each shot should
// show. The camera needs HTTPS (or localhost); without it the button stays hidden and the photo
// picker works as before.
(function () {
  const view = document.querySelector("[data-camera]");
  const open = document.querySelector("[data-camera-open]");
  if (!view || !open || !window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
  try {
    new DataTransfer(); // how the shots become the form's photos; missing before iOS 14.5
  } catch (err) {
    return;
  }
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
