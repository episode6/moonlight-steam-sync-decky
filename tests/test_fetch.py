"""fetch.py, the update downloader (update spec 3.12.3 / 3.12.6).

The real script runs with ``sys.executable -I`` against ``file://`` URLs
(``--allow-file``); the URL check and the redirect handler are called
directly from the script loaded as a module, with fake requests. Nothing
connects anywhere (``no_network``).
"""

from __future__ import annotations

import email.message
import hashlib
import http.client
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import urllib.response

import pytest

from conftest import ROOT

pytestmark = pytest.mark.usefixtures("no_network")

SCRIPT = ROOT / "py_modules" / "moonlight_sync" / "fetch.py"
PAYLOAD = b"moonlight " * 20_000  # 200 kB: several 64 KiB chunks
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()
SECRET = "SECRET-token-value"


def load_fetch():
    spec = importlib.util.spec_from_file_location("fetch_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = load_fetch()


def run_script(*args: str) -> tuple[dict, subprocess.CompletedProcess[str]]:
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    # Exactly one line on stdout, exit 0, nothing on stderr, whatever happened.
    assert result.returncode == 0, result
    assert result.stdout.count("\n") == 1 and result.stdout.endswith("\n"), result.stdout
    assert result.stderr == ""
    return json.loads(result.stdout), result


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "srv" / "Moonlight-Sync.zip"
    path.parent.mkdir()
    path.write_bytes(PAYLOAD)
    return path


@pytest.fixture
def dest(tmp_path):
    folder = tmp_path / "staged dir"  # a space, as in "Moonlight Sync"
    folder.mkdir()
    return folder / "out.zip"


def part_of(dest) -> str:
    return str(dest) + ".part"


# ---------------------------------------------------------------------------
# the real script over file://


def test_a_download_and_its_hash(source, dest) -> None:
    answer, _ = run_script("--allow-file", "--", source.as_uri(), str(dest))
    assert answer == {"ok": True, "status": 200, "bytes": len(PAYLOAD), "sha256": PAYLOAD_SHA}
    assert dest.read_bytes() == PAYLOAD
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600
    assert not os.path.exists(part_of(dest))


@pytest.mark.parametrize("given", [PAYLOAD_SHA, PAYLOAD_SHA.upper()])
def test_the_right_sha256(source, dest, given) -> None:
    answer, _ = run_script("--allow-file", "--sha256", given, source.as_uri(), str(dest))
    assert answer["ok"] is True and answer["sha256"] == PAYLOAD_SHA


def test_the_wrong_sha256_leaves_dest_as_it_was(source, dest) -> None:
    dest.write_bytes(b"the previous file")
    answer, _ = run_script("--allow-file", "--sha256", "0" * 64, source.as_uri(), str(dest))
    assert answer["ok"] is False and answer["error"] == "hash-mismatch"
    assert dest.read_bytes() == b"the previous file"
    assert not os.path.exists(part_of(dest))


def test_max_bytes_exceeded(source, dest) -> None:
    dest.write_bytes(b"the previous file")
    answer, _ = run_script(
        "--allow-file", "--max-bytes", str(len(PAYLOAD) - 1), source.as_uri(), str(dest)
    )
    assert answer["ok"] is False and answer["error"] == "too-large"
    assert dest.read_bytes() == b"the previous file"
    assert not os.path.exists(part_of(dest))


def test_max_bytes_exactly_is_fine(source, dest) -> None:
    answer, _ = run_script(
        "--allow-file", "--max-bytes", str(len(PAYLOAD)), source.as_uri(), str(dest)
    )
    assert answer["ok"] is True


def test_a_missing_file_answers_as_a_404(tmp_path, dest) -> None:
    dest.write_bytes(b"the previous file")
    answer, _ = run_script("--allow-file", (tmp_path / "nothing.zip").as_uri(), str(dest))
    assert answer["ok"] is False
    assert (answer["error"], answer["status"]) == ("http", 404)
    assert dest.read_bytes() == b"the previous file"
    assert not os.path.exists(part_of(dest))


def test_a_stale_part_file_is_replaced(source, dest) -> None:
    with open(part_of(dest), "wb") as handle:
        handle.write(b"left by a killed run")
    answer, _ = run_script("--allow-file", source.as_uri(), str(dest))
    assert answer["ok"] is True and dest.read_bytes() == PAYLOAD
    assert not os.path.exists(part_of(dest))


def test_a_symlink_at_the_part_path_is_never_followed(source, dest, tmp_path) -> None:
    victim = tmp_path / "victim"
    victim.write_bytes(b"do not touch")
    os.symlink(victim, part_of(dest))
    answer, _ = run_script("--allow-file", source.as_uri(), str(dest))
    assert answer["ok"] is True
    assert victim.read_bytes() == b"do not touch"
    assert dest.read_bytes() == PAYLOAD


def test_an_unwritable_destination_is_io(source, tmp_path) -> None:
    answer, _ = run_script("--allow-file", source.as_uri(), str(tmp_path / "no-dir" / "x.zip"))
    assert answer["ok"] is False and answer["error"] == "io"
    assert answer["status"] is None


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/episode6/x/releases/download/v1/Moonlight-Sync.zip",
        "https://example.com/Moonlight-Sync.zip",
        "https://api.github.com/repos/x/y/releases",
        "ftp://github.com/x",
    ],
)
def test_bad_url(url, dest) -> None:
    dest.write_bytes(b"the previous file")
    answer, _ = run_script("--allow-file", url, str(dest))
    assert answer == {"ok": False, "error": "bad-url", "status": None, "message": answer["message"]}
    assert dest.read_bytes() == b"the previous file"
    assert not os.path.exists(part_of(dest))


