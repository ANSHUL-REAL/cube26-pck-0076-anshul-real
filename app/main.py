"""Pack Manager web app: pick an order, photograph the open box, get SEAL / STOP & FIX /
CHECK BY HAND with the evidence behind it."""

from __future__ import annotations

import base64
import logging
import time
import uuid
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from pack_manager import __version__
from pack_manager.catalogue import load_org_catalogue, reference_images
from pack_manager.config import get_settings
from pack_manager.evidence import apply_override, verify
from pack_manager.models import OVERRIDE_REASONS, Catalogue, Decision, EvidenceRecord
from pack_manager.pipeline import Photo, QualityRejected, prepare_photos, verify_box
from pack_manager.quality import ImageDecodeError, PreparedImage
from pack_manager.vision.base import PerceptionError

from . import store
from .db import Database
from .icons import icon

log = logging.getLogger("pack_manager.app")
BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
settings = get_settings()

app = FastAPI(title="Pack Manager", version=__version__)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax", max_age=12 * 3600)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

DECISION_UI = {
    "SEAL": ("Seal the box", "seal"),
    "STOP_AND_FIX": ("Stop and fix", "stop"),
    "UNCERTAIN": ("Check by hand", "unsure"),
    "PENDING": ("Needs your decision", "pending"),
}
DECISION_ICON = {"SEAL": "circle-check", "STOP_AND_FIX": "octagon-x", "UNCERTAIN": "circle-help", "PENDING": "clock"}
DECISION_BLURB = {
    "SEAL": "Everything in the order is in the box, and nothing else.",
    "STOP_AND_FIX": "Something is missing, wrong or extra. Fix it before sealing.",
    "UNCERTAIN": "The photos can't settle it. Check the box by hand before sealing.",
    "PENDING": "The AI check didn't finish. The photos are saved; check by hand.",
}
VERDICT_ICON = {"PASS": "check", "FAIL": "x", "UNCERTAIN": "circle-help", "NOT_CHECKED": "minus"}


def _initials(text: str | None) -> str:
    words = [w for w in (text or "").replace("-", " ").split() if w[:1].isalnum()]
    return "".join(w[0] for w in words[:2]).upper() or "?"


def _hue(text: str | None) -> int:
    """A stable colour per SKU or name, for the letter tiles."""
    return sum((i + 1) * ord(c) for i, c in enumerate(text or "")) * 47 % 360


templates.env.globals.update(DECISION_UI=DECISION_UI, DECISION_ICON=DECISION_ICON,
                             DECISION_BLURB=DECISION_BLURB, VERDICT_ICON=VERDICT_ICON, icon=icon)
templates.env.filters["when"] = lambda dt: dt.strftime("%d %b, %H:%M UTC") if dt else ""
templates.env.filters["initials"] = _initials
templates.env.filters["hue"] = _hue


# ------------------------------------------------------------------ dependencies

_db: Database | None = None


def db() -> Database:
    global _db
    if _db is None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not set.")
        _db = Database(settings.database_url)
    return _db


class _NoModel:
    """Used when no API key is configured: every check fails open to a pending record."""

    def perceive(self, *args, **kwargs):
        raise PerceptionError("GEMINI_API_KEY is not set.")


@lru_cache
def perceiver():
    if settings.gemini_api_key:
        from pack_manager.vision.gemini import GeminiPerceiver

        return GeminiPerceiver(settings)
    return _NoModel()


@lru_cache
def org_catalogue(org_id: str) -> tuple[Catalogue, Path]:
    return load_org_catalogue(ROOT / settings.catalogue_dir, org_id)


class LoginRequired(Exception):
    pass


