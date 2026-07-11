"""Atomic cross-repo commit transport for the gallery publish pipeline (BOT-04).

Pure network/commit module: publishes image(s) + a ``gallery.json`` entry, or removes
a message's photos, as ONE commit against the website repo via the GitHub **Git Data
API** (blobs -> tree -> commit -> ref). It imports only stdlib + ``requests`` + ``config``
— no ``discord`` — so the whole read-modify-commit is unit-testable with HTTP mocked,
separate from the cog (05-03/05-04).

Why the Git Data API (not the Contents API): the Contents API commits one file per
request, which would split the image and ``gallery.json`` into two commits — two Pages
builds and a broken-tile window (violates D-16). The tree API commits both atomically
AND deletes files via ``"sha": null`` (which PyGithub cannot express cleanly), so it is
the only transport that satisfies both publish and removal.

The 7-step sequence (headers ``Authorization: Bearer <PAT>`` + ``Accept:
application/vnd.github+json``; repo/branch from ``config``):
  1. GET  /repos/{repo}/git/ref/heads/{branch}      -> parent commit sha
  2. GET  /repos/{repo}/git/commits/{parent_sha}    -> base tree sha
  3. GET  /repos/{repo}/contents/{gallery_json}      -> current array (tolerates [] and 404)
  4. POST /git/blobs (publish only, per image)        -> blob sha
  5. POST /git/trees {base_tree, tree:[...]}          -> new tree sha
  6. POST /git/commits {message, tree, parents}       -> new commit sha
  7. PATCH /git/refs/heads/{branch} {sha}             -> move branch (PAT push -> deploy)

Design choices (D-18 discretion):
  * The whole read-modify-commit-ref runs under a module-level ``asyncio.Lock`` so
    concurrent approvals never race the same parent sha (single-process bot).
  * On a stale-ref conflict (HTTP 409/422 from the ref PATCH) the sequence re-fetches
    the ref and rebuilds — up to ``_MAX_ATTEMPTS`` (4) tries with exponential backoff
    (``_BACKOFF_BASE`` 0.5s -> 0.5/1.0/2.0s). When retries are exhausted (or a non-retry
    HTTP error occurs) a typed ``GitHubPublishError`` is raised for the cog to surface
    (D-19: persistent error reply + ⚠️).
  * The PAT is read from ``config.GITHUB_PAT`` at call time and only ever placed in the
    ``Authorization`` header. Nothing here logs the header/token — only endpoint labels
    and status codes reach the logs (T-05-04).

The blocking ``requests`` work is dispatched off the event loop with
``asyncio.to_thread`` so Discord handling is never blocked; callers simply ``await``.
"""

import asyncio
import base64
import json
import logging
import re
import time
from datetime import datetime, timezone

import requests

import config
from core import store_sync

log = logging.getLogger(__name__)

_API = "https://api.github.com"
_MODE = "100644"                    # regular non-executable blob
_MAX_ATTEMPTS = 4                   # ref-conflict retries (D-18)
_BACKOFF_BASE = 0.5                 # seconds; exponential: 0.5, 1.0, 2.0 ...
_RETRY_STATUSES = frozenset({409, 422})   # "ref moved / not a fast forward"
# (connect, read) seconds — requests has NO default timeout, and every commit runs
# under _commit_lock: one black-holed connection would otherwise hold the lock forever
# and silently disable the entire publish pipeline (CR-02). Blob POSTs of ~1-2 MB
# images need generous read headroom.
_TIMEOUT = (10, 60)

# Serializes the whole read-modify-commit so concurrent publishes don't race the ref.
# The single-process bot uses one event loop; uncontended acquires take the fast path
# and never bind a loop, so this is also safe across the test suite's asyncio.run calls.
_commit_lock = asyncio.Lock()


class GitHubPublishError(RuntimeError):
    """Raised when a publish/removal commit cannot be completed (after retries).

    The cog catches this to drive the D-19 failure UX (persistent reply + ⚠️).
    """


# ── low-level helpers ─────────────────────────────────────────────────────────────
def _headers():
    # PAT read at call time (so config/.env changes and tests take effect); never logged.
    return {
        "Authorization": f"Bearer {config.GITHUB_PAT}",
        "Accept": "application/vnd.github+json",
    }