def test_file_without_the_flag_is_bad_url(source, dest) -> None:
    answer, _ = run_script(source.as_uri(), str(dest))
    assert answer["error"] == "bad-url"
    assert not dest.exists()


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["only-a-url"],
        ["--sha256", "abc", "https://github.com/x", "/tmp/x"],
        ["--sha256", "g" * 64, "https://github.com/x", "/tmp/x"],
        ["--max-bytes", "0", "https://github.com/x", "/tmp/x"],
        ["--max-bytes", "lots", "https://github.com/x", "/tmp/x"],
        ["--timeout", "-1", "https://github.com/x", "/tmp/x"],
        ["--timeout", "nan", "https://github.com/x", "/tmp/x"],
        ["--help"],
        ["--unknown", "https://github.com/x", "/tmp/x"],
    ],
)
def test_bad_arguments_are_one_io_line(args) -> None:
    answer, _ = run_script(*args)
    assert answer == {"ok": False, "error": "io", "status": None, "message": "bad arguments"}


def test_the_script_runs_isolated_and_imports_nothing_beside_it(tmp_path, source, dest) -> None:
    """`-I`: a module named like a standard one beside a copy of the script is
    not what it imports."""
    copy = tmp_path / "isolated" / "fetch.py"
    copy.parent.mkdir()
    copy.write_bytes(SCRIPT.read_bytes())
    (copy.parent / "hashlib.py").write_text("raise SystemExit('shadowed')\n")
    result = subprocess.run(
        [sys.executable, "-I", str(copy), "--allow-file", source.as_uri(), str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert json.loads(result.stdout)["ok"] is True


# ---------------------------------------------------------------------------
# the URL check, directly


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/episode6/moonlight-steam-sync-decky/releases/download/v1/x.zip",
        "https://GITHUB.COM/x",
        "https://github.com:443/x",
        "https://release-assets.githubusercontent.com/github-production-release-asset/1?sig=x",
        "https://objects.githubusercontent.com/x",
    ],
)
def test_check_url_accepts(url) -> None:
    fetch.check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/x",
        "HTTPS://github.com/x",
        "https://evilgithubusercontent.com/x",
        "https://githubusercontent.com/x",
        "https://github.com.evil.example/x",
        "https://api.github.com/x",
        "https://gist.github.com/x",
        "https://github.com@evil.example/",
        "https://user:pass@github.com/",
        "https://github.com:8443/",
        "https://github.com:/x",
        "https://github.com:abc/x",
        "https://evil.example/?x=github.com",
        "https://evil.example/#github.com",
        "https://github.com./x",
        "https://github..com/x",
        "https://[::1]/x",
        "https://127.0.0.1/x",
        "https:///x",
        "https://github.com\\@evil.example/",
        "https://github.com/x y",
        "https://github.com/x\ty",
        "https://github.com/x\ny",
        "https://github.com/\x00",
        "https://github.com/café",
        " https://github.com/x",
        "file:///etc/passwd",
        "data:text/plain,x",
        "",
        "https://github.com/" + "a" * 5000,
        None,
    ],
)
def test_check_url_refuses(url) -> None:
    with pytest.raises(fetch.Refused):
        fetch.check_url(url)


