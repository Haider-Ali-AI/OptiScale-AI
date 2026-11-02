"""Fixed NVIDIA endpoint, bounded calls, private credentials and sanitized errors."""

import hashlib
import json
import os
import re
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone

from ads_optimizer.domain import DomainError

MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
MAX_RESPONSE = 128 * 1024
_call_lock = threading.Lock()
_verification = {}


def key_path(repo):
    return repo.root / "ai" / "nvidia-api-key"


def credential(repo):
    environment = os.environ.get("NVIDIA_API_KEY", "").strip()
    if environment:
        return environment, "environment"
    path = key_path(repo)
    return (path.read_text().strip(), "local_file") if path.exists() else ("", "missing")


def identity(repo, key):
    return str(repo.root.resolve()), hashlib.sha256(key.encode()).hexdigest()


def status(repo):
    key, source = credential(repo)
    verified = _verification.get(identity(repo, key), {})
    return {
        "provider": "NVIDIA",
        "model": MODEL,
        "configured": bool(key),
        "key_source": source,
        "verified": bool(verified.get("verified")),
        "checked_at": verified.get("checked_at"),
        "last_error": verified.get("last_error"),
    }


def save_key(repo, key):
    if os.environ.get("NVIDIA_API_KEY", "").strip():
        raise DomainError("The launch environment manages this key. Update NVIDIA_API_KEY there.")
    if not re.fullmatch(r"nvapi-[A-Za-z0-9_-]{20,250}", key):
        raise DomainError("Enter a valid NVIDIA API key beginning with nvapi-.")
    path = key_path(repo)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(key)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    _verification.pop(identity(repo, key), None)
    return status(repo)


def remove_key(repo):
    key, source = credential(repo)
    if source == "environment":
        raise DomainError("Remove NVIDIA_API_KEY from the launch environment to disconnect it.")
    key_path(repo).unlink(missing_ok=True)
    _verification.pop(identity(repo, key), None)
    return status(repo)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DomainError("NVIDIA redirected the request unexpectedly. Please retry later.", 502)


def complete(repo, system, user):
    key, _ = credential(repo)
    if not key:
        raise DomainError("Add a NVIDIA API key in AI Assistant before requesting an explanation.")
    if not _call_lock.acquire(blocking=False):
        raise DomainError("A NVIDIA request is already running. Wait before trying again.", 429)
    checked = datetime.now(timezone.utc).isoformat()
    try:
        body = json.dumps(
            {
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
                "top_p": 0.9,
                "max_tokens": 900,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
            }
        ).encode()
        request = urllib.request.Request(
            ENDPOINT,
            data=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
                raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError("oversized response")
            payload = json.loads(raw)
            # Deliberately ignore reasoning_content and tools; only final narrative is allowed.
            text = payload["choices"][0]["message"]["content"]
            if not isinstance(text, str) or not text.strip() or len(text) > 6000:
                raise ValueError("empty or invalid final content")
            if key in text or "<think>" in text or re.search(r"nvapi-[A-Za-z0-9_-]+", text):
                raise ValueError("unsafe provider content")
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise DomainError(
                    "NVIDIA rejected this key or account access. Replace or verify it."
                ) from None
            if error.code == 429:
                raise DomainError(
                    "NVIDIA's rate limit was reached. Wait and try again.", 429
                ) from None
            raise DomainError(
                "NVIDIA is temporarily unavailable. Your local reports still work.", 502
            ) from None
        except (OSError, TimeoutError, urllib.error.URLError):
            raise DomainError(
                "Could not reach NVIDIA within the timeout. Try again later.", 504
            ) from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise DomainError(
                "NVIDIA returned an unusable answer. No explanation was saved.", 502
            ) from None
        _verification[identity(repo, key)] = {"verified": True, "checked_at": checked}
        return text.strip()
    except DomainError as error:
        _verification[identity(repo, key)] = {
            "verified": False,
            "checked_at": checked,
            "last_error": error.message,
        }
        raise
    finally:
        _call_lock.release()
