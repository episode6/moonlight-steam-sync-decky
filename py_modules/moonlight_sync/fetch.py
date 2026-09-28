"""The update downloader (update spec 3.12.3): one URL to one file, verified.

    python3 -I fetch.py [--sha256 HEX] [--max-bytes N] [--timeout S]
                        [--allow-file] [--] URL DEST

A script, not a module of the backend. The backend runs it with the system
interpreter (``Backend._fetch``), whose OpenSSL reads SteamOS's CA store;
Decky's own PyInstaller interpreter does not (spec 2.5). So it imports the
standard library only, nothing from ``moonlight_sync`` or beside it, and
runs under Python 3.11 (the CLI's floor). ``-I`` keeps this file's own
directory off ``sys.path``, so no module next to it can shadow a standard
one. ``tests/test_hard_rules.py`` holds both directions: this file imports
nothing of the package, and nothing under ``py_modules`` or ``main.py``
imports this file.

What it guarantees, in order:

1. **The URL** passes :func:`check_url`: ``https``, the host ``github.com``
   or one under ``.githubusercontent.com``, port 443, no user info. The same
   function judges every redirect target *before* the redirect is followed
   (:class:`RedirectGuard`), and at most five redirects are followed. With
   ``--allow-file`` (the tests' seam; the backend passes it only when its
   ``Source`` says so, which ``main.py`` never does) a ``file:///`` URL is
   accepted as the first URL; a redirect can never lead to one.
2. **The opener** can open nothing else: no ``http``, ``ftp`` or ``data``
   handler, no proxy from the environment, TLS verified with
   ``ssl.create_default_context()``.
3. **The body** is streamed to ``DEST + ".part"`` (created afresh, mode
   0600, never through a symlink), hashed and counted as it goes, and
   ``os.replace``d onto ``DEST`` only when it is complete, within
   ``--max-bytes`` and, with ``--sha256``, the expected bytes. On any
   failure the part file is removed and ``DEST`` is exactly as it was.
4. **The output** is exactly one JSON line on stdout and exit 0, whatever
   happened, an uncaught exception and bad arguments included::

       {"ok": true, "status": 200, "bytes": 794721, "sha256": "<hex>"}
       {"ok": false, "error": "<code>", "status": 404, "message": "..."}

   ``error`` is one of ``bad-url``, ``http``, ``network``, ``too-large``,
   ``hash-mismatch``, ``io``. ``status`` is the HTTP status when there was
   one (200 for a ``file://`` success, 404 for a missing file there), else
   ``null``. ``message`` is built from a URL's scheme, host and path only:
   GitHub's asset redirects carry a signed query string, which never
   reaches the output. Nothing is ever written to stderr.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "moonlight-sync"
CHUNK = 64 * 1024
MAX_REDIRECTS = 5
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MAX_BYTES = 32 * 1024 * 1024
#: Longer than any URL this plugin builds or GitHub redirects to.
MAX_URL_LENGTH = 4096
ALLOWED_HOST = "github.com"
ALLOWED_SUFFIX = ".githubusercontent.com"
#: A host as this script accepts one: lower-case letters, digits, dots and
#: hyphens (``urlsplit``'s ``hostname`` is already lower-cased).
HOST_RE = re.compile(r"[a-z0-9.-]+")
HEX64_RE = re.compile(r"[0-9a-fA-F]{64}")
#: A URL inside free text, for :func:`scrub`.
URL_IN_TEXT_RE = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://[^\s?#'\"<>]*)[?#][^\s'\"<>]*")


class Refused(Exception):
    """A URL this script will not open (``bad-url``).

    Deliberately not an ``OSError``: urllib wraps ``OSError``s raised while
    it opens a connection into ``URLError``, which would read as
    ``network``. The message never holds a query string.
    """


class Failed(Exception):
    """A failure with its output code; ``status`` is the HTTP status, if any."""

    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# the URL check: the one function for the first URL and every redirect


def safe_url(url: str) -> str:
    """``url`` with its query, fragment and user info dropped: what a message
    may show. Never raises."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port is not None else ""
    except ValueError:
        return "(an unreadable URL)"
    return f"{parts.scheme}://{host}{port}{parts.path}"


