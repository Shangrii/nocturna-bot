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
import time
from datetime import datetime, timezone

import requests

import config

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


def _entry_message_id(filename):
    """Extract the message-id segment from ``{YYYYMMDD}-{message.id}-{index}.webp``.

    Splits on ``-`` and returns the EXACT middle segment — never a substring — so a
    snowflake that merely shares a prefix (e.g. ``9876543210`` vs ``987654321``) does
    not collide (D-14).
    """
    parts = filename.split("-")
    if len(parts) < 3:
        return None
    return parts[1]


def _fetch_parent_sha(repo, branch):
    url = f"{_API}/repos/{repo}/git/ref/heads/{branch}"
    resp = _require(_http("get", url, "GET git/ref"), "GET git/ref")
    return resp.json()["object"]["sha"]


def _fetch_base_tree_sha(repo, parent_sha):
    url = f"{_API}/repos/{repo}/git/commits/{parent_sha}"
    resp = _require(_http("get", url, "GET git/commits"), "GET git/commits")
    return resp.json()["tree"]["sha"]


def _fetch_gallery(repo, branch):
    """GET the current ``gallery.json`` array; tolerates an empty file and a 404."""
    url = f"{_API}/repos/{repo}/contents/{config.WEBSITE_GALLERY_JSON}"
    resp = _http("get", url, "GET contents gallery.json", params={"ref": branch})
    if resp.status_code == 404:
        return []                              # not-yet-created gallery.json
    _require(resp, "GET contents gallery.json")
    raw = base64.b64decode(resp.json()["content"])
    text = raw.decode("utf-8").strip()
    return json.loads(text) if text else []


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


# ── retryable read-modify-commit-ref core ─────────────────────────────────────────
def _commit_with_retry(repo, branch, message, build_tree):
    """Run the ref-relative part of the sequence, rebuilding on a stale-ref conflict.

    ``build_tree(current_gallery)`` returns the tree-entry list to commit; it is called
    fresh on every attempt with a freshly fetched ``gallery.json`` so a concurrent
    commit's entries are merged rather than clobbered (D-18 / Pitfall 4).
    """
    last_status = None
    for attempt in range(_MAX_ATTEMPTS):
        parent_sha = _fetch_parent_sha(repo, branch)
        base_tree_sha = _fetch_base_tree_sha(repo, parent_sha)
        current = _fetch_gallery(repo, branch)
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
        updated = list(current) + new_entries    # append order is irrelevant (site sorts by date)
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
