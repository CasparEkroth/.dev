from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from tree_sitter_language_pack import get_parser


@dataclass
class Symbol:
    kind: str
    name: str
    signature: str
    start: int
    end: int
    start_line: int
    end_line: int


@dataclass(frozen=True)
class _TreeSitterAPI:
    """Concrete accessors for the installed tree-sitter binding.

    Official tree-sitter exposes Node fields as properties (``.type``,
    ``.start_byte``, …). Some alternate builds expose the same names as
    zero-arg methods (``.kind()``, ``.start_byte()``, …). Detect once and
    never use ``callable()`` on live node fields — that path segfaulted on
    CI during large-tree walks.
    """

    method_style: bool
    kind_attr: str
    start_point_attr: str
    end_point_attr: str
    parse_bytes: bool

    def root(self, tree):
        root = tree.root_node
        return root() if self.method_style else root

    def kind(self, node) -> str:
        value = getattr(node, self.kind_attr)
        return value() if self.method_style else value

    def start_byte(self, node) -> int:
        value = node.start_byte
        return int(value() if self.method_style else value)

    def end_byte(self, node) -> int:
        value = node.end_byte
        return int(value() if self.method_style else value)

    def start_point(self, node):
        value = getattr(node, self.start_point_attr)
        return value() if self.method_style else value

    def end_point(self, node):
        value = getattr(node, self.end_point_attr)
        return value() if self.method_style else value

    def child_count(self, node) -> int:
        value = node.child_count
        return int(value() if self.method_style else value)

    def children(self, node):
        # Prefer the ``children`` sequence when the binding provides it as data.
        if not self.method_style and hasattr(node, "children"):
            return list(node.children)
        return [
            child
            for i in range(self.child_count(node))
            if (child := node.child(i)) is not None
        ]

    def point_row(self, point) -> int:
        if isinstance(point, tuple):
            return int(point[0])
        return int(point.row)

    def parse(self, parser, code: str):
        source_bytes = code.encode("utf8")
        tree = parser.parse(source_bytes if self.parse_bytes else code)
        return tree, source_bytes


_API: _TreeSitterAPI | None = None


def _detect_api(parser) -> _TreeSitterAPI:
    source = b"def _probe():\n    pass\n"
    parse_bytes = True
    try:
        tree = parser.parse(source)
    except TypeError:
        tree = parser.parse(source.decode("utf8"))
        parse_bytes = False

    root_attr = tree.root_node
    # Property API yields a Node; method API yields a bound method.
    method_style = not hasattr(root_attr, "child") and not hasattr(root_attr, "type")
    root = root_attr() if method_style else root_attr

    if hasattr(root, "type") and not method_style:
        kind_attr = "type"
    elif hasattr(root, "kind"):
        kind_attr = "kind"
    else:
        kind_attr = "type"

    if hasattr(root, "start_point"):
        start_point_attr, end_point_attr = "start_point", "end_point"
    else:
        start_point_attr, end_point_attr = "start_position", "end_position"

    return _TreeSitterAPI(
        method_style=method_style,
        kind_attr=kind_attr,
        start_point_attr=start_point_attr,
        end_point_attr=end_point_attr,
        parse_bytes=parse_bytes,
    )


def _api(parser) -> _TreeSitterAPI:
    global _API
    if _API is None:
        _API = _detect_api(parser)
    return _API


class LanguageAdapter(ABC):
    def __init__(self, language: str):
        self.language = language
        self.parser = get_parser(language)
        self._ts = _api(self.parser)

    def extract_symbols(self, code: str) -> list[Symbol]:
        # Keep `tree` referenced for the full walk. Nodes borrow into the Tree;
        # dropping it early can make native field access segfault.
        tree, source_bytes = self._ts.parse(self.parser, code)
        root = self._ts.root(tree)

        symbols: list[Symbol] = []
        stack = [root]
        while stack:
            node = stack.pop()
            if self.is_function(node):
                symbols.append(self.extract_function(node, source_bytes))
            elif self.is_class(node):
                symbols.append(self.extract_class(node, source_bytes))

            children = self._ts.children(node)
            stack.extend(reversed(children))

        _ = tree  # lifetime anchor for native nodes
        return symbols

    @abstractmethod
    def is_function(self, node) -> bool:
        pass

    @abstractmethod
    def is_class(self, node) -> bool:
        pass

    def node_kind(self, node) -> str:
        return self._ts.kind(node)

    def slice_node(self, node, source_bytes: bytes) -> str:
        start = self._ts.start_byte(node)
        end = self._ts.end_byte(node)
        return source_bytes[start:end].decode("utf8")

    def get_name(self, node, source_bytes: bytes) -> str:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return "<unknown>"
        return self.slice_node(name_node, source_bytes)

    def get_signature(self, node, source_bytes: bytes) -> str:
        text = self.slice_node(node, source_bytes)
        return text.split("\n", 1)[0].strip()

    def extract_function(self, node, source_bytes: bytes) -> Symbol:
        start = self._ts.start_point(node)
        end = self._ts.end_point(node)
        return Symbol(
            kind="function",
            name=self.get_name(node, source_bytes),
            signature=self.get_signature(node, source_bytes),
            start=self._ts.start_byte(node),
            end=self._ts.end_byte(node),
            start_line=self._ts.point_row(start) + 1,
            end_line=self._ts.point_row(end) + 1,
        )

    def extract_class(self, node, source_bytes: bytes) -> Symbol:
        start = self._ts.start_point(node)
        end = self._ts.end_point(node)
        return Symbol(
            kind="class",
            name=self.get_name(node, source_bytes),
            signature=self.get_signature(node, source_bytes),
            start=self._ts.start_byte(node),
            end=self._ts.end_byte(node),
            start_line=self._ts.point_row(start) + 1,
            end_line=self._ts.point_row(end) + 1,
        )