def scrub(text: str) -> str:
    """``text`` with the query and fragment of every URL in it removed: the
    last step before a message is printed, whatever built it."""
    return URL_IN_TEXT_RE.sub(r"\1", text)


def _refuse(url: str, why: str) -> Refused:
    return Refused(f"refused {safe_url(url)}: {why}")


def check_url(url: object, *, allow_file: bool = False) -> None:
    """Raise :class:`Refused` unless ``url`` may be opened.

    ``allow_file`` admits ``file:///`` URLs and nothing else: every other
    rule stands with it. A redirect is always checked with
    ``allow_file=False`` (:class:`RedirectGuard`).
    """
    if not isinstance(url, str) or not url:
        raise Refused("refused: no URL")
    if len(url) > MAX_URL_LENGTH:
        raise Refused("refused: the URL is too long")
    # Before parsing: urlsplit strips some whitespace and control characters
    # and browsers read a backslash as a slash, so a URL holding any of them
    # could mean one thing to this check and another to the connection.
    # Printable ASCII only; a space is refused with the rest.
    for char in url:
        if not ("!" <= char <= "~") or char == "\\":
            raise Refused("refused: the URL holds a space, a control character or a backslash")
    if allow_file and url.startswith("file:"):
        _check_file_url(url)
        return
    # The scheme exactly as written, lower case: an http URL (and so an
    # https -> http downgrade by redirect) is refused here.
    if not url.startswith("https://"):
        raise _refuse(url, "only https URLs are opened")
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise _refuse(url, "the URL does not parse") from None
    if "@" in parts.netloc:
        raise _refuse(url, "a URL with user info")
    if port is not None and port != 443:
        raise _refuse(url, "a port other than 443")
    if not host:
        raise _refuse(url, "no host")
    if host.endswith(".") or not HOST_RE.fullmatch(host) or "" in host.split("."):
        raise _refuse(url, "not a plain host name")
    # The netloc is the host itself (any case) or the host and :443, nothing
    # else: no brackets, no empty port, nothing urlsplit would have dropped.
    if parts.netloc.lower() not in (host, f"{host}:443"):
        raise _refuse(url, "not a plain host name")
    # The leading dot matters: `evilgithubusercontent.com` is not GitHub's.
    if host != ALLOWED_HOST and not host.endswith(ALLOWED_SUFFIX):
        raise _refuse(url, "not a GitHub download host")


def _check_file_url(url: str) -> None:
    """``file:///<absolute path>``, with no host, query or fragment."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "file" or not url.startswith("file:///"):
        raise Refused("refused: a file URL must be file:///<path>")
    if parts.netloc or parts.query or parts.fragment:
        raise Refused("refused: a file URL has no host, query or fragment")


# ---------------------------------------------------------------------------
# the opener


class RedirectGuard(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to a URL :func:`check_url` accepts, five at most.

    urllib calls ``http_error_30x`` with the response, and it calls
    ``redirect_request`` for the new request before it opens anything, so a
    refusal raised from either means no connection is made to the target.
    """

    # The base class's own limits (10 redirects, 4 visits of one URL), set
    # explicitly rather than trusted: redirect_request counts on its own.
    max_redirections = MAX_REDIRECTS
    max_repeats = MAX_REDIRECTS

    def http_error_302(self, req, fp, code, msg, headers):  # type: ignore[override]
        # Checked here first, on the target resolved as the base class
        # resolves it, because the base class answers a scheme it does not
        # know (file:, data:) with an HTTPError of its own before
        # redirect_request runs: that would read as `http`, not `bad-url`.
        location = headers.get("location") or headers.get("uri")
        if location:
            check_url(urllib.parse.urljoin(req.full_url, location))
        return super().http_error_302(req, fp, code, msg, headers)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        # The final form of the target (the base class re-quotes it), with
        # no file URL whatever the command line said.
        check_url(newurl, allow_file=False)
        count = getattr(req, "redirects_followed", 0) + 1
        if count > MAX_REDIRECTS:
            raise Refused(f"refused {safe_url(newurl)}: more than {MAX_REDIRECTS} redirects")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.redirects_followed = count  # type: ignore[attr-defined]
        return new