@app.exception_handler(LoginRequired)
async def _to_login(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


def current_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise LoginRequired()
    return user


def page(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
    ctx.setdefault("user", request.session.get("user"))
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def not_found(request: Request, what: str = "That page") -> HTMLResponse:
    return page(request, "not_found.html", status_code=404, what=what)


# Photos that failed the quality gate, kept briefly so "use anyway" doesn't need a re-upload.
_STASH: dict[str, tuple[str, str, list[PreparedImage], float]] = {}


def _stash_put(org: str, order_id: str, photos: list[PreparedImage]) -> str:
    now = time.time()
    for key in [k for k, v in _STASH.items() if now - v[3] > 900]:
        _STASH.pop(key, None)
    key = uuid.uuid4().hex
    _STASH[key] = (org, order_id, photos, now)
    return key


# ------------------------------------------------------------------ sign in


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return page(request, "login.html", demo_codes=["alpha-demo", "bravo-demo"])


@app.post("/login")
def login(request: Request, code: str = Form(...)):
    with db().anonymous() as cur:
        found = store.resolve_code(cur, code)
    if not found:
        return page(request, "login.html", status_code=401, error="That access code isn't recognised.",
                    demo_codes=["alpha-demo", "bravo-demo"])
    with db().org(found["organization_id"]) as cur:
        name = store.org_name(cur, found["organization_id"])
    request.session["user"] = {"org": found["organization_id"], "org_name": name,
                               "operator": found["operator_label"]}
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ------------------------------------------------------------------ orders & checking a box


@app.get("/", response_class=HTMLResponse)
def orders(request: Request, q: str | None = None):
    user = current_user(request)
    with db().org(user["org"]) as cur:
        rows = store.list_orders(cur, q)
        counts = store.counts_by_decision(cur)
    catalogue, _ = org_catalogue(user["org"])
    return page(request, "orders.html", rows=rows, counts=counts, q=q or "", catalogue=catalogue,
                thumbs=_thumbs(catalogue))


def _thumbs(catalogue: Catalogue) -> set[str]:
    """SKUs that have a reference photo to show as a thumbnail."""
    return {i.sku for i in catalogue.items if i.reference_images}


def _verify_page(request, user, order, **extra):
    catalogue, root = org_catalogue(user["org"])
    with db().org(user["org"]) as cur:
        history = store.list_records(cur, order_id=order.order_id, limit=10)
    lines = []
    for line in order.lines:
        item = catalogue.get(line.sku)
        has_ref = bool(item and reference_images(item, root, settings))
        lines.append({"sku": line.sku, "qty": line.qty, "title": catalogue.title(line.sku),
                      "attributes": item.attributes if item else {}, "thumb": has_ref})
    return page(request, "verify.html", order=order, lines=lines, history=history,
                max_photos=settings.max_box_photos, **extra)


@app.get("/orders/{order_id}", response_class=HTMLResponse)
def verify_form(request: Request, order_id: str):
    user = current_user(request)
    with db().org(user["org"]) as cur:
        order = store.get_order(cur, order_id)
    if not order:
        return not_found(request, "That order")
    return _verify_page(request, user, order)


@app.post("/orders/{order_id}/verify")
async def verify_submit(
    request: Request,
    order_id: str,
    photos: list[UploadFile] = File(default=[]),
    stash: str | None = Form(default=None),
):
    user = current_user(request)
    with db().org(user["org"]) as cur:
        order = store.get_order(cur, order_id)
    if not order:
        return not_found(request, "That order")

    force = False
    if stash:
        held = _STASH.pop(stash, None)
        if not held or held[0] != user["org"] or held[1] != order_id:
            return _verify_page(request, user, order, error="Those photos expired. Please take them again.")
        prepared, force = held[2], True
    else:
        uploads = [await f.read() for f in photos if f.filename]
        try:
            prepared = await run_in_threadpool(
                prepare_photos,
                [Photo(data, "top_down" if i == 0 else f"extra_{i}") for i, data in enumerate(uploads)],
                settings,
            )
        except (ValueError, ImageDecodeError) as exc:
            return _verify_page(request, user, order, error=str(exc))

    catalogue, root = org_catalogue(user["org"])
    try:
        record = await run_in_threadpool(
            verify_box, order, prepared, catalogue, perceiver(), settings,
            operator_label=user["operator"], catalogue_root=root, force_quality=force,
        )
    except QualityRejected as exc:
        rejected = [
            {"n": i, "reasons": r.reasons, "ok": r.gate == "PASS",
             "src": "data:image/jpeg;base64," + base64.b64encode(p.jpeg).decode()}
            for i, (r, p) in enumerate(zip(exc.reports, prepared), 1)
        ]
        return _verify_page(request, user, order, rejected=rejected,
                            stash=_stash_put(user["org"], order_id, prepared))

    with db().org(user["org"]) as cur:
        store.save_record(cur, record, prepared)
    return RedirectResponse(f"/records/{record.record_id}", status_code=303)


@app.get("/catalogue/{sku}/thumb")
def catalogue_thumb(request: Request, sku: str):
    user = current_user(request)
    catalogue, root = org_catalogue(user["org"])
    item = catalogue.get(sku)
    refs = reference_images(item, root, settings) if item else []
    if not refs:
        return Response(status_code=404)
    return Response(refs[0], media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# ------------------------------------------------------------------ records


def _object_states(record: EvidenceRecord) -> dict[str, str]:
    obs = record.observations or {}
    state = {}
    for o in obs.get("detected_items", []):
        state[o["object_id"]] = "insert" if o["classification"] == "NON_PRODUCT" else "ok"
    for o in obs.get("unclear", []):
        state[o["object_id"]] = "unsure"
    for o in obs.get("wrong", []) + obs.get("extra", []):
        state[o["object_id"]] = "problem"
    return state


@app.get("/records", response_class=HTMLResponse)
def records(request: Request, decision: str | None = None):
    user = current_user(request)
    decision = decision if decision in DECISION_UI else None
    with db().org(user["org"]) as cur:
        rows = store.list_records(cur, decision=decision)
        counts = store.counts_by_decision(cur)
    return page(request, "records.html", rows=rows, counts=counts, decision=decision)


@app.get("/records/{record_id}", response_class=HTMLResponse)
def record_page(request: Request, record_id: str):
    user = current_user(request)
    with db().org(user["org"]) as cur:
        record = store.get_record(cur, record_id)
    if not record:
        return not_found(request, "That record")
    catalogue, _ = org_catalogue(user["org"])
    agent_decision = record.overrides[0].original_decision if record.overrides else record.outcome.decision
    tally = {"PASS": 0, "FAIL": 0, "UNCERTAIN": 0}
    for c in record.checks:
        if c.verdict.value in tally:
            tally[c.verdict.value] += 1
    return page(
        request, "record.html", r=record, hash_ok=verify(record), states=_object_states(record),
        agent_decision=agent_decision, reasons=OVERRIDE_REASONS, catalogue=catalogue,
        obs=record.observations or {}, tally=tally, thumbs=_thumbs(catalogue),
    )


@app.post("/records/{record_id}/decision")
def record_decision(
    request: Request,
    record_id: str,
    decision: str = Form(...),
    reason_code: str = Form(...),
    note: str = Form(default=""),
):
    user = current_user(request)
    if decision not in ("SEAL", "STOP_AND_FIX") or reason_code not in OVERRIDE_REASONS:
        return RedirectResponse(f"/records/{record_id}", status_code=303)
    with db().org(user["org"]) as cur:
        record = store.get_record(cur, record_id)
        if not record:
            return not_found(request, "That record")
        updated = apply_override(record, Decision(decision), reason_code, user["operator"], note.strip()[:500])
        store.update_record(cur, updated)
    return RedirectResponse(f"/records/{record_id}", status_code=303)


@app.get("/images/{image_id}")
def image(request: Request, image_id: str):
    user = current_user(request)
    try:
        uuid.UUID(image_id)
    except ValueError:
        return Response(status_code=404)
    with db().org(user["org"]) as cur:
        found = store.get_image(cur, image_id)
    if not found:
        return Response(status_code=404)
    mime, content = found
    return Response(content, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})


# ------------------------------------------------------------------ JSON API (for Returns / Recovery)


def _api_user(request: Request) -> dict | None:
    code = request.headers.get("x-access-code")
    if code:
        with db().anonymous() as cur:
            found = store.resolve_code(cur, code)
        return {"org": found["organization_id"], "operator": found["operator_label"]} if found else None
    return request.session.get("user")


@app.get("/api/records")
def api_records(request: Request, order_id: str | None = None, unit_id: str | None = None):
    user = _api_user(request)
    if not user:
        return JSONResponse({"error": "unauthorised"}, status_code=401)
    with db().org(user["org"]) as cur:
        rows = store.list_records(cur, order_id=order_id, unit_id=unit_id, limit=500)
        full = [store.get_record(cur, r["record_id"]).model_dump(mode="json") for r in rows]
    return {"records": full}


@app.get("/api/records/{record_id}")
def api_record(request: Request, record_id: str):
    user = _api_user(request)
    if not user:
        return JSONResponse({"error": "unauthorised"}, status_code=401)
    with db().org(user["org"]) as cur:
        record = store.get_record(cur, record_id)
    if not record:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {**record.model_dump(mode="json"), "_hash_verified": verify(record)}


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__, "vision_model": settings.gemini_model,
            "vision_configured": bool(settings.gemini_api_key)}