def _ok(resp):
    return 200 <= resp.status_code < 300


def _require(resp, what):
    """Log the endpoint + status (never the token) and raise on a non-2xx response."""
    log.debug("github %s -> HTTP %s", what, resp.status_code)
    if not _ok(resp):
        raise GitHubPublishError(f"{what} failed: HTTP {resp.status_code}")
    return resp


def _http(method, url, what, headers=None, **kw):
    """Issue one HTTP request, keeping the typed-error contract airtight (CR-01).

    ``requests`` raises untyped ``RequestException`` subclasses on DNS failures,
    refused/reset connections and timeouts — the cog only catches
    ``GitHubPublishError``, so every transport call is routed here to convert
    network-level failures into the typed error the D-19 failure UX depends on.
    Only the exception CLASS NAME is interpolated (never ``str(exc)``) so a URL or
    header value can never leak into the error text or the logs.

    Every call carries an explicit ``_TIMEOUT`` (CR-02): a timeout expiry raises
    ``requests.Timeout``, which the wrapper converts to ``GitHubPublishError`` —
    releasing ``_commit_lock`` and triggering the ⚠️ retry UX instead of hanging.
    """
    kw.setdefault("timeout", _TIMEOUT)
    try:
        return getattr(requests, method)(url, headers=headers or _headers(), **kw)
    except requests.RequestException as exc:
        raise GitHubPublishError(
            f"{what} failed: network error ({exc.__class__.__name__})") from exc


# The exact D-14 bot filename shape: {YYYYMMDD}-{msgID}-{index}.webp — nothing else.
# Single source of truth for the parser (WR-06); cogs/gallery.py imports it from here.
_BOT_FILE_RE = re.compile(r"^\d{8}-(\d+)-\d+\.webp$")


def _entry_message_id(filename):
    """The ``{msgID}`` segment of the EXACT bot filename shape, or ``None`` (WR-06).

    Only ``{YYYYMMDD}-{msgID}-{index}.webp`` parses — sample or manually-committed
    files (any other name) return ``None``, so publish dedupe and DELETION can never
    match them. The full-segment match also means a snowflake that merely shares a
    prefix (``9876543210`` vs ``987654321``) cannot collide (D-14).
    """
    match = _BOT_FILE_RE.match(filename or "")
    return match.group(1) if match else None


def _fetch_parent_sha(repo, branch):
    url = f"{_API}/repos/{repo}/git/ref/heads/{branch}"
    resp = _require(_http("get", url, "GET git/ref"), "GET git/ref")
    return resp.json()["object"]["sha"]


def _fetch_base_tree_sha(repo, parent_sha):
    url = f"{_API}/repos/{repo}/git/commits/{parent_sha}"
    resp = _require(_http("get", url, "GET git/commits"), "GET git/commits")
    return resp.json()["tree"]["sha"]


def _fetch_json(repo, branch, path):
    """GET the current JSON array at ``path``; tolerates an empty file and a 404.

    The single generic reader for both transports (gallery + reviews). Files between
    1 MB and 100 MB come back from the Contents API with ``"content": "", "encoding":
    "none"`` — mistaking that for an empty array would make the next publish rewrite the
    file with ONLY the new entries, silently wiping every existing entry (WR-01). When
    the inline content is unreadable the array is re-fetched via the raw media type
    instead; if THAT fails, the typed error propagates — never an empty list.
    """
    url = f"{_API}/repos/{repo}/contents/{path}"
    resp = _http("get", url, "GET contents json", params={"ref": branch})
    if resp.status_code == 404:
        return []                              # not-yet-created file
    _require(resp, "GET contents json")
    data = resp.json()
    if data.get("encoding") == "none" or (data.get("size", 0) > 0 and not data.get("content")):
        raw_resp = _http(
            "get", url, "GET contents json (raw)",
            headers={**_headers(), "Accept": "application/vnd.github.raw+json"},
            params={"ref": branch})
        _require(raw_resp, "GET contents json (raw)")
        text = raw_resp.text.strip()
    else:
        raw = base64.b64decode(data.get("content", ""))
        text = raw.decode("utf-8").strip()
    # Normalize JSON-shape failures into the typed error (WR-04): a malformed file
    # (manual edit, partial write) or a non-array body must drive the same ⚠️ retry UX
    # as any other transport failure instead of escaping as JSONDecodeError/AttributeError.
    try:
        parsed = json.loads(text) if text else []
    except ValueError as exc:
        raise GitHubPublishError(
            f"GET contents json failed: invalid JSON ({exc.__class__.__name__})") from exc
    if not isinstance(parsed, list):
        raise GitHubPublishError("GET contents json failed: expected a JSON array")
    return parsed