def build_opener(allow_file: bool) -> urllib.request.OpenerDirector:
    """An opener with only the handlers this script needs.

    Not ``urlopen`` and not ``build_opener()``: those add the environment's
    proxies and the ``http``, ``ftp``, ``file`` and ``data`` handlers. Here
    ``https`` is the one scheme it can open (``file`` too under
    ``--allow-file``), through no proxy, with the system's CA store and
    hostname checking (``create_default_context``; never turned off).
    """
    opener = urllib.request.OpenerDirector()
    handlers: list[urllib.request.BaseHandler] = [
        # No proxy, and none read from the environment (as cdp.py does). With
        # no proxies a ProxyHandler has no `<scheme>_open` method, so the
        # director does not even keep it: nothing here consults *_proxy.
        urllib.request.ProxyHandler({}),
        urllib.request.UnknownHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        RedirectGuard(),
        urllib.request.HTTPErrorProcessor(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    ]
    if allow_file:
        handlers.append(urllib.request.FileHandler())
    for handler in handlers:
        opener.add_handler(handler)
    opener.addheaders = [("User-Agent", USER_AGENT)]
    return opener


# ---------------------------------------------------------------------------
# the download


def _remove(path: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)


def _create_part(part: str) -> int:
    """A new, empty part file, mode 0600.

    A stale one (a killed run's) is removed first; ``O_EXCL`` then refuses
    to open anything already at the path, a symlink planted in between
    included, and ``O_NOFOLLOW`` (where the platform has it) says so twice.
    """
    _remove(part)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    return os.open(part, flags, 0o600)


def _content_length(response) -> int | None:
    headers = getattr(response, "headers", None)
    value = headers.get("Content-Length") if headers is not None else None
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _open(opener, url: str, timeout: float, is_file: bool):
    """The response for ``url``, or :class:`Failed` / :class:`Refused`."""
    request = urllib.request.Request(url)
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        exc.close()
        where = safe_url(exc.geturl() or url)
        raise Failed("http", f"HTTP {exc.code} from {where}", exc.code) from None
    except urllib.error.URLError as exc:
        reason = exc.reason
        if is_file and isinstance(reason, FileNotFoundError):
            # The file seam answers a missing file as a server would.
            raise Failed("http", f"no such file: {safe_url(url)}", 404) from None
        raise Failed("network", f"could not reach {safe_url(url)}: {_reason(reason)}") from None
    except (TimeoutError, ConnectionError, ssl.SSLError) as exc:
        raise Failed("network", f"could not reach {safe_url(url)}: {_reason(exc)}") from None
    if response is None:  # no handler took the URL
        raise Refused(f"refused {safe_url(url)}: no handler for it")
    return response


def _reason(reason: object) -> str:
    """A short, URL-free description of why a connection failed."""
    if isinstance(reason, OSError) and reason.strerror:
        return reason.strerror
    if isinstance(reason, str):
        return reason
    return type(reason).__name__


def _read_chunk(response, final: str) -> bytes:
    """The next chunk of the body. Every failure of the read is the
    network's (``network``): a connection closed early is an
    ``http.client.IncompleteRead``, a reset or a timeout an ``OSError``.
    Kept apart from the file's side so neither is mistaken for the other."""
    try:
        return response.read(CHUNK)
    except (OSError, http.client.HTTPException) as exc:
        raise Failed("network", f"reading {safe_url(final)}: {_reason(exc)}") from None


def _write_all(fd: int, chunk: bytes) -> None:
    view = memoryview(chunk)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _file_side(step, *args):
    """``step(*args)`` on the file's side (create, write, fsync, replace):
    an ``OSError`` there is ``io``, never the network's."""
    try:
        return step(*args)
    except OSError as exc:
        raise Failed("io", f"could not write the download: {_reason(exc)}") from None


def download(
    url: str,
    dest: str,
    *,
    sha256: str | None,
    max_bytes: int,
    timeout: float,
    allow_file: bool,
    opener_factory=build_opener,
) -> dict:
    """The download itself: the success line's dict, or an exception."""
    check_url(url, allow_file=allow_file)
    is_file = url.startswith("file:")
    opener = opener_factory(allow_file)
    part = dest + ".part"
    fd = -1
    try:
        response = _open(opener, url, timeout, is_file)
        with response:
            # The final URL after every redirect passes the same check once more.
            final = response.geturl() or url
            if final != url:
                check_url(final)
            status = 200 if is_file else getattr(response, "status", None)
            if status != 200:
                raise Failed("http", f"HTTP {status} from {safe_url(final)}", status)
            # The header only refuses early; the count below decides.
            declared = _content_length(response)
            if declared is not None and declared > max_bytes:
                raise Failed("too-large", f"{safe_url(final)} is larger than {max_bytes} bytes")
            fd = _file_side(_create_part, part)
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = _read_chunk(response, final)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise Failed("too-large", f"{safe_url(final)} is larger than {max_bytes} bytes")
                digest.update(chunk)
                _file_side(_write_all, fd, chunk)
        _file_side(os.fsync, fd)
        os.close(fd)
        fd = -1
        got = digest.hexdigest()
        if sha256 is not None and got != sha256.lower():
            raise Failed("hash-mismatch", f"{safe_url(url)} does not have the expected sha256", 200)
        _file_side(os.replace, part, dest)
        return {"ok": True, "status": 200, "bytes": size, "sha256": got}
    except BaseException:
        if fd >= 0:
            os.close(fd)
        _remove(part)
        raise


# ---------------------------------------------------------------------------
# the command line and the one line of output


class ArgumentsRefused(Exception):
    """argparse's complaint, raised instead of printed (stdout stays one line)."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise ArgumentsRefused(message)


def _positive_int(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise ValueError(text)
    return value


def _positive_float(text: str) -> float:
    value = float(text)
    if not value > 0 or value == float("inf"):
        raise ValueError(text)
    return value


def _hex64(text: str) -> str:
    if not HEX64_RE.fullmatch(text):
        raise ValueError("not 64 hex digits")
    return text.lower()


def parse_args(argv: list[str]) -> argparse.Namespace:
    # add_help=False: --help would print to stdout, which carries one line.
    parser = _Parser(prog="fetch.py", add_help=False)
    parser.add_argument("url")
    parser.add_argument("dest")
    parser.add_argument("--sha256", type=_hex64, default=None)
    parser.add_argument("--max-bytes", type=_positive_int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--timeout", type=_positive_float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--allow-file", action="store_true")
    return parser.parse_args(argv)


def run(argv: list[str], *, opener_factory=build_opener) -> dict:
    """The output line's dict for ``argv``. Never raises (but for
    ``BaseException``s such as ``KeyboardInterrupt``, which :func:`main`
    catches too)."""
    try:
        args = parse_args(argv)
    except (ArgumentsRefused, ValueError):
        # Fixed text: argparse's message would quote the argument back.
        return _failure("io", "bad arguments", None)
    try:
        return download(
            args.url,
            args.dest,
            sha256=args.sha256,
            max_bytes=args.max_bytes,
            timeout=args.timeout,
            allow_file=args.allow_file,
            opener_factory=opener_factory,
        )
    except Refused as exc:
        return _failure("bad-url", str(exc), None)
    except Failed as exc:
        return _failure(exc.code, exc.message, exc.status)
    except OSError as exc:
        # Neither a read nor a write (those are Failed): say no more than that.
        return _failure("io", f"the download failed: {_reason(exc)}", None)
    except Exception as exc:
        return _failure("io", type(exc).__name__, None)


def _failure(code: str, message: str, status: int | None) -> dict:
    return {"ok": False, "error": code, "status": status, "message": scrub(message)}


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(sys.argv[1:] if argv is None else argv)
    except BaseException as exc:  # the one line, whatever happened
        result = _failure("io", type(exc).__name__, None)
    sys.stdout.write(json.dumps(result) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