def test_allow_file_admits_file_urls_and_nothing_else() -> None:
    fetch.check_url("file:///srv/releases/v1/Moonlight-Sync.zip", allow_file=True)
    for url in (
        "file://host/srv/x",
        "file:/srv/x",
        "file:///srv/x?q=1",
        "http://github.com/x",
        "https://example.com/x",
    ):
        with pytest.raises(fetch.Refused):
            fetch.check_url(url, allow_file=True)


def test_a_refusal_never_quotes_a_query() -> None:
    with pytest.raises(fetch.Refused) as caught:
        fetch.check_url(f"https://evil.example/path?token={SECRET}")
    assert SECRET not in str(caught.value)
    assert "https://evil.example/path" in str(caught.value)


# ---------------------------------------------------------------------------
# the redirect handler, directly


def headers(location: str) -> email.message.Message:
    message = email.message.Message()
    message["Location"] = location
    return message


class FakeParent:
    def __init__(self) -> None:
        self.opened: list[urllib.request.Request] = []

    def open(self, request, timeout=None):
        self.opened.append(request)
        return "followed"


def guard() -> tuple[object, FakeParent]:
    handler = fetch.RedirectGuard()
    parent = FakeParent()
    handler.parent = parent
    return handler, parent


def start() -> urllib.request.Request:
    request = urllib.request.Request(
        "https://github.com/o/r/releases/download/v1/Moonlight-Sync.zip"
    )
    request.timeout = 30  # what OpenerDirector.open sets on a request it opens
    return request


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example/x",
        "http://release-assets.githubusercontent.com/x",
        "https://evilgithubusercontent.com/x",
        "file:///etc/passwd",
        "data:text/plain,x",
    ],
)
def test_the_handler_refuses_a_hop_before_following_it(target) -> None:
    handler, parent = guard()
    with pytest.raises(fetch.Refused):
        handler.http_error_302(start(), io.BytesIO(b""), 302, "Found", headers(target))
    with pytest.raises(fetch.Refused):
        handler.redirect_request(start(), io.BytesIO(b""), 302, "Found", headers(target), target)
    assert parent.opened == []


def test_the_handler_follows_a_hop_to_github_s_asset_host() -> None:
    handler, parent = guard()
    target = f"https://release-assets.githubusercontent.com/a/b?token={SECRET}"
    assert handler.http_error_302(start(), io.BytesIO(b""), 302, "Found", headers(target)) == (
        "followed"
    )
    assert [request.full_url for request in parent.opened] == [target]


def test_a_redirect_to_file_is_refused_even_with_the_flag() -> None:
    """The handler never looks at --allow-file: a file URL is never a hop."""
    handler, parent = guard()
    with pytest.raises(fetch.Refused):
        handler.http_error_302(start(), io.BytesIO(b""), 302, "Found", headers("file:///x"))
    assert parent.opened == []
    opener = fetch.build_opener(True)
    guards = [h for h in opener.handlers if isinstance(h, fetch.RedirectGuard)]
    assert len(guards) == 1
    with pytest.raises(fetch.Refused):
        guards[0].redirect_request(start(), None, 302, "Found", headers("x"), "file:///etc/passwd")


def test_at_most_five_redirects() -> None:
    handler, _ = guard()
    request = start()
    for hop in range(1, 6):
        target = f"https://objects.githubusercontent.com/hop{hop}"
        request = handler.redirect_request(request, None, 302, "Found", headers(target), target)
        assert request is not None and request.redirects_followed == hop
    with pytest.raises(fetch.Refused, match="more than 5 redirects"):
        handler.redirect_request(request, None, 302, "Found", headers("x"), "https://github.com/6")
    assert fetch.RedirectGuard.max_redirections == 5