def _fetch_gallery(repo, branch):
    """GET the current ``gallery.json`` array (backward-compatible thin wrapper).

    Preserves the gallery transport's original signature/behavior byte-for-byte by
    delegating to the generic ``_fetch_json`` with the gallery JSON path.
    """
    return _fetch_json(repo, branch, config.WEBSITE_GALLERY_JSON)


def _fetch_json_object(repo, branch, path):
    """GET the current JSON OBJECT at ``path`` (the store variant of ``_fetch_json``).

    ``store.json`` is ``{"_comment": "<schema doc>", "products": [...]}`` — an OBJECT, not
    an array — so the generic ``_fetch_json`` (which RAISES on a dict body to protect the
    gallery/reviews array contract) cannot read it. This dict-expecting sibling shares the
    exact content / raw-media fallback (WR-01: a 1-100 MB file comes back with ``encoding:
    none`` and must be re-fetched raw, never mistaken for an empty file) and normalizes every
    JSON-shape failure into the typed ``GitHubPublishError`` (WR-04) so the same ⚠️/retry
    discipline applies. A body that is not a dict containing ``products`` (an array, or a
    dict missing the key) is rejected at the transport boundary — otherwise ``build_tree``
    would silently drop ``_comment`` or ``AttributeError`` on the missing list.

    ``_fetch_json`` itself is left UNTOUCHED so gallery/reviews keep their array contract.
    """
    url = f"{_API}/repos/{repo}/contents/{path}"
    resp = _http("get", url, "GET contents json", params={"ref": branch})
    if resp.status_code == 404:
        # store.json is a shipped, staff-owned file — a 404 is never "empty storefront".
        raise GitHubPublishError("store.json: expected an object with a 'products' key")
    _require(resp, "GET contents json")
    data = resp.json()
    if data.get("encoding") == "none" or (data.get("size", 0) > 0 and not data.get("content")):
        raw_resp = _http(
            "get", url, "GET contents json (raw)",
            headers={**_headers(), "Accept": "application/vnd.github.raw+json"},
            params={"ref": branch})
        _require(raw_resp, "GET contents json (raw)")
        text = raw_resp.text.strip()
    else:
        raw = base64.b64decode(data.get("content", ""))
        text = raw.decode("utf-8").strip()
    try:
        parsed = json.loads(text) if text else None
    except ValueError as exc:
        raise GitHubPublishError(
            f"GET contents json failed: invalid JSON ({exc.__class__.__name__})") from exc
    if not isinstance(parsed, dict) or "products" not in parsed:
        raise GitHubPublishError("store.json: expected an object with a 'products' key")
    return parsed


def _fetch_store(repo, branch, path):
    """GET the current ``store.json`` OBJECT, preserving ``_comment`` + any staff keys.

    Thin wrapper over ``_fetch_json_object`` (the object-shape guard lives there). Returns
    the WHOLE dict so ``build_tree`` can rewrite ``products`` while carrying every other
    top-level key (``_comment`` schema doc, staff-added notes) through the commit unchanged.
    """
    return _fetch_json_object(repo, branch, path)


def _create_blob(repo, raw_bytes):
    url = f"{_API}/repos/{repo}/git/blobs"
    payload = {"content": base64.b64encode(raw_bytes).decode("ascii"), "encoding": "base64"}
    resp = _require(_http("post", url, "POST git/blobs", json=payload), "POST git/blobs")
    return resp.json()["sha"]


