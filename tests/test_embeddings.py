import unittest
from scripts.vector.embeddings import (
    embed_text,
    cosine_similarity,
    add_vector,
    save_vectors,
    load_vectors,
    search_vectors,
    VECTOR_STORE,
)
import subprocess


class TestEmbeddings(unittest.TestCase):

    def test_embed_text(self):
        vector = embed_text("hello world")

        assert isinstance(vector, list)
        assert len(vector) > 0
        assert all(isinstance(x, float) for x in vector)

    def test_embed_text_is_deterministic(self):
        a = embed_text("refresh token")
        b = embed_text("refresh token")

        assert len(a) == len(b)
        assert a == b

    def test_embedding_dimension_is_consistent(self):
        a = embed_text("hello")
        b = embed_text("completely different longer text")

        assert len(a) == len(b)

    def test_cosine_sim(self):
        a = embed_text("refresh authentication token")
        b = embed_text("renew user login token")
        c = embed_text("save application config")

        sim_ab = cosine_similarity(a, b)
        sim_ac = cosine_similarity(a, c)

        self.assertTrue(sim_ab > sim_ac)

    def test_similar_texts_are_closer_than_unrelated_texts(self):
        query = embed_text("refresh authentication token")

        similar = embed_text("renew user login token")
        unrelated = embed_text("save application config")

        assert cosine_similarity(query, similar) > cosine_similarity(query, unrelated)

    def test_add_vector_and_vector_search(self):
        VECTOR_STORE.clear()

        add_vector(
            {
                "payload": "refresh_token",
                "text": "Function refreshes authentication tokens",
            }
        )

        add_vector(
            {
                "payload": "save_config",
                "text": "Function saves application configuration",
            }
        )

        result1 = search_vectors("refresh authentication tokens", k=1)
        self.assertEqual(result1[0]["payload"], "refresh_token")

        result2 = search_vectors("save application configuration", k=1)
        self.assertEqual(result2[0]["payload"], "save_config")

    def test_save_and_load_VECTOR_STORE(self):
        path = "vectors.json"
        VECTOR_STORE.clear()

        add_vector(
            {
                "payload": "refresh_token",
                "text": "Function refreshes authentication tokens",
            }
        )

        add_vector(
            {
                "payload": "save_config",
                "text": "Function saves application configuration",
            }
        )

        save_vectors(path)

        VECTOR_STORE.clear()
        self.assertEqual(len(VECTOR_STORE), 0)

        load_vectors(path)

        self.assertEqual(len(VECTOR_STORE), 2)

        payloads = [item["payload"] for item in VECTOR_STORE]

        self.assertIn("refresh_token", payloads)
        self.assertIn("save_config", payloads)
        subprocess.run(["rm", path])
