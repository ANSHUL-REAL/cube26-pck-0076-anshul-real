"""Pack Manager web app: pick an order, photograph the open box, get SEAL / STOP & FIX /
CHECK BY HAND with the evidence behind it."""

from __future__ import annotations

import base64
import csv
import io
import logging
import secrets
import time
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlsplit

import psycopg2
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from pack_manager import __version__
from pack_manager.catalogue import load_org_catalogue, reference_images
from pack_manager.config import get_settings
from pack_manager.evidence import apply_override, verify, verify_history
from pack_manager.export import CSV_COLUMNS, record_row
from pack_manager.models import OVERRIDE_REASONS, Catalogue, Decision, EvidenceRecord
from pack_manager.orders import parse_orders_csv
from pack_manager.pipeline import Photo, QualityRejected, prepare_photos, rerun_box, verify_box
from pack_manager.quality import ImageDecodeError, PreparedImage
from pack_manager.vision.base import PerceptionError

from . import store
from .db import Database, DatabaseBusy
from .icons import icon
from .migrate import DEMO_CODES, ORGS

log = logging.getLogger("pack_manager.app")
BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
settings = get_settings()


def session_secret(configured: str | None) -> str:
    """The key that signs sign-in cookies. With the default or a short key anyone could forge a
    sign-in, so a random key is used instead (everyone is then signed out when the app restarts)."""
    if configured and configured != "change-me" and len(configured) >= 32:
        return configured
    log.warning("SESSION_SECRET is not set, is the default, or is shorter than 32 characters. Using a "
                "random one for now, so everyone is signed out when the app restarts. Set it to a long "
                "random value, e.g. python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
    return secrets.token_urlsafe(48)


def _origin(scheme: str, netloc: str) -> str:
    """The host a request came from or went to. Only the host is compared: behind a proxy that
    ends HTTPS the app may see "http" while the browser says "https", and a different site can't
    have the same host anyway."""
    netloc = netloc.lower()
    default_port = {"http": ":80", "https": ":443"}.get(scheme)
    if default_port and netloc.endswith(default_port):
        netloc = netloc[: -len(default_port)]
    return netloc


class SameOriginPosts:
    """Refuse a form post sent from another website (cross-site request forgery). Browsers send
    an Origin header with every POST; a request without one (curl, other pods, tests) passes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] not in ("GET", "HEAD", "OPTIONS"):
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            if origin is not None:
                sent = urlsplit(origin)
                if _origin(sent.scheme, sent.netloc) != _origin(scope.get("scheme", "http"), headers.get("host", "")):
                    response = error_page(Request(scope), 403, "Not accepted",
                                          "This form was sent from another website, so it wasn't accepted. "
                                          "Open Pack Manager and try again.")
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


app = FastAPI(title="Pack Manager", version=__version__)
app.add_middleware(SessionMiddleware, secret_key=session_secret(settings.session_secret), same_site="lax",
                   max_age=12 * 3600, https_only=settings.secure_cookies)
app.add_middleware(SameOriginPosts)
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


# Changes whenever the CSS or JS changes, so phones don't keep an old copy after a deploy.
ASSET_VERSION = str(max(int((BASE / "static" / name).stat().st_mtime) for name in ("app.css", "app.js")))
templates.env.globals.update(DECISION_UI=DECISION_UI, DECISION_ICON=DECISION_ICON,
                             DECISION_BLURB=DECISION_BLURB, VERDICT_ICON=VERDICT_ICON, icon=icon,
                             ASSET_VERSION=ASSET_VERSION)
def _when(dt) -> str:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return dt.strftime("%d %b, %H:%M UTC") if dt else ""


templates.env.filters["when"] = _when


def url_part(value) -> str:
    """An id as one URL path segment. Jinja's urlencode leaves "/" alone, which would split it."""
    return quote(str(value), safe="")


templates.env.filters["urlpart"] = url_part


def order_url(order_id: str) -> str:
    return f"/orders/{url_part(order_id)}"


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


class _OverLimit:
    """Used once an organisation reaches its daily number of AI checks."""

    def perceive(self, *args, **kwargs):
        raise PerceptionError(
            f"This company has used today's {settings.daily_checks_per_org} AI checks. Check this box by hand.")


def perceiver_for(org_id: str):
    limit = settings.daily_checks_per_org
    if limit:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        with db().org(org_id) as cur:
            if store.count_ai_checks_since(cur, today) >= limit:
                return _OverLimit()
    return perceiver()


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


def not_found(request: Request, what: str = "That page", status_code: int = 404) -> HTMLResponse:
    return page(request, "not_found.html", status_code=status_code, what=what)


def _is_api(request: Request) -> bool:
    return request.url.path == "/api" or request.url.path.startswith("/api/")


def error_page(request: Request, status_code: int, title: str, message: str, user: dict | None = None) -> Response:
    """A plain error page (JSON for the API). Doesn't read the session, so it also works
    outside the session middleware."""
    if _is_api(request):
        return JSONResponse({"error": message}, status_code=status_code)
    return templates.TemplateResponse(request, "error.html", {"user": user, "title": title, "message": message},
                                      status_code=status_code)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if _is_api(request):
        return await http_exception_handler(request, exc)
    if exc.status_code in (404, 405):
        response = not_found(request, status_code=exc.status_code)
    else:
        response = error_page(request, exc.status_code, "Something went wrong",
                              "That request couldn't be read. Go back and try again.",
                              user=request.session.get("user"))
    response.headers.update(exc.headers or {})
    return response


@app.exception_handler(RequestValidationError)
async def _bad_request(request: Request, exc: RequestValidationError):
    if _is_api(request):
        return await request_validation_exception_handler(request, exc)
    return error_page(request, 400, "Something was missing",
                      "Part of the form was missing or couldn't be read. Go back and try again.",
                      user=request.session.get("user"))


@app.exception_handler(Exception)
async def _server_error(request: Request, exc: Exception):
    # The server logs the full traceback too; this line says which page it was.
    log.error("Error on %s %s: %s: %s", request.method, request.url.path, type(exc).__name__, exc)
    if isinstance(exc, (DatabaseBusy, psycopg2.OperationalError)):
        return error_page(request, 503, "Please try again",
                          "The database isn't answering right now. Wait a moment and try again.")
    return error_page(request, 500, "Something went wrong",
                      "Something went wrong on our side. Try again, and if it keeps happening, tell your team lead.")


# Photos that failed the quality gate, kept briefly so "use anyway" doesn't need a re-upload.
# They are held in memory, so both the number kept and how long are capped.
_STASH: dict[str, tuple[str, str, list[PreparedImage], float]] = {}
STASH_MAX = 50
STASH_TTL_S = 900


def _stash_put(org: str, order_id: str, photos: list[PreparedImage]) -> str:
    now = time.time()
    for key in [k for k, v in _STASH.items() if now - v[3] > STASH_TTL_S]:
        _STASH.pop(key, None)
    while len(_STASH) >= STASH_MAX:
        _STASH.pop(next(iter(_STASH)))  # the oldest: a dict keeps insertion order
    key = uuid.uuid4().hex
    _STASH[key] = (org, order_id, photos, now)
    return key


def _stash_take(key: str, org: str, order_id: str) -> list[PreparedImage] | None:
    held = _STASH.pop(key, None)
    if not held or held[0] != org or held[1] != order_id or time.time() - held[3] > STASH_TTL_S:
        return None
    return held[2]


# ------------------------------------------------------------------ sign in


# The public demo companies shown on the sign-in page (seeded by app.migrate).
DEMO_ORGS = [{"code": code, "name": ORGS[org].removesuffix(" (demo)")} for code, (org, _) in DEMO_CODES.items()]


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return page(request, "login.html", demo_orgs=DEMO_ORGS)


@app.post("/login")
def login(request: Request, code: str = Form(default="")):
    code = code.strip()
    if not code:
        return page(request, "login.html", status_code=400, error="Enter your access code.", demo_orgs=DEMO_ORGS)
    with db().anonymous() as cur:
        found = store.resolve_code(cur, code)
    if not found:
        return page(request, "login.html", status_code=401, error="That access code isn't recognised. Check it and try again.",
                    demo_orgs=DEMO_ORGS)
    with db().org(found["organization_id"]) as cur:
        name = store.org_name(cur, found["organization_id"])
    request.session["user"] = {"org": found["organization_id"], "org_name": name,
                               "operator": found["operator_label"]}
    return RedirectResponse("/", status_code=303)


@app.api_route("/logout", methods=["GET", "POST"])
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ------------------------------------------------------------------ orders & checking a box

ORDERS_SHOWN = 200  # rows on one tab of the orders page; the tab counts cover every order


@app.get("/", response_class=HTMLResponse)
def orders(request: Request, q: str | None = None, view: str = "todo"):
    user = current_user(request)
    view = view if view in ("todo", "done", "all") else "todo"
    q = (q or "").strip()[:100]
    with db().org(user["org"]) as cur:
        rows = store.list_orders(cur, q or None, view=view, limit=ORDERS_SHOWN)
        view_counts = store.order_counts(cur, q or None)
        counts = store.counts_by_decision(cur)
    catalogue, _ = org_catalogue(user["org"])
    return page(request, "orders.html", rows=rows, view=view, view_counts=view_counts,
                counts=counts, q=q, catalogue=catalogue, thumbs=_thumbs(catalogue))


@app.get("/orders/import", response_class=HTMLResponse)
def import_form(request: Request):
    current_user(request)
    return page(request, "import.html")


MAX_CSV_BYTES = 2_000_000


def _parse_import(org: str, text: str):
    catalogue, _ = org_catalogue(org)
    return parse_orders_csv(text, org, catalogue)


def _save_import(org: str, orders: list) -> int:
    """Saves the orders; returns how many already existed."""
    updated = 0
    with db().org(org) as cur:
        for order in orders:
            updated += store.get_order(cur, order.order_id) is not None
            store.upsert_order(cur, order, source="csv_import")
    return updated


@app.post("/orders/import", response_class=HTMLResponse)
async def import_submit(request: Request, file: UploadFile | None = File(default=None)):
    user = current_user(request)
    if file is None or not file.filename:
        return page(request, "import.html", status_code=400, error="Choose a CSV file first.")
    data = await file.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        return page(request, "import.html", status_code=413,
                    error="This file is larger than 2 MB. Split it into smaller files and import them one at a time.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return page(request, "import.html", error="Save the file as CSV (UTF-8) and try again.")
    try:
        result = await run_in_threadpool(_parse_import, user["org"], text)
    except (ValueError, csv.Error) as exc:
        log.info("CSV import couldn't be parsed: %s", exc)
        return page(request, "import.html", status_code=400,
                    error="This file couldn't be read as a list of orders. Check it against the file format and try again.")
    updated = await run_in_threadpool(_save_import, user["org"], result.orders)
    return page(request, "import.html", result=result, updated=updated)


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


# Order ids come from imports and can contain "/", so the order routes take the rest of the path.
@app.get("/orders/{order_id:path}/verify")
def verify_reload(order_id: str):
    """The "photo could be clearer" page is shown at this address; opening it again shows the order."""
    return RedirectResponse(order_url(order_id), status_code=303)


@app.get("/orders/{order_id:path}", response_class=HTMLResponse)
def verify_form(request: Request, order_id: str):
    user = current_user(request)
    with db().org(user["org"]) as cur:
        order = store.get_order(cur, order_id)
    if not order:
        return not_found(request, "That order")
    return _verify_page(request, user, order)


MAX_PHOTO_BYTES = 15 * 1024 * 1024
PHOTO_UNREADABLE = "A photo couldn't be read. Take it again, or choose a JPEG or PNG photo."


async def _read_capped(upload: UploadFile, cap: int) -> bytes | None:
    """The whole file, or None if it is larger than cap. Reads in chunks, so a huge file is
    never held in memory in full."""
    chunks, size = [], 0
    while chunk := await upload.read(min(1 << 20, cap + 1 - size)):
        chunks.append(chunk)
        size += len(chunk)
        if size > cap:
            return None
    return b"".join(chunks)


def _get_order(org: str, order_id: str):
    with db().org(org) as cur:
        return store.get_order(cur, order_id)


def _check_box(user: dict, order, prepared: list[PreparedImage], force: bool) -> EvidenceRecord:
    """The model call and the database work for one box. Blocking, so it runs in a thread."""
    catalogue, root = org_catalogue(user["org"])
    with db().org(user["org"]) as cur:
        earlier = store.find_image_uses(cur, [p.sha256 for p in prepared])
    record = verify_box(
        order, prepared, catalogue, perceiver_for(user["org"]), settings,
        operator_label=user["operator"], catalogue_root=root, force_quality=force, earlier_uses=earlier,
    )
    with db().org(user["org"]) as cur:
        store.save_record(cur, record, prepared)
    return record


@app.post("/orders/{order_id:path}/verify")
async def verify_submit(
    request: Request,
    order_id: str,
    photos: list[UploadFile] = File(default=[]),
    stash: str | None = Form(default=None),
):
    user = current_user(request)
    order = await run_in_threadpool(_get_order, user["org"], order_id)
    if not order:
        return not_found(request, "That order")

    async def again(**extra):
        return await run_in_threadpool(_verify_page, request, user, order, **extra)

    force = False
    if stash:
        prepared = _stash_take(stash, user["org"], order_id)
        if prepared is None:
            return await again(error="Those photos expired. Please take them again.")
        force = True
    else:
        # Only the first few photos are used; the page says so when more are chosen.
        uploads = []
        for n, f in enumerate([f for f in photos if f.filename][: settings.max_box_photos], 1):
            data = await _read_capped(f, MAX_PHOTO_BYTES)
            if data is None:
                return await again(error=f"Photo {n} is larger than {MAX_PHOTO_BYTES // 2**20} MB. "
                                         "Take it again, or choose a smaller copy.")
            uploads.append(data)
        try:
            prepared = await run_in_threadpool(
                prepare_photos,
                [Photo(data, "top_down" if i == 0 else f"extra_{i}") for i, data in enumerate(uploads)],
                settings,
            )
        except (ImageDecodeError, ValueError) as exc:  # the message is written for the packer
            return await again(error=str(exc) or PHOTO_UNREADABLE)
        except Exception as exc:  # any other decoding problem: a message, not a server error
            log.warning("Couldn't prepare an uploaded photo: %s: %s", type(exc).__name__, exc)
            return await again(error=PHOTO_UNREADABLE)

    try:
        record = await run_in_threadpool(_check_box, user, order, prepared, force)
    except QualityRejected as exc:
        rejected = [
            {"n": i, "reasons": r.reasons, "ok": r.gate == "PASS",
             "src": "data:image/jpeg;base64," + base64.b64encode(p.jpeg).decode()}
            for i, (r, p) in enumerate(zip(exc.reports, prepared), 1)
        ]
        return await again(rejected=rejected, stash=_stash_put(user["org"], order_id, prepared))
    except ValueError as exc:  # e.g. an order with no lines to check against
        return await again(error=str(exc))
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
def records(request: Request, decision: str | None = None, q: str | None = None):
    user = current_user(request)
    decision = decision if decision in DECISION_UI else None
    q = (q or "").strip()[:100]
    with db().org(user["org"]) as cur:
        rows = store.list_records(cur, decision=decision, query=q or None)
        counts = store.counts_by_decision(cur)
    return page(request, "records.html", rows=rows, counts=counts, decision=decision, q=q)


# The check of the whole override chain, shown next to the content hash on a decided record.
HISTORY_CHECK = {
    True: ("ok", "Every earlier version checks out"),
    False: ("warn", "An earlier version doesn't match its hash"),
    None: ("plain", "Earlier versions can't be rebuilt (made before this check existed)"),
}


def _record_page(request: Request, user: dict, record: EvidenceRecord, status_code: int = 200, **extra):
    catalogue, _ = org_catalogue(user["org"])
    agent_decision = record.overrides[0].original_decision if record.overrides else record.outcome.decision
    tally = {"PASS": 0, "FAIL": 0, "UNCERTAIN": 0}
    for c in record.checks:
        if c.verdict.value in tally:
            tally[c.verdict.value] += 1
    with db().org(user["org"]) as cur:
        later = [row for row in store.list_records(cur, order_id=record.subject.get("order_id"), limit=20)
                 if row["captured_at"] >= record.captured_at and row["record_id"] != record.record_id]
        retry = store.find_retry(cur, record.record_id)
    return page(
        request, "record.html", status_code=status_code, r=record, hash_ok=verify(record),
        history_check=HISTORY_CHECK[verify_history(record)] if record.overrides else None,
        states=_object_states(record), agent_decision=agent_decision, reasons=OVERRIDE_REASONS,
        catalogue=catalogue, obs=record.observations or {}, tally=tally, thumbs=_thumbs(catalogue),
        later=later, retry=retry, can_retry=agent_decision == Decision.PENDING and not retry, **extra,
    )


@app.get("/records/{record_id}", response_class=HTMLResponse)
def record_page(request: Request, record_id: str):
    user = current_user(request)
    with db().org(user["org"]) as cur:
        record = store.get_record(cur, record_id)
    if not record:
        return not_found(request, "That record")
    return _record_page(request, user, record)


@app.get("/records/{record_id}/{action}")
def record_action_reload(record_id: str, action: str):
    """A record page shown after a refused form post has this address; opening it again shows the record."""
    if action not in ("decision", "retry"):
        raise StarletteHTTPException(status_code=404)
    return RedirectResponse(f"/records/{url_part(record_id)}", status_code=303)


def _load_for_retry(org: str, record_id: str):
    with db().org(org) as cur:
        record = store.get_record(cur, record_id)
        if not record:
            return None
        retry = store.find_retry(cur, record_id)
        stored = [store.get_image(cur, ref.image_id) for ref in record.images]
        earlier = store.find_image_uses(cur, [ref.sha256 for ref in record.images])
    return record, retry, stored, earlier


def _rerun(user: dict, record: EvidenceRecord, stored: list[bytes], earlier: list[dict]) -> str:
    """Runs the AI check again and saves the new record. Returns its id, or the id of a re-check
    someone else saved in the meantime: a record is only ever checked again once."""
    catalogue, root = org_catalogue(user["org"])
    new, prepared = rerun_box(
        record, stored, catalogue, perceiver_for(user["org"]), settings,
        retried_by=user["operator"], catalogue_root=root,
        earlier_uses=[u for u in earlier if u["record_id"] != record.record_id],
    )
    with db().org(user["org"]) as cur:
        existing = store.find_retry(cur, record.record_id, lock=True)
        if existing:
            return existing
        store.save_record(cur, new, prepared)
    return new.record_id


@app.post("/records/{record_id}/retry")
async def record_retry(request: Request, record_id: str):
    """Run the AI check again on a box the model didn't answer for. Creates a new, linked record."""
    user = current_user(request)
    loaded = await run_in_threadpool(_load_for_retry, user["org"], record_id)
    if loaded is None:
        return not_found(request, "That record")
    record, retry, stored, earlier = loaded
    if retry:  # already checked again: show that record instead of making another
        return RedirectResponse(f"/records/{url_part(retry)}", status_code=303)
    first = record.overrides[0].original_decision if record.overrides else record.outcome.decision
    if first != Decision.PENDING:
        return RedirectResponse(f"/records/{url_part(record_id)}", status_code=303)
    try:
        if any(s is None for s in stored):
            raise ValueError("Some photos of this box are missing.")
        new_id = await run_in_threadpool(_rerun, user, record, [data for _, data in stored], earlier)
    except ValueError as exc:  # the stored photos are missing or don't match their hashes
        log.warning("Retry of %s refused: %s", record_id, exc)
        return await run_in_threadpool(
            _record_page, request, user, record, status_code=409,
            error="The AI check can't run again: the saved photos don't match this record. "
                  "Check the box by hand and record your decision.")
    return RedirectResponse(f"/records/{url_part(new_id)}", status_code=303)


# Shown with a "Reload and check it again." link to the record.
CONFLICT = "This record changed while you were deciding."


@app.post("/records/{record_id}/decision")
def record_decision(
    request: Request,
    record_id: str,
    decision: str = Form(default=""),
    reason_code: str = Form(default=""),
    note: str = Form(default=""),
    prior_hash: str = Form(default=""),
):
    user = current_user(request)
    note = note.strip()[:500]
    with db().org(user["org"]) as cur:
        record = store.get_record(cur, record_id)
        retry = store.find_retry(cur, record_id) if record else None
    if not record:
        return not_found(request, "That record")

    def again(error: str, status_code: int, shown: EvidenceRecord = record):
        return _record_page(request, user, shown, status_code=status_code, error=error,
                            reload=error == CONFLICT, form_note=note, form_reason=reason_code)

    if retry:
        return again("The AI checked this box again. Record your decision on the newer record.", 409)
    if decision not in ("SEAL", "STOP_AND_FIX"):
        return again("Choose Seal the box or Stop and fix to record your decision.", 400)
    if reason_code not in OVERRIDE_REASONS:
        return again("Choose a reason for your decision.", 400)
    # The form carries the hash of the record as the operator saw it. The save only goes through
    # if the record still has that hash, so a decision someone else made meanwhile isn't lost.
    if prior_hash and prior_hash != record.content_hash:
        return again(CONFLICT, 409)
    try:
        updated = apply_override(record, Decision(decision), reason_code, user["operator"], note)
    except ValueError as exc:  # the record doesn't match its content hash
        return again(str(exc), 409)
    with db().org(user["org"]) as cur:
        saved = store.update_record(cur, updated, prior_hash=record.content_hash)
        latest = None if saved else store.get_record(cur, record_id)
    if not saved:
        return again(CONFLICT, 409, shown=latest or record)
    return RedirectResponse(f"/records/{url_part(record_id)}", status_code=303)


@app.get("/images/{image_id}")
def image(request: Request, image_id: str):
    user = current_user(request)
    try:
        image_id = str(uuid.UUID(image_id))  # the column is a uuid: always pass the plain form
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
def api_records(request: Request, order_id: str | None = None, unit_id: str | None = None,
                since: datetime | None = None):
    """For other pods. With `since`: records captured at or after it, oldest first; pass the
    returned `next_since` to get the next page, and dedupe by record_id."""
    user = _api_user(request)
    if not user:
        return JSONResponse({"error": "unauthorised"}, status_code=401)
    with db().org(user["org"]) as cur:
        rows = store.list_records(cur, order_id=order_id, unit_id=unit_id, since=since, limit=500)
        full = [store.get_record(cur, r["record_id"]).model_dump(mode="json") for r in rows]
    out: dict = {"records": full}
    if since is not None:
        out["next_since"] = full[-1]["captured_at"] if full else since.isoformat()
    return out


def _cell(value: str) -> str:
    """Stop spreadsheet apps from running a cell as a formula (order ids can come from a CSV import)."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


@app.get("/api/records.csv")
def api_records_csv(request: Request, since: datetime | None = None):
    """Every record as CSV: the organisers' pack_sample.csv columns first, then ours."""
    user = _api_user(request)
    if not user:
        return JSONResponse({"error": "unauthorised"}, status_code=401)
    with db().org(user["org"]) as cur:
        rows = store.list_records(cur, since=since, limit=1000)
        records = [store.get_record(cur, r["record_id"]) for r in rows]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        if record:
            writer.writerow({k: _cell(v) for k, v in record_row(record).items()})
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="pack-records.csv"'})


@app.get("/api/records/{record_id}")
def api_record(request: Request, record_id: str, download: bool = False):
    user = _api_user(request)
    if not user:
        return JSONResponse({"error": "unauthorised"}, status_code=401)
    with db().org(user["org"]) as cur:
        record = store.get_record(cur, record_id)
    if not record:
        return JSONResponse({"error": "not found"}, status_code=404)
    if download:  # exactly the hashed record, so the file can be verified on its own
        return Response(record.model_dump_json(indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{record.record_id}.json"'})
    return {**record.model_dump(mode="json"), "_hash_verified": verify(record)}


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__, "vision_model": settings.gemini_model,
            "vision_configured": bool(settings.gemini_api_key)}
