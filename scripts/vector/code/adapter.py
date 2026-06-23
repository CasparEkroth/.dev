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


class LanguageAdapter(ABC):
    def __init__(self, language: str):
        self.language = language
        self.parser = get_parser(language)

    def extract_symbols(self, code: str) -> list[Symbol]:
        tree = self.parser.parse(code)
        root = tree.root_node()

        symbols = []

        def visit(node):
            if self.is_function(node):
                symbols.append(self.extract_function(node, code))

            elif self.is_class(node):
                symbols.append(self.extract_class(node, code))

            for i in range(node.child_count()):
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

    def slice_node(self, node, source: str) -> str:
        return source.encode("utf8")[node.start_byte():node.end_byte()].decode("utf8")

    def get_name(self, node, source: str) -> str:
        name_node = node.child_by_field_name("name")

        if name_node is None:
            return "<unknown>"
        return self.slice_node(name_node, source)

    def get_signature(self, node, source: str) -> str:
        text = self.slice_node(node, source)
        return text.split("\n", 1)[0].strip()

    def extract_function(self, node, source: str) -> Symbol:
        start = node.start_position()
        end = node.end_position()

        return Symbol(
            kind="function",
            name=self.get_name(node, source),
            signature=self.get_signature(node, source),
            start=node.start_byte(),
            end=node.end_byte(),
            start_line=start.row + 1,
            end_line=end.row + 1,
        )

    def extract_class(self, node, source: str) -> Symbol:
        start = node.start_position()
        end = node.end_position()

        return Symbol(
            kind="class",
            name=self.get_name(node, source),
            signature=self.get_signature(node, source),
            start=node.start_byte(),
            end=node.end_byte(),
            start_line=start.row + 1,
            end_line=end.row + 1,
        )