def _create_tree(repo, base_tree_sha, tree_entries):
    url = f"{_API}/repos/{repo}/git/trees"
    payload = {"base_tree": base_tree_sha, "tree": tree_entries}
    resp = _require(_http("post", url, "POST git/trees", json=payload), "POST git/trees")
    return resp.json()["sha"]


def _create_commit(repo, message, tree_sha, parent_sha):
    url = f"{_API}/repos/{repo}/git/commits"
    payload = {"message": message, "tree": tree_sha, "parents": [parent_sha]}
    resp = _require(_http("post", url, "POST git/commits", json=payload), "POST git/commits")
    return resp.json()["sha"]


def _update_ref(repo, branch, commit_sha):
    """PATCH the branch to the new commit. Returns the raw response so the retry loop
    can distinguish a stale-ref conflict (409/422) from a hard failure."""
    url = f"{_API}/repos/{repo}/git/refs/heads/{branch}"
    return _http("patch", url, "PATCH git/refs", json={"sha": commit_sha})


def _serialize_gallery(array):
    # Phase 4 shape: 2-space indent, non-ASCII kept readable (captions escape correctly).
    return json.dumps(array, ensure_ascii=False, indent=2)


# The reviews transport shares the exact same JSON shape (2-space indent, non-ASCII kept
# readable so review text renders correctly). The body is already generic, so this is a
# pure alias — no behavior change for the gallery.
_serialize_json = _serialize_gallery


# ── retryable read-modify-commit-ref core ─────────────────────────────────────────
def _commit_with_retry(repo, branch, message, build_tree, fetch=None):
    """Run the ref-relative part of the sequence, rebuilding on a stale-ref conflict.

    ``build_tree(current)`` returns the tree-entry list to commit; it is called fresh on
    every attempt with the freshly fetched current array so a concurrent commit's entries
    are merged rather than clobbered (D-18 / Pitfall 4).

    ``fetch`` is the callable that returns the current array on each attempt. It defaults
    to the gallery fetch so existing gallery callers keep identical behavior; the reviews
    transport passes ``fetch=lambda: _fetch_json(repo, branch, reviews_path)`` to point
    the same retry core at ``reviews.json`` (backward-compatible generalization).
    """
    fetch = fetch or (lambda: _fetch_gallery(repo, branch))
    last_status = None
    for attempt in range(_MAX_ATTEMPTS):
        parent_sha = _fetch_parent_sha(repo, branch)
        base_tree_sha = _fetch_base_tree_sha(repo, parent_sha)
        current = fetch()
        tree_entries = build_tree(current)
        new_tree_sha = _create_tree(repo, base_tree_sha, tree_entries)
        commit_sha = _create_commit(repo, message, new_tree_sha, parent_sha)

        resp = _update_ref(repo, branch, commit_sha)
        if _ok(resp):
            log.info("github PATCH git/refs -> HTTP %s (attempt %d)", resp.status_code, attempt + 1)
            return commit_sha

        last_status = resp.status_code
        if resp.status_code in _RETRY_STATUSES and attempt + 1 < _MAX_ATTEMPTS:
            backoff = _BACKOFF_BASE * (2 ** attempt)
            log.warning("github stale ref (HTTP %s); retry %d/%d after %.1fs",
                        resp.status_code, attempt + 1, _MAX_ATTEMPTS, backoff)
            time.sleep(backoff)
            continue
        if resp.status_code not in _RETRY_STATUSES:
            raise GitHubPublishError(f"PATCH git/refs failed: HTTP {resp.status_code}")

    raise GitHubPublishError(
        f"PATCH git/refs failed after {_MAX_ATTEMPTS} attempts (last HTTP {last_status})")


