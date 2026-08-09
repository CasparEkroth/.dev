from dataclasses import dataclass
from abc import ABC, abstractmethod
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


def _call_or_get(obj, name: str):
    """Read a tree-sitter field that may be a property or zero-arg method."""
    value = getattr(obj, name)
    return value() if callable(value) else value


def _node_kind(node) -> str:
    if hasattr(node, "kind"):
        kind = node.kind
        return kind() if callable(kind) else kind
    node_type = node.type
    return node_type() if callable(node_type) else node_type


def _point_row(point) -> int:
    if hasattr(point, "row"):
        return point.row
    # Standard tree-sitter points are (row, column) tuples.
    return point[0]


def _root_node(tree):
    root = tree.root_node
    return root() if callable(root) else root


def _child_count(node) -> int:
    return int(_call_or_get(node, "child_count"))


def _start_byte(node) -> int:
    return int(_call_or_get(node, "start_byte"))


def _end_byte(node) -> int:
    return int(_call_or_get(node, "end_byte"))


def _start_point(node):
    if hasattr(node, "start_position"):
        return _call_or_get(node, "start_position")
    return _call_or_get(node, "start_point")


def _end_point(node):
    if hasattr(node, "end_position"):
        return _call_or_get(node, "end_position")
    return _call_or_get(node, "end_point")


def _parse(parser, code: str):
    """Parse source for both bytes-only and str-only tree-sitter builds."""
    source_bytes = code.encode("utf8")
    try:
        return parser.parse(source_bytes), source_bytes
    except TypeError:
        return parser.parse(code), source_bytes


class LanguageAdapter(ABC):
    def __init__(self, language: str):
        self.language = language
        self.parser = get_parser(language)

    def extract_symbols(self, code: str) -> list[Symbol]:
        tree, source_bytes = _parse(self.parser, code)
        root = _root_node(tree)

        symbols = []

        def visit(node):
            if self.is_function(node):
                symbols.append(self.extract_function(node, source_bytes))

            elif self.is_class(node):
                symbols.append(self.extract_class(node, source_bytes))

            for i in range(_child_count(node)):
                child = node.child(i)
                if child is not None:
                    visit(child)

        visit(root)
        return symbols

    @abstractmethod
    def is_function(self, node) -> bool:
        pass

    @abstractmethod
    def is_class(self, node) -> bool:
        pass

    def node_kind(self, node) -> str:
        return _node_kind(node)

    def slice_node(self, node, source_bytes: bytes) -> str:
        return source_bytes[_start_byte(node) : _end_byte(node)].decode("utf8")

    def get_name(self, node, source_bytes: bytes) -> str:
        name_node = node.child_by_field_name("name")

        if name_node is None:
            return "<unknown>"
        return self.slice_node(name_node, source_bytes)

    def get_signature(self, node, source_bytes: bytes) -> str:
        text = self.slice_node(node, source_bytes)
        return text.split("\n", 1)[0].strip()

    def extract_function(self, node, source_bytes: bytes) -> Symbol:
        start = _start_point(node)
        end = _end_point(node)

        return Symbol(
            kind="function",
            name=self.get_name(node, source_bytes),
            signature=self.get_signature(node, source_bytes),
            start=_start_byte(node),
            end=_end_byte(node),
            start_line=_point_row(start) + 1,
            end_line=_point_row(end) + 1,
        )

    def extract_class(self, node, source_bytes: bytes) -> Symbol:
        start = _start_point(node)
        end = _end_point(node)

        return Symbol(
            kind="class",
            name=self.get_name(node, source_bytes),
            signature=self.get_signature(node, source_bytes),
            start=_start_byte(node),
            end=_end_byte(node),
            start_line=_point_row(start) + 1,
            end_line=_point_row(end) + 1,
        )
