from __future__ import annotations

from scripts.vector.code.adapter import LanguageAdapter

# Path.suffix is dotted (".py"); accept both forms via resolve_language().
SUFFIX_TO_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".java": "java",
    # Bare forms kept for callers that strip the leading dot themselves.
    "py": "python",
    "js": "javascript",
    "java": "java",
}


def resolve_language(suffix: str) -> str | None:
    """Map a file suffix (with or without leading ``.``) to a language id."""
    if not suffix:
        return None
    return SUFFIX_TO_LANG.get(suffix) or SUFFIX_TO_LANG.get(suffix.lstrip("."))


def get_adapter(language: str) -> LanguageAdapter:
    adapters = {
        "python": PythonAdapter,
        "javascript": JavaScriptAdapter,
        "java": JavaAdapter,
    }

    adapter_cls = adapters.get(language)

    if adapter_cls is None:
        raise ValueError(f"No adapter found for language: {language}")

    return adapter_cls()


class PythonAdapter(LanguageAdapter):
    def __init__(self):
        super().__init__("python")

    def is_function(self, node) -> bool:
        return self.node_kind(node) == "function_definition"

    def is_class(self, node) -> bool:
        return self.node_kind(node) == "class_definition"


class JavaAdapter(LanguageAdapter):
    def __init__(self):
        super().__init__("java")

    def is_function(self, node) -> bool:
        return self.node_kind(node) in {
            "method_declaration",
            "constructor_declaration",
        }

    def is_class(self, node) -> bool:
        return self.node_kind(node) in {
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
        }


class JavaScriptAdapter(LanguageAdapter):
    def __init__(self):
        super().__init__("javascript")

    def is_function(self, node) -> bool:
        return self.node_kind(node) in {
            "function_declaration",
            "method_definition",
            "arrow_function",
        }

    def is_class(self, node) -> bool:
        return self.node_kind(node) == "class_declaration"
