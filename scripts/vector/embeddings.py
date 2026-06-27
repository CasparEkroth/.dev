from sentence_transformers import SentenceTransformer
import json
import numpy as np
from dataclasses import dataclass
from typing import Any
import os
from config import settings


@dataclass
class VectorItem:
    id: str
    text: str
    payload: dict[str, Any]


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_model = None


def get_model():
    global _model

    if _model is None:
        _model = SentenceTransformer(
            MODEL_NAME,
            token=settings.HF_TOKEN,
        )

    return _model


def embed_text(text: str) -> list[float]:
    model = get_model()
    return model.encode(text).tolist()


VECTOR_STORE = []


def to_jsonable(value: Any):
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, set):
        return [to_jsonable(item) for item in value]
    return value


def add_vector(item: VectorItem):
    embedding = embed_text(item.text)

    VECTOR_STORE.append(
        {
            "id": item.id,
            "text": item.text,
            "vector": embedding,
            "payload": item.payload,
        }
    )


def save_vectors(path="vectors.json"):
    dir_name = os.path.dirname(path)

    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    with open(path, "w") as f:
        json.dump(to_jsonable(VECTOR_STORE), f)


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
    if len(results) < k:
        return results

    return results[:k]