# ── sync publish/remove (run off the event loop via asyncio.to_thread) ─────────────
def _publish_sync(message_id, entries, date):
    repo = config.WEBSITE_REPO
    branch = config.WEBSITE_BRANCH
    image_dir = config.WEBSITE_IMAGE_DIR.rstrip("/")
    gallery_path = config.WEBSITE_GALLERY_JSON

    if not entries:
        return {"committed": False, "commit_sha": None, "count": 0, "files": []}

    # Create image blobs once (content-addressed, independent of the ref -> survives
    # retries) and build the gallery.json entries in the locked Phase 4 shape.
    blob_tree = []
    new_entries = []
    files = []
    for raw, width, height, filename, caption in entries:
        blob_sha = _create_blob(repo, raw)
        blob_tree.append({
            "path": f"{image_dir}/{filename}",
            "mode": _MODE,
            "type": "blob",
            "sha": blob_sha,
        })
        entry = {"file": filename}
        if caption:                              # omit the key entirely when empty (never "")
            entry["caption"] = caption
        entry["width"] = width
        entry["height"] = height
        entry["date"] = date
        new_entries.append(entry)
        files.append(filename)

    message = f"gallery: publish {len(entries)} photos (discord msg {message_id})"

    def build_tree(current):
        # Idempotent commit (WR-02): drop any existing entries for THIS message before
        # appending, so a double-✅ race or a re-✅ after a lost 🟢 marker republishes
        # cleanly instead of duplicating tiles. Non-bot filenames parse to None and are
        # always kept. Append order is irrelevant (site sorts by date).
        target = str(message_id)
        kept = [e for e in current if _entry_message_id(e.get("file", "")) != target]
        updated = kept + new_entries
        gallery_entry = {
            "path": gallery_path,
            "mode": _MODE,
            "type": "blob",
            "content": _serialize_gallery(updated),
        }
        return blob_tree + [gallery_entry]

    commit_sha = _commit_with_retry(repo, branch, message, build_tree)
    return {"committed": True, "commit_sha": commit_sha, "count": len(entries), "files": files}


def _remove_sync(message_id):
    repo = config.WEBSITE_REPO
    branch = config.WEBSITE_BRANCH
    image_dir = config.WEBSITE_IMAGE_DIR.rstrip("/")
    gallery_path = config.WEBSITE_GALLERY_JSON
    target = str(message_id)

    # No-op guard: derive the message's files statelessly from the current gallery.json.
    # If none match, do nothing — never create an empty commit (T-05-15).
    current = _fetch_gallery(repo, branch)
    removed_files = [e["file"] for e in current
                     if _entry_message_id(e.get("file", "")) == target]
    if not removed_files:
        return {"committed": False, "commit_sha": None, "count": 0, "files": []}

    message = f"gallery: remove {len(removed_files)} photos (discord msg {message_id})"

    def build_tree(cur):
        keep = [e for e in cur if _entry_message_id(e.get("file", "")) != target]
        gallery_entry = {
            "path": gallery_path,
            "mode": _MODE,
            "type": "blob",
            "content": _serialize_gallery(keep),
        }
        deletes = [{
            "path": f"{image_dir}/{name}",
            "mode": _MODE,
            "type": "blob",
            "sha": None,                         # sha:null DELETES the file from the tree
        } for name in removed_files]
        return [gallery_entry] + deletes

    commit_sha = _commit_with_retry(repo, branch, message, build_tree)
    return {"committed": True, "commit_sha": commit_sha,
            "count": len(removed_files), "files": removed_files}


# ── public async API ───────────────────────────────────────────────────────────────
async def publish_message(message_id, entries, date=None):
    """Publish a message's images + gallery.json entries as ONE atomic commit.

    Args:
        message_id: the Discord message snowflake (drives the D-17 commit message).
        entries: list of ``(webp_bytes, width, height, filename, caption)`` — one per
            optimized image. ``caption`` "" omits the key; ``filename`` is the
            bot-generated ``{date}-{msgID}-{index}.webp`` (numeric only, no user text).
        date: ISO 8601 string written to every entry's ``date`` (defaults to now UTC).

    Returns:
        ``{"committed": bool, "commit_sha": str|None, "count": int, "files": [str]}``.

    Raises:
        GitHubPublishError: transport failed after the retry budget (cog surfaces D-19).
    """
    if date is None:
        date = datetime.now(timezone.utc).isoformat()
    async with _commit_lock:
        return await asyncio.to_thread(_publish_sync, message_id, entries, date)


