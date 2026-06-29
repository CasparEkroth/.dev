from scripts.vector.code.adapter import LanguageAdapter

SUFFIX_TO_LANG = {"py": "python", "js": "javascript", "java": "java"}


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
        return node.kind() == "function_definition"

    def is_class(self, node) -> bool:
        return node.kind() == "class_definition"


class JavaAdapter(LanguageAdapter):
    def __init__(self):
        super().__init__("java")

    def is_function(self, node) -> bool:
        return node.kind() in {
            "method_declaration",
            "constructor_declaration",
        }

    def is_class(self, node) -> bool:
        return node.kind() in {
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
        }


class JavaScriptAdapter(LanguageAdapter):
    def __init__(self):
        super().__init__("javascript")

    def is_function(self, node) -> bool:
        return node.kind() in {
            "function_declaration",
            "method_definition",
            "arrow_function",
        }

    def is_class(self, node) -> bool:
        return node.kind() == "class_declaration"