def test_the_opener_has_only_the_handlers_it_needs() -> None:
    kinds = {type(h) for h in fetch.build_opener(False).handlers}
    assert urllib.request.HTTPHandler not in kinds
    assert urllib.request.FTPHandler not in kinds
    assert urllib.request.FileHandler not in kinds
    assert urllib.request.DataHandler not in kinds
    assert urllib.request.HTTPSHandler in kinds
    assert fetch.RedirectGuard in kinds
    assert urllib.request.HTTPRedirectHandler not in kinds
    assert urllib.request.FileHandler in {type(h) for h in fetch.build_opener(True).handlers}
    # The schemes the director can open: https (file too under --allow-file);
    # `unknown` is UnknownHandler's, which refuses everything else.
    assert set(fetch.build_opener(False).handle_open) == {"https", "unknown"}
    assert set(fetch.build_opener(True).handle_open) == {"https", "file", "unknown"}
    https = next(
        h for h in fetch.build_opener(False).handlers if isinstance(h, urllib.request.HTTPSHandler)
    )
    context = https._context
    assert context.verify_mode.name == "CERT_REQUIRED" and context.check_hostname is True


def test_the_opener_ignores_the_environment_s_proxy(monkeypatch) -> None:
    monkeypatch.setenv("https_proxy", "http://proxy.invalid:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    opener = fetch.build_opener(False)
    assert not any(isinstance(h, urllib.request.ProxyHandler) for h in opener.handlers)
    assert [type(h) for h in opener.handle_open["https"]] == [urllib.request.HTTPSHandler]


# ---------------------------------------------------------------------------
# run(): the output line, over fake openers (never a connection)


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, url: str, status: int = 200, length: str | None = None):
        super().__init__(data)
        self.url = url
        self.status = status
        self.headers = email.message.Message()
        if length is not None:
            self.headers["Content-Length"] = length

    def geturl(self) -> str:
        return self.url


def opener_answering(behaviour):
    class Opener:
        def open(self, request, timeout=None):
            return behaviour(request)

    return lambda allow_file: Opener()


URL = "https://github.com/o/r/releases/download/v1/Moonlight-Sync.zip"


def test_a_redirect_refused_mid_download_is_bad_url_without_the_query(dest) -> None:
    def redirected(request):
        handler = fetch.RedirectGuard()
        target = f"https://evil.example/steal?token={SECRET}"
        return handler.redirect_request(request, None, 302, "Found", headers(target), target)

    answer = fetch.run([URL, str(dest)], opener_factory=opener_answering(redirected))
    assert answer["ok"] is False and answer["error"] == "bad-url"
    assert SECRET not in json.dumps(answer)
    assert "https://evil.example/steal" in answer["message"]
    assert not dest.exists() and not os.path.exists(part_of(dest))


def test_an_http_error_after_a_redirect_quotes_no_query(dest) -> None:
    def forbidden(request):
        raise urllib.error.HTTPError(
            f"https://release-assets.githubusercontent.com/a?token={SECRET}",
            403,
            "Forbidden",
            {},
            None,
        )

    answer = fetch.run([URL, str(dest)], opener_factory=opener_answering(forbidden))
    assert (answer["error"], answer["status"]) == ("http", 403)
    assert SECRET not in json.dumps(answer)
    assert "release-assets.githubusercontent.com/a" in answer["message"]


def test_a_network_error_is_network(dest) -> None:
    def unreachable(request):
        raise urllib.error.URLError(OSError(101, "Network is unreachable"))

    answer = fetch.run([URL, str(dest)], opener_factory=opener_answering(unreachable))
    assert answer["error"] == "network" and answer["status"] is None
    assert "Network is unreachable" in answer["message"]


def test_a_success_over_https_through_a_redirect(dest) -> None:
    final = f"https://release-assets.githubusercontent.com/a?token={SECRET}"
    answer = fetch.run(
        ["--sha256", PAYLOAD_SHA, URL, str(dest)],
        opener_factory=opener_answering(lambda request: FakeResponse(PAYLOAD, final)),
    )
    assert answer == {"ok": True, "status": 200, "bytes": len(PAYLOAD), "sha256": PAYLOAD_SHA}
    assert dest.read_bytes() == PAYLOAD


