import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from scripts.agent.memory import (
    save_session,
    load_session,
    get_list_of_sessions,
    remove_session,
)


class TestMemoryFunctions(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.session_id = uuid4()
        self.conversation = [{"role": "user", "content": "Hello"}]

    def tearDown(self):
        for file in self.temp_dir.iterdir():
            file.unlink()
        self.temp_dir.rmdir()

    def test_save_and_load_session(self):
        sid = save_session(self.conversation, self.session_id, self.temp_dir)
        self.assertEqual(sid, self.session_id)
        loaded = load_session(self.session_id, self.temp_dir)
        self.assertEqual(loaded, self.conversation)

    def test_save_appends_conversation(self):
        save_session(self.conversation, self.session_id, self.temp_dir)
        more = [{"role": "assistant", "content": "Hi"}]
        save_session(more, self.session_id, self.temp_dir)
        loaded = load_session(self.session_id, self.temp_dir)
        self.assertEqual(len(loaded), 2)

    def test_load_nonexistent_session(self):
        loaded = load_session(uuid4(), self.temp_dir)
        self.assertEqual(loaded, [])

    def test_get_list_of_sessions(self):
        save_session(self.conversation, self.session_id, self.temp_dir)
        sessions = get_list_of_sessions(self.temp_dir)
        self.assertEqual(len(sessions), 1)
        self.assertTrue(isinstance(sessions[0][0], Path))
        self.assertTrue(isinstance(sessions[0][1], float))

    def test_remove_session(self):
        save_session(self.conversation, self.session_id, self.temp_dir)
        removed = remove_session(self.session_id, self.temp_dir)
        self.assertTrue(removed)
        self.assertFalse((self.temp_dir / str(self.session_id)).exists())

    def test_remove_nonexistent_session(self):
        removed = remove_session(uuid4(), self.temp_dir)
        self.assertFalse(removed)


if __name__ == "__main__":
    unittest.main()
