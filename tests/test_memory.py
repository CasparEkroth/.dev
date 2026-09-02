import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from scripts.amon.memory import (
    save_session,
    load_session,
    get_list_of_sessions,
    remove_session,
    save_todos,
    load_todos,
    save_context_tokens,
    load_context_tokens,
    save_session_info,
    load_session_info,
    save_session_cwd,
    load_session_cwd,
    append_event,
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

    def test_save_and_load_todos(self):
        todos = [{"content": "step one", "status": "in_progress"}]
        save_todos(self.session_id, todos, self.temp_dir)
        self.assertEqual(load_todos(self.session_id, self.temp_dir), todos)

    def test_load_todos_for_unknown_session_is_empty(self):
        self.assertEqual(load_todos(uuid4(), self.temp_dir), [])

    def test_save_todos_overwrites_not_appends(self):
        save_todos(
            self.session_id, [{"content": "a", "status": "pending"}], self.temp_dir
        )
        save_todos(
            self.session_id, [{"content": "b", "status": "pending"}], self.temp_dir
        )
        loaded = load_todos(self.session_id, self.temp_dir)
        self.assertEqual(loaded, [{"content": "b", "status": "pending"}])

    def test_todos_sidecar_excluded_from_session_list(self):
        save_session(self.conversation, self.session_id, self.temp_dir)
        save_todos(
            self.session_id, [{"content": "a", "status": "pending"}], self.temp_dir
        )
        sessions = get_list_of_sessions(self.temp_dir)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0][0].name, str(self.session_id))

    def test_get_list_of_sessions_ignores_non_uuid_stray_files(self):
        save_session(self.conversation, self.session_id, self.temp_dir)
        (self.temp_dir / "notes.txt").write_text("not a session")
        (self.temp_dir / ".DS_Store").write_text("")
        sessions = get_list_of_sessions(self.temp_dir)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0][0].name, str(self.session_id))

    def test_remove_session_also_removes_todos_sidecar(self):
        save_session(self.conversation, self.session_id, self.temp_dir)
        save_todos(
            self.session_id, [{"content": "a", "status": "pending"}], self.temp_dir
        )
        remove_session(self.session_id, self.temp_dir)
        self.assertEqual(load_todos(self.session_id, self.temp_dir), [])
        self.assertFalse((self.temp_dir / f"{self.session_id}.todos.json").exists())

    def test_save_session_info_and_load_it_back(self):
        save_session_info(
            self.session_id, self.temp_dir, agent="dev", preview="fix the login bug"
        )
        info = load_session_info(self.session_id, self.temp_dir)
        self.assertEqual(info["agent"], "dev")
        self.assertEqual(info["preview"], "fix the login bug")

    def test_session_info_does_not_clobber_context_tokens(self):
        save_context_tokens(self.session_id, 4242, self.temp_dir)
        save_session_info(self.session_id, self.temp_dir, agent="dev", preview="x")
        self.assertEqual(load_context_tokens(self.session_id, self.temp_dir), 4242)
        self.assertEqual(
            load_session_info(self.session_id, self.temp_dir)["agent"], "dev"
        )

    def test_context_tokens_does_not_clobber_session_info(self):
        save_session_info(self.session_id, self.temp_dir, agent="dev", preview="x")
        save_context_tokens(self.session_id, 10, self.temp_dir)
        info = load_session_info(self.session_id, self.temp_dir)
        self.assertEqual(info["agent"], "dev")
        self.assertEqual(info["preview"], "x")

    def test_load_session_info_for_unknown_session_is_empty(self):
        info = load_session_info(uuid4(), self.temp_dir)
        self.assertIsNone(info["agent"])
        self.assertIsNone(info["preview"])

    def test_save_session_cwd_and_load_it_back(self):
        save_session_cwd(self.session_id, "/work/src", self.temp_dir)
        self.assertEqual(load_session_cwd(self.session_id, self.temp_dir), "/work/src")

    def test_load_session_cwd_for_unknown_session_is_none(self):
        self.assertIsNone(load_session_cwd(uuid4(), self.temp_dir))

    def test_session_cwd_does_not_clobber_session_info(self):
        save_session_info(self.session_id, self.temp_dir, agent="dev", preview="x")
        save_session_cwd(self.session_id, "/work/src", self.temp_dir)
        info = load_session_info(self.session_id, self.temp_dir)
        self.assertEqual(info["agent"], "dev")
        self.assertEqual(load_session_cwd(self.session_id, self.temp_dir), "/work/src")

    def test_append_event_writes_one_jsonl_line(self):
        import json

        append_event(self.session_id, {"event": "turn", "turn": 1}, self.temp_dir)
        path = self.temp_dir / f"{self.session_id}.events.jsonl"
        lines = path.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), {"event": "turn", "turn": 1})

    def test_append_event_appends_not_overwrites(self):
        append_event(self.session_id, {"event": "turn", "turn": 1}, self.temp_dir)
        append_event(self.session_id, {"event": "turn", "turn": 2}, self.temp_dir)
        path = self.temp_dir / f"{self.session_id}.events.jsonl"
        self.assertEqual(len(path.read_text().splitlines()), 2)

    def test_events_jsonl_excluded_from_session_list(self):
        save_session(self.conversation, self.session_id, self.temp_dir)
        append_event(self.session_id, {"event": "turn"}, self.temp_dir)
        sessions = get_list_of_sessions(self.temp_dir)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0][0].name, str(self.session_id))

    def test_remove_session_also_removes_events_jsonl(self):
        save_session(self.conversation, self.session_id, self.temp_dir)
        append_event(self.session_id, {"event": "turn"}, self.temp_dir)
        remove_session(self.session_id, self.temp_dir)
        self.assertFalse((self.temp_dir / f"{self.session_id}.events.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