def test_a_final_url_off_the_allowlist_is_refused(dest) -> None:
    answer = fetch.run(
        [URL, str(dest)],
        opener_factory=opener_answering(lambda r: FakeResponse(PAYLOAD, "https://evil.example/")),
    )
    assert answer["error"] == "bad-url"
    assert not dest.exists()


def test_a_status_other_than_200_is_http(dest) -> None:
    answer = fetch.run(
        [URL, str(dest)],
        opener_factory=opener_answering(lambda r: FakeResponse(b"", URL, status=206)),
    )
    assert (answer["error"], answer["status"]) == ("http", 206)


def test_a_content_length_over_the_limit_is_refused_before_reading(dest) -> None:
    class Unread(FakeResponse):
        def read(self, *args):
            raise AssertionError("read after a Content-Length over the limit")

    answer = fetch.run(
        ["--max-bytes", "100", URL, str(dest)],
        opener_factory=opener_answering(lambda r: Unread(b"", URL, length="101")),
    )
    assert answer["error"] == "too-large"
    assert not os.path.exists(part_of(dest))


def test_the_count_decides_not_the_header(dest) -> None:
    dest.write_bytes(b"the previous file")
    answer = fetch.run(
        ["--max-bytes", "1000", URL, str(dest)],
        opener_factory=opener_answering(lambda r: FakeResponse(PAYLOAD, URL, length="10")),
    )
    assert answer["error"] == "too-large"
    assert dest.read_bytes() == b"the previous file"
    assert not os.path.exists(part_of(dest))


def test_an_uncaught_exception_is_io_with_its_class_name_only(dest, capsys) -> None:
    def broken(request):
        raise RuntimeError(f"https://x.githubusercontent.com/?token={SECRET}")

    answer = fetch.run([URL, str(dest)], opener_factory=opener_answering(broken))
    assert answer == {"ok": False, "error": "io", "status": None, "message": "RuntimeError"}