async def remove_message(message_id):
    """Remove a message's published photos + gallery.json entries as ONE atomic commit.

    Files are derived statelessly from the ``{msgID}`` filename segment (D-14); a
    message with no matching entries is a no-op (no empty commit).

    Returns:
        ``{"committed": bool, "commit_sha": str|None, "count": int, "files": [str]}``.

    Raises:
        GitHubPublishError: transport failed after the retry budget.
    """
    async with _commit_lock:
        return await asyncio.to_thread(_remove_sync, message_id)


# ── reviews transport (Fase 7): single reviews.json blob, no image blobs ────────────
def _publish_review_sync(entry):
    """Commit ONE ``reviews.json`` blob with ``entry`` appended, deduped by id.

    Reviews have no images — the commit is a pure read-modify-write of ONE JSON file.
    ``entry`` is a ready-built ``{"id", "author", "text", "date"}`` dict (the cog resolves
    author/anonymity; the transport stays dumb and writes what it is handed — ``author:
    null`` is preserved verbatim). Idempotent: any existing entry with the same ``id`` is
    dropped before appending, so a re-✅ republishes cleanly instead of duplicating.
    """
    repo = config.WEBSITE_REPO
    branch = config.WEBSITE_BRANCH
    reviews_path = config.WEBSITE_REVIEWS_JSON
    target = str(entry["id"])

    message = f"reviews: publish review (discord msg {entry['id']})"

    def build_tree(current):
        kept = [e for e in current if str(e.get("id")) != target]
        updated = kept + [entry]
        review_entry = {
            "path": reviews_path,
            "mode": _MODE,
            "type": "blob",
            "content": _serialize_json(updated),
        }
        return [review_entry]

    commit_sha = _commit_with_retry(
        repo, branch, message, build_tree,
        fetch=lambda: _fetch_json(repo, branch, reviews_path))
    return {"committed": True, "commit_sha": commit_sha, "count": 1}


def _remove_review_sync(message_id):
    """Commit ONE ``reviews.json`` blob without the ``message_id`` entry.

    Keyed by the discord message id (no filename parsing — reviews have no images).
    A message with no matching entry is a no-op: no empty commit is created.
    """
    repo = config.WEBSITE_REPO
    branch = config.WEBSITE_BRANCH
    reviews_path = config.WEBSITE_REVIEWS_JSON
    target = str(message_id)

    # No-op guard: if nothing matches, do nothing — never create an empty commit.
    current = _fetch_json(repo, branch, reviews_path)
    keep = [e for e in current if str(e.get("id")) != target]
    if len(keep) == len(current):
        return {"committed": False, "commit_sha": None, "count": 0}

    message = f"reviews: remove review (discord msg {message_id})"

    def build_tree(cur):
        kept = [e for e in cur if str(e.get("id")) != target]
        review_entry = {
            "path": reviews_path,
            "mode": _MODE,
            "type": "blob",
            "content": _serialize_json(kept),
        }
        return [review_entry]

    commit_sha = _commit_with_retry(
        repo, branch, message, build_tree,
        fetch=lambda: _fetch_json(repo, branch, reviews_path))
    return {"committed": True, "commit_sha": commit_sha, "count": 1}


async def publish_review(entry):
    """Publish ONE review to ``reviews.json`` as a single atomic commit.

    Args:
        entry: a ready-built ``{"id", "author", "text", "date"}`` dict. ``id`` is the
            Discord message snowflake (drives the commit message + dedupe); ``author`` is
            the display name or ``None`` for anonymous (preserved verbatim, never derived
            or logged here).

    Returns:
        ``{"committed": bool, "commit_sha": str|None, "count": int}``.

    Raises:
        GitHubPublishError: transport failed after the retry budget (cog surfaces ⚠️).
    """
    async with _commit_lock:
        return await asyncio.to_thread(_publish_review_sync, entry)


async def remove_review(message_id):
    """Remove a review from ``reviews.json`` as a single atomic commit.

    Keyed by the Discord message id; a message with no matching entry is a no-op
    (no empty commit).

    Returns:
        ``{"committed": bool, "commit_sha": str|None, "count": int}``.

    Raises:
        GitHubPublishError: transport failed after the retry budget.
    """
    async with _commit_lock:
        return await asyncio.to_thread(_remove_review_sync, message_id)


