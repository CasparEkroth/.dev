import unittest
import subprocess

from scripts.vector.embeddings import (
    VectorItem,
    embed_text,
    cosine_similarity,
    add_vector,
    save_vectors,
    load_vectors,
    search_vectors,
    VECTOR_STORE,
)


class TestEmbeddings(unittest.TestCase):

    def test_embed_text(self):
        vector = embed_text("hello world")

        self.assertIsInstance(vector, list)
        self.assertGreater(len(vector), 0)
        self.assertTrue(all(isinstance(x, float) for x in vector))

    def test_embed_text_is_deterministic(self):
        a = embed_text("refresh token")
        b = embed_text("refresh token")

        self.assertEqual(len(a), len(b))
        self.assertEqual(a, b)

    def test_embedding_dimension_is_consistent(self):
        a = embed_text("hello")
        b = embed_text("completely different longer text")

        self.assertEqual(len(a), len(b))

    def test_cosine_sim(self):
        a = embed_text("refresh authentication token")
        b = embed_text("renew user login token")
        c = embed_text("save application config")

        sim_ab = cosine_similarity(a, b)
        sim_ac = cosine_similarity(a, c)

        self.assertGreater(sim_ab, sim_ac)

    def test_add_vector_and_vector_search(self):
        VECTOR_STORE.clear()

        add_vector(
            VectorItem(
                id="symbol:refresh_token",
                text="Function refreshes authentication tokens",
                payload={"name": "refresh_token"},
            )
        )

        add_vector(
            VectorItem(
                id="symbol:save_config",
                text="Function saves application configuration",
                payload={"name": "save_config"},
            )
        )

        result1 = search_vectors("refresh authentication tokens", k=1)
        self.assertEqual(result1[0]["payload"]["name"], "refresh_token")

        result2 = search_vectors("save application configuration", k=1)
        self.assertEqual(result2[0]["payload"]["name"], "save_config")

    def test_save_and_load_VECTOR_STORE(self):
        path = "vectors.json"
        VECTOR_STORE.clear()

        add_vector(
            VectorItem(
                id="symbol:refresh_token",
                text="Function refreshes authentication tokens",
                payload={"name": "refresh_token"},
            )
        )

        add_vector(
            VectorItem(
                id="symbol:save_config",
                text="Function saves application configuration",
                payload={"name": "save_config"},
            )
        )

        save_vectors(path)

        VECTOR_STORE.clear()
        self.assertEqual(len(VECTOR_STORE), 0)

        load_vectors(path)

        self.assertEqual(len(VECTOR_STORE), 2)

        payload_names = [item["payload"]["name"] for item in VECTOR_STORE]

        self.assertIn("refresh_token", payload_names)
        self.assertIn("save_config", payload_names)

        subprocess.run(["rm", path])
