import unittest
from scripts.vector.code.lang_adapters import get_adapter


class TestLangAdapters(unittest.TestCase):

    def test_python_adapter(self):
        code = """
        class UserService:
            def create_user(self, name: str):
                return {"name": name}
        """

        adapter = get_adapter("python")
        symbols = adapter.extract_symbols(code)

        self.assertEqual(len(symbols), 2)

        self.assertEqual(symbols[0].kind, "class")
        self.assertEqual(symbols[0].name, "UserService")
        self.assertEqual(symbols[0].signature, "class UserService:")

        self.assertEqual(symbols[1].kind, "function")
        self.assertEqual(symbols[1].name, "create_user")
        self.assertEqual(symbols[1].signature, "def create_user(self, name: str):")

        s1 = "Symbol(kind='class', name='UserService', signature='class UserService:', start=9, end=111, start_line=2, end_line=4)"
        s2 = "Symbol(kind='function', name='create_user', signature='def create_user(self, name: str):', start=40, end=111, start_line=3, end_line=4)"

        self.assertEqual(str(symbols[0]), s1)
        self.assertEqual(str(symbols[1]), s2)

    def test_java_adapter(self):
        code = """
        public class HelloWorld {
            public static void main(String[] args) {
                System.out.println("Hello, World");
            }
        }
        """

        adapter = get_adapter("java")
        symbols = adapter.extract_symbols(code)

        self.assertEqual(len(symbols), 2)

        self.assertEqual(symbols[0].kind, "class")
        self.assertEqual(symbols[0].name, "HelloWorld")
        self.assertEqual(symbols[0].signature, "public class HelloWorld {")

        self.assertEqual(symbols[1].kind, "function")
        self.assertEqual(symbols[1].name, "main")
        self.assertEqual(
            symbols[1].signature, "public static void main(String[] args) {"
        )

    def test_empty_file(self):
        symbols = get_adapter("python").extract_symbols("")
        self.assertEqual(symbols, [])

    def test_multiple_functions(self):
        code = """
        def a():
            pass

        def b():
            pass
        """
        symbols = get_adapter("python").extract_symbols(code)
        self.assertEqual([s.name for s in symbols], ["a", "b"])

    def test_decorated_function(self):
        code = """
        @app.route("/users")
        def get_users():
            pass
        """
        symbols = get_adapter("python").extract_symbols(code)
        self.assertEqual(symbols[0].name, "get_users")
        self.assertEqual(symbols[0].kind, "function")

    def test_async_function(self):
        code = """
        async def fetch_data():
            pass
        """
        symbols = get_adapter("python").extract_symbols(code)
        self.assertEqual(symbols[0].name, "fetch_data")
        self.assertEqual(symbols[0].kind, "function")

    def test_syntax_error_does_not_crash(self):
        code = """
        def broken(
        """
        symbols = get_adapter("python").extract_symbols(code)
        self.assertIsInstance(symbols, list)

    def test_unicode_names(self):
        code = """
        def hälsa():
            pass

        class Café:
            pass
        """
        symbols = get_adapter("python").extract_symbols(code)
        self.assertEqual([s.name for s in symbols], ["hälsa", "Café"])

    def test_nested_functions_and_classes(self):
        code = """
        class Outer:
            class Inner:
                pass

            def method(self):
                def inner_func():
                    pass
        """
        symbols = get_adapter("python").extract_symbols(code)
        self.assertEqual(
            [s.name for s in symbols],
            ["Outer", "Inner", "method", "inner_func"],
        )

    def test_fastapi_example(self):
        code = """
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/users")
        def get_users():
            return []

        class UserService:
            pass
        """
        symbols = get_adapter("python").extract_symbols(code)
        self.assertEqual(
            [s.name for s in symbols],
            ["get_users", "UserService"],
        )

    def test_large_file(self):
        code = "\n\n".join(f"def func_{i}():\n    pass" for i in range(1000))

        symbols = get_adapter("python").extract_symbols(code)

        self.assertEqual(len(symbols), 1000)
        self.assertEqual(symbols[0].name, "func_0")
        self.assertEqual(symbols[-1].name, "func_999")
