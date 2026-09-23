"""A minimal DOM over ``tests/fixtures/sgdb/*.html``, and the snippets' mirrors.

There is no JavaScript engine here. :class:`Document` is the subset of the
DOM that ``sgdbpage.py``'s snippets touch (``querySelector`` /
``querySelectorAll`` for tag, class, id and attribute selectors with the
descendant combinator and selector lists; ``textContent``, ``innerText``,
``value``, ``href``, a recording ``click()``, ``document.readyState`` and
``location.href``), and :func:`evaluate` runs each snippet's *mirror* over
it: the same control flow written in Python, with every selector and
regex literal read out of the snippet's own text, so a selector changed in
``sgdbpage.py`` changes what the mirror queries and a snippet whose shape
changed is a test failure, not a silent drift. The mirrors are matched to
the snippets by their exact text.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from moonlight_sync import sgdbpage

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sgdb"

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}


class Element:
    def __init__(self, tag: str, attrs: dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.document: Document | None = None
        self.children: list[Element | str] = []
        self.parent: Element | None = None

    # -- the DOM surface the snippets read ----------------------------------

    @property
    def text_content(self) -> str:
        return "".join(c if isinstance(c, str) else c.text_content for c in self.children)

    @property
    def inner_text(self) -> str:
        return " ".join(self.text_content.split())

    @property
    def value(self) -> str:
        return self.attrs.get("value", "")

    @property
    def href(self) -> str | None:
        return self.attrs.get("href") if "href" in self.attrs else None

    def click(self) -> None:
        assert self.document is not None
        self.document.clicks.append(self)

    def remove(self) -> None:
        if self.parent is not None:
            self.parent.children.remove(self)
            self.parent = None

    # -- selectors -------------------------------------------------------

    def descendants(self) -> list[Element]:
        out: list[Element] = []
        for child in self.children:
            if isinstance(child, Element):
                out.append(child)
                out.extend(child.descendants())
        return out

    def query_selector_all(self, selector: str) -> list[Element]:
        groups = [_parse_compound_chain(part) for part in _split_top(selector, ",")]
        return [el for el in self.descendants() if any(_matches_chain(el, g) for g in groups)]

    def query_selector(self, selector: str) -> Element | None:
        found = self.query_selector_all(selector)
        return found[0] if found else None

    def __repr__(self) -> str:
        return f"<{self.tag} {self.attrs}>"


class Location:
    def __init__(self, document: Document, href: str) -> None:
        self.document = document
        self._href = href

    @property
    def href(self) -> str:
        return self._href

    @href.setter
    def href(self, url: str) -> None:
        self.document.navigations.append(url)


class Document:
    """One parsed page. ``clicks`` and ``navigations`` record what a snippet did."""

    def __init__(self, root: Element, href: str = "about:blank") -> None:
        self.root = root
        self.clicks: list[Element] = []
        self.navigations: list[str] = []
        self.ready_state = "complete"
        self.location = Location(self, href)
        for element in [root, *root.descendants()]:
            element.document = self

    @classmethod
    def from_html(cls, text: str, href: str = "about:blank") -> Document:
        parser = _Parser()
        parser.feed(text)
        parser.close()
        return cls(parser.root, href)

    @classmethod
    def from_fixture(cls, name: str, href: str = "about:blank") -> Document:
        return cls.from_html((FIXTURES / name).read_text(encoding="utf-8"), href)

    def query_selector_all(self, selector: str) -> list[Element]:
        return self.root.query_selector_all(selector)

    def query_selector(self, selector: str) -> Element | None:
        return self.root.query_selector(selector)

    @property
    def title(self) -> str:
        el = self.query_selector("title")
        return el.text_content.strip() if el is not None else ""


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = Element(tag, {k: v or "" for k, v in attrs})
        element.parent = self.stack[-1]
        self.stack[-1].children.append(element)
        if tag not in _VOID:
            self.stack.append(element)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


# ---------------------------------------------------------------------------
# selectors: `tag.class#id[attr=value][attr*=value]`, descendants, lists

_COMPOUND = re.compile(r"^([a-zA-Z][\w-]*)?((?:[#.][\w-]+|\[[^\]]+\])*)$")
_PART = re.compile(r"[#.][\w-]+|\[[^\]]+\]")
_ATTR = re.compile(r"^\[\s*([\w-]+)\s*(?:(\*?=)\s*(\"[^\"]*\"|'[^']*'|[^\]]*))?\s*\]$")


def _split_top(text: str, sep: str) -> list[str]:
    """Split on ``sep`` outside ``[...]``."""
    parts, depth, current = [], 0, ""
    for ch in text:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    return [p.strip() for p in parts if p.strip()]


def _parse_compound(text: str) -> tuple[str | None, list[tuple[str, str, str | None]]]:
    match = _COMPOUND.match(text)
    if match is None:
        raise ValueError(f"unsupported selector: {text!r}")
    tag = match.group(1).lower() if match.group(1) else None
    conditions: list[tuple[str, str, str | None]] = []
    for part in _PART.findall(match.group(2)):
        if part[0] == "#":
            conditions.append(("id", part[1:], None))
        elif part[0] == ".":
            conditions.append(("class", part[1:], None))
        else:
            attr = _ATTR.match(part)
            if attr is None:
                raise ValueError(f"unsupported attribute selector: {part!r}")
            value = attr.group(3)
            if value is not None and value[:1] in "\"'":
                value = value[1:-1]
            conditions.append((attr.group(1), value or "", attr.group(2)))
    return tag, conditions


def _parse_compound_chain(text: str) -> list[tuple[str | None, list[tuple[str, str, str | None]]]]:
    return [_parse_compound(part) for part in _split_top(text, " ")]


def _matches_compound(el: Element, compound: tuple[str | None, list[Any]]) -> bool:
    tag, conditions = compound
    if tag is not None and el.tag != tag:
        return False
    for name, value, op in conditions:
        if name == "id" and op is None:
            ok = el.attrs.get("id") == value
        elif name == "class" and op is None:
            ok = value in el.attrs.get("class", "").split()
        elif name not in el.attrs:
            ok = False
        elif op == "=":
            ok = el.attrs[name] == value
        elif op == "*=":
            ok = value in el.attrs[name]
        else:
            ok = True  # `[attr]`: present
        if not ok:
            return False
    return True


def _matches_chain(el: Element, chain: list[tuple[str | None, list[Any]]]) -> bool:
    if not _matches_compound(el, chain[-1]):
        return False
    ancestor = el.parent
    for compound in reversed(chain[:-1]):
        while ancestor is not None and not _matches_compound(ancestor, compound):
            ancestor = ancestor.parent
        if ancestor is None:
            return False
        ancestor = ancestor.parent
    return True


# ---------------------------------------------------------------------------
# the mirrors

_SELECTOR_IN_JS = re.compile(r"querySelector(?:All)?\((['\"])(.*?)\1\)")
_STRING_IN_JS = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")
_REGEX_IN_JS = re.compile(r"/((?:\\.|[^/\\])+)/([a-z]*)")
_NAVIGATE_RE = re.compile(
    "^"
    + re.escape(sgdbpage.JS_NAVIGATE.split("%s")[0])
    + r'("(?:\\.|[^"\\])*")'
    + re.escape(sgdbpage.JS_NAVIGATE.split("%s")[1])
    + "$"
)


def selectors_of(js: str) -> list[str]:
    """Every ``querySelector(All)`` argument in a snippet, in order."""
    return [m.group(2) for m in _SELECTOR_IN_JS.finditer(js)]


def regexes_of(js: str) -> list[re.Pattern[str]]:
    """Every regex literal in a snippet (string literals blanked first), in order."""
    blanked = _STRING_IN_JS.sub('""', js)
    out = []
    for match in _REGEX_IN_JS.finditer(blanked):
        flags = re.IGNORECASE if "i" in match.group(2) else 0
        out.append(re.compile(match.group(1), flags))
    return out


def evaluate(js: str, document: Document) -> Any:
    """Run the snippet's mirror over ``document`` and answer as the page would."""
    if js == sgdbpage.JS_PAGE:
        return {"href": document.location.href, "ready": document.ready_state}
    if js == sgdbpage.JS_LOGIN_LINK:
        (selector,) = selectors_of(js)
        el = document.query_selector(selector)
        return el.href if el is not None else None
    if js == sgdbpage.JS_OPENID_FORM:
        (selector,) = selectors_of(js)
        return document.query_selector(selector) is not None
    if js == sgdbpage.JS_OPENID_SUBMIT:
        (selector,) = selectors_of(js)
        el = document.query_selector(selector)
        if el is None:
            return False
        el.click()
        return True
    if js == sgdbpage.JS_KEY:
        (selector,) = selectors_of(js)
        (pattern,) = regexes_of(js)
        texts = [e.text_content.strip() for e in document.query_selector_all(selector)]
        found = [t for t in texts if pattern.search(t)]
        return found[0] if len(found) == 1 else None
    if js == sgdbpage.JS_GENERATE:
        (selector,) = selectors_of(js)
        wanted, excluded = regexes_of(js)
        for el in document.query_selector_all(selector):
            text = el.inner_text or el.value or ""
            if wanted.search(text) and not excluded.search(text):
                el.click()
                return True
        return False
    navigate = _NAVIGATE_RE.match(js)
    if navigate is not None:
        document.location.href = json.loads(navigate.group(1))
        return True
    raise ValueError(f"no mirror for the snippet {js[:60]!r}")


#: Every snippet ``fetch_key`` can evaluate, for the never-Revoke check.
ALL_SNIPPETS = (
    sgdbpage.JS_PAGE,
    sgdbpage.JS_LOGIN_LINK,
    sgdbpage.navigate_js(sgdbpage.SGDB_API_PAGE),
    sgdbpage.JS_OPENID_SUBMIT,
    sgdbpage.JS_OPENID_FORM,
    sgdbpage.JS_KEY,
    sgdbpage.JS_GENERATE,
)