# ── store transport (Fase 9): OBJECT-aware store.json, _comment preserved ────────────
def _sync_store_sync(products, message=None):
    """Commit the whole ``products`` list into ``store.json``, mutating ONLY ``products``.

    ``store.json`` is an OBJECT ``{"_comment": ..., "products": [...]}`` (the load-bearing
    divergence from gallery/reviews — RESEARCH Pattern 2 / Pitfall 1). ``build_tree`` copies
    the current dict and replaces only ``current["products"]`` so ``_comment`` (the staff-
    facing schema doc) and any staff-added top-level keys survive every sync (T-09-10, D-12).

    No-op guard (T-09-12 / D-06 / Pitfall 2 — every commit is one Pages rebuild): if the new
    products list already equals the current one, short-circuit to ``committed: False`` with
    NO ref PATCH. The 09-05 caller only invokes this when the merge reports a change; this is
    a defensive second gate so a redundant call never triggers an empty commit or a rebuild.

    Concurrent-attach re-graft (WR-01 / gap #1 / T-09-07-01): ``build_tree`` receives the
    FRESHLY-fetched store on every (re)try and re-grafts the staff-owned key set from the
    fresh entry (matched by ``checkoutUrl``) onto each pre-computed product before writing.
    This closes the race where a ``/tienda medios`` attach (JINXXY_DEPLOY.md tells staff to
    run one per product right after the first sync) lands inside the commit window: without
    the graft the stale merged list would silently revert the staff ``images``/``description``
    (STORE-SYNC-01/02). Sync-owned fields still come from the pre-computed list so genuine
    Jinxxy changes propagate; a product absent from the fresh fetch (a new product) is written
    verbatim with no graft.
    """
    repo = config.WEBSITE_REPO
    branch = config.WEBSITE_BRANCH
    store_path = config.WEBSITE_STORE_JSON
    new_products = list(products)

    # Defensive no-op: compare against the live store before touching the ref.
    current = _fetch_store(repo, branch, store_path)
    if current.get("products") == new_products:
        return {"committed": False, "commit_sha": None, "count": 0}

    msg = message or f"store: sync {len(new_products)} products"

    # Staff-owned key set carried from the fresh store, NEVER from the merged list:
    # store_sync.STAFF_OWNED (id, description, images, featured, license, details, updates,
    # storefronts) PLUS "editor" (D-09: staff-editable, carried through, never re-sourced).
    _GRAFT_KEYS = store_sync.STAFF_OWNED + ("editor",)

    def build_tree(cur):
        updated = dict(cur)                       # preserve _comment + unknown top-level keys
        # Re-graft staff-owned fields from the FRESH fetch, keyed by checkoutUrl (WR-01).
        fresh = {p["checkoutUrl"]: p for p in cur.get("products", [])
                 if isinstance(p, dict) and p.get("checkoutUrl")}
        grafted = []
        for entry in new_products:
            merged = dict(entry)                  # sync-owned fields stay from the merged list
            match = fresh.get(entry.get("checkoutUrl")) if isinstance(entry, dict) else None
            if match is not None:
                for key in _GRAFT_KEYS:
                    if key in match:              # only graft keys present in the fresh entry
                        merged[key] = match[key]
            grafted.append(merged)
        updated["products"] = grafted             # ONLY products changes
        return [{
            "path": store_path,
            "mode": _MODE,
            "type": "blob",
            "content": _serialize_json(updated),
        }]

    commit_sha = _commit_with_retry(
        repo, branch, msg, build_tree,
        fetch=lambda: _fetch_store(repo, branch, store_path))
    return {"committed": True, "commit_sha": commit_sha, "count": len(new_products)}


