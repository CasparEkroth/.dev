from sentence_transformers import SentenceTransformer
import json
import numpy as np

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


def embed_text(text: str) -> list[float]:
    return model.encode(text).tolist()


VECTOR_STORE = []


def add_vector(item: dict):
    """then item needs to contain [id, text, payload]"""
    vector = embed_text(item["text"])

    VECTOR_STORE.append(
        {
            "id": id(item),
            "vector": vector,
            "payload": item["payload"],
        }
    )


def save_vectors(path="vectors.json"):
    with open(path, "w") as f:
        json.dump(VECTOR_STORE, f)


def load_vectors(path="vectors.json"):
    with open(path, "r") as f:
        data = json.load(f)

    VECTOR_STORE.clear()
    VECTOR_STORE.extend(data)


def cosine_similarity(a, b):
    a = np.array(a)
    b = np.array(b)

    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def search_vectors(query: str, k: int = 10) -> list:
    query_vector = embed_text(query)

    results = []

    for item in VECTOR_STORE:
        score = cosine_similarity(query_vector, item["vector"])

        results.append({"score": score, "payload": item["payload"]})

    results.sort(key=lambda x: x["score"], reverse=True)

    return results[:k]