def test_main_prints_one_line_even_when_run_itself_fails(monkeypatch, capsys) -> None:
    def explode(argv, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(fetch, "run", explode)
    assert fetch.main(["x", "y"]) == 0
    out = capsys.readouterr()
    assert out.err == ""
    assert json.loads(out.out) == {
        "ok": False,
        "error": "io",
        "status": None,
        "message": "KeyboardInterrupt",
    }


def test_scrub_drops_every_query() -> None:
    text = f"a https://h.githubusercontent.com/p?x={SECRET} and file:///x#frag{SECRET}"
    assert SECRET not in fetch.scrub(text)


# ---------------------------------------------------------------------------
# the whole chain in a real OpenerDirector, over a fake https handler: urllib
# asks the guard before it opens a redirect's target


class FakeHTTPS(urllib.request.BaseHandler):
    """``https_open`` that answers from a script of ``url -> (code, location)``
    and records every URL it was asked to open."""

    def __init__(self, script: dict[str, tuple[int, str | None]]) -> None:
        self.script = script
        self.opened: list[str] = []

    def https_open(self, request):
        self.opened.append(request.full_url)
        code, location = self.script[request.full_url]
        message = email.message.Message()
        if location is not None:
            message["Location"] = location
        response = urllib.response.addinfourl(io.BytesIO(PAYLOAD), message, request.full_url, code)
        response.msg = "OK" if code == 200 else "Found"
        return response


def chained_opener(fake: FakeHTTPS):
    def factory(allow_file: bool):
        opener = urllib.request.OpenerDirector()
        for handler in (
            urllib.request.UnknownHandler(),
            urllib.request.HTTPDefaultErrorHandler(),
            fetch.RedirectGuard(),
            urllib.request.HTTPErrorProcessor(),
            fake,
        ):
            opener.add_handler(handler)
        return opener

    return factory


def test_urllib_refuses_the_hop_before_opening_it(dest) -> None:
    evil = f"https://evil.example/x?token={SECRET}"
    fake = FakeHTTPS({URL: (302, evil), evil: (200, None)})
    answer = fetch.run([URL, str(dest)], opener_factory=chained_opener(fake))
    assert answer["error"] == "bad-url"
    assert fake.opened == [URL]  # never the evil one
    assert SECRET not in json.dumps(answer)


def test_urllib_follows_five_hops_and_refuses_the_sixth(dest) -> None:
    hops = [URL] + [f"https://objects.githubusercontent.com/{n}" for n in range(1, 7)]
    script = {hops[n]: (302, hops[n + 1]) for n in range(6)}
    script[hops[6]] = (200, None)
    fake = FakeHTTPS(script)
    answer = fetch.run([URL, str(dest)], opener_factory=chained_opener(fake))
    assert answer["error"] == "bad-url" and "more than 5 redirects" in answer["message"]
    assert fake.opened == hops[:6]


def test_urllib_through_five_hops_downloads(dest) -> None:
    hops = [URL] + [f"https://objects.githubusercontent.com/{n}" for n in range(1, 6)]
    script = {hops[n]: (302, hops[n + 1]) for n in range(5)}
    script[hops[5]] = (200, None)
    fake = FakeHTTPS(script)
    answer = fetch.run(
        ["--sha256", PAYLOAD_SHA, URL, str(dest)], opener_factory=chained_opener(fake)
    )
    assert answer["ok"] is True and fake.opened == hops
    assert dest.read_bytes() == PAYLOAD


def test_urllib_refuses_a_redirect_to_file(dest, tmp_path) -> None:
    target = (tmp_path / "secret").as_uri()
    fake = FakeHTTPS({URL: (302, target)})
    answer = fetch.run(["--allow-file", URL, str(dest)], opener_factory=chained_opener(fake))
    assert answer["error"] == "bad-url"
    assert fake.opened == [URL]


def test_urllib_refuses_a_downgrade_to_http(dest) -> None:
    target = "http://objects.githubusercontent.com/x"
    fake = FakeHTTPS({URL: (301, target)})
    answer = fetch.run([URL, str(dest)], opener_factory=chained_opener(fake))
    assert answer["error"] == "bad-url"
    assert fake.opened == [URL]


# ---------------------------------------------------------------------------
# a body cut short is the network's; a failed write is the file's


class CutShort(FakeResponse):
    """Gives one chunk, then fails the next read with ``error``."""

    def __init__(self, error: BaseException) -> None:
        super().__init__(PAYLOAD, URL, length=str(len(PAYLOAD)))
        self.error = error
        self.reads = 0

    def read(self, *args):
        self.reads += 1
        if self.reads > 1:
            raise self.error
        return super().read(*args)


@pytest.mark.parametrize(
    "error",
    [
        http.client.IncompleteRead(b"partial", 1000),
        OSError(5, "Input/output error"),
        ConnectionResetError(104, "Connection reset by peer"),
    ],
)
def test_a_body_cut_short_is_network(dest, error) -> None:
    dest.write_bytes(b"the previous file")
    answer = fetch.run([URL, str(dest)], opener_factory=opener_answering(lambda r: CutShort(error)))
    assert answer["ok"] is False and answer["error"] == "network"
    assert answer["message"].startswith("reading https://github.com/")
    assert dest.read_bytes() == b"the previous file"
    assert not os.path.exists(part_of(dest))


def test_a_failed_write_is_io(dest, monkeypatch) -> None:
    dest.write_bytes(b"the previous file")

    def full(fd, data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(fetch.os, "write", full)
    answer = fetch.run(
        [URL, str(dest)], opener_factory=opener_answering(lambda r: FakeResponse(PAYLOAD, URL))
    )
    assert answer == {
        "ok": False,
        "error": "io",
        "status": None,
        "message": "could not write the download: No space left on device",
    }
    assert dest.read_bytes() == b"the previous file"
    assert not os.path.exists(part_of(dest))


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write a read-only directory")
def test_a_read_only_destination_is_io(dest) -> None:
    dest.write_bytes(b"the previous file")
    dest.parent.chmod(0o555)
    try:
        answer = fetch.run(
            [URL, str(dest)],
            opener_factory=opener_answering(lambda r: FakeResponse(PAYLOAD, URL)),
        )
    finally:
        dest.parent.chmod(0o755)
    assert answer["error"] == "io"
    assert answer["message"].startswith("could not write the download")
    assert dest.read_bytes() == b"the previous file"