def _attach_store_media_sync(checkout_url, media, description):
    """Commit staff-supplied image blobs + ``images``/``description`` in ONE commit (D-15).

    ``images`` and ``description`` are 100% staff-owned (D-15) — the sync merge NEVER writes
    them; this is their only write path. ``media`` is a list of ``(webp_bytes, filename)``:
    each becomes a blob under ``{WEBSITE_STORE_IMAGE_DIR}/{filename}`` (default ``public/store``)
    and the matched product's ``images`` is set to the site-relative ``/store/{filename}``
    list. The image blobs AND the ``store.json`` edit ride ONE tree -> ONE commit (mirrors the
    gallery ``_publish_sync`` mixed blob+JSON shape) so a tile never renders against a
    not-yet-committed image.

    Matched by ``checkoutUrl`` (the D-13 cross-repo link key). A ``checkout_url`` matching no
    product RAISES — never a silent no-op that would discard the staff's uploaded work.
    ``_comment`` and every other product pass through byte-for-byte (T-09-10). Passing only
    ``media`` leaves ``description`` untouched and vice-versa.
    """
    repo = config.WEBSITE_REPO
    branch = config.WEBSITE_BRANCH
    store_path = config.WEBSITE_STORE_JSON
    image_dir = config.WEBSITE_STORE_IMAGE_DIR.rstrip("/")
    media = list(media)

    # Image blobs are content-addressed (independent of the ref) so they survive retries;
    # create them once, then reference their shas from the (rebuildable) tree.
    blob_tree = []
    image_paths = []
    for raw, filename in media:
        blob_sha = _create_blob(repo, raw)
        blob_tree.append({
            "path": f"{image_dir}/{filename}",
            "mode": _MODE,
            "type": "blob",
            "sha": blob_sha,
        })
        image_paths.append(f"/store/{filename}")           # site-relative, per the schema

    message = f"store: attach media to {checkout_url}"

    def build_tree(cur):
        updated = dict(cur)                                # preserve _comment + unknown keys
        products = [dict(p) for p in cur.get("products", [])]
        match = next((p for p in products
                      if p.get("checkoutUrl") == checkout_url), None)
        if match is None:
            raise GitHubPublishError(
                f"store.json: no product with checkoutUrl {checkout_url} to attach media to")
        if media:
            match["images"] = image_paths                  # only when images were supplied
        if description is not None:
            match["description"] = description              # only when a description was supplied
        updated["products"] = products
        store_entry = {
            "path": store_path,
            "mode": _MODE,
            "type": "blob",
            "content": _serialize_json(updated),
        }
        return blob_tree + [store_entry]

    commit_sha = _commit_with_retry(
        repo, branch, message, build_tree,
        fetch=lambda: _fetch_store(repo, branch, store_path))
    return {"committed": True, "commit_sha": commit_sha,
            "count": len(media), "files": [fn for _, fn in media]}


async def sync_store(products, *, message=None):
    """Sync the full ``products`` list into ``store.json`` as ONE atomic commit.

    Args:
        products: the merged product list to write. ``_comment`` and any staff-added
            top-level keys are preserved; only ``products`` is replaced.
        message: optional commit message override (defaults to a "store: sync N products").

    Returns:
        ``{"committed": bool, "commit_sha": str|None, "count": int}``. An unchanged list is
        a no-op (``committed: False``) — no empty commit, no Pages rebuild.

    Raises:
        GitHubPublishError: transport failed after the retry budget, or the fetched
            ``store.json`` is not an object with a ``products`` key.
    """
    async with _commit_lock:
        return await asyncio.to_thread(_sync_store_sync, products, message)


async def attach_store_media(checkout_url, media=(), description=None):
    """Attach staff-supplied images + description to one product as ONE atomic commit.

    Args:
        checkout_url: the product's ``checkoutUrl`` (the D-13 link key) to attach to.
        media: iterable of ``(webp_bytes, filename)`` — each is committed as a blob under
            ``WEBSITE_STORE_IMAGE_DIR`` and referenced as ``/store/{filename}``. Empty leaves
            ``images`` untouched.
        description: an ``{"es", "en"}`` dict, or ``None`` to leave ``description`` untouched.

    Returns:
        ``{"committed": bool, "commit_sha": str|None, "count": int, "files": [str]}``.

    Raises:
        GitHubPublishError: no product matches ``checkout_url``, or the transport failed
            after the retry budget.
    """
    async with _commit_lock:
        return await asyncio.to_thread(
            _attach_store_media_sync, checkout_url, media, description)
