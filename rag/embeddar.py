"""
RAG Step 3 — Embedder
Convert text into vector embeddings using a local sentence-transformers model.

Flow: store.py → embedder.py (embedder is called by store, never directly by pipeline)

Rules from PIPELINE.md:
- Model: all-MiniLM-L6-v2 (384 dimensions, fast, runs on CPU)
- Load model ONCE at module level — never reload on every call
- Expose two functions only: embed_text() and embed_batch()
- Never call any external API — local model only

GPU: automatically used if available (CUDA or MPS on Apple Silicon)
     falls back to CPU silently if no GPU found
"""

import torch
import numpy as np
from sentence_transformers import SentenceTransformer

# ─────────────────────────────────────────────
# Detect best available device
# ─────────────────────────────────────────────
if torch.cuda.is_available():
    DEVICE = "cuda"           # NVIDIA GPU
elif torch.backends.mps.is_available():
    DEVICE = "mps"            # Apple Silicon GPU (M1/M2/M3)
else:
    DEVICE = "cpu"            # fallback

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384

print(f"Loading embedding model {MODEL_NAME} on {DEVICE.upper()}...", flush=True)
_model = SentenceTransformer(MODEL_NAME, device=DEVICE)
print(f"Embedding model ready on {DEVICE.upper()}.", flush=True)


def embed_text(text: str) -> np.ndarray:
    """
    Embed a single string into a 384-dimensional vector.

    Input:  any string (query, chunk text, hypothetical document)
    Output: numpy array of shape (384,)
    """
    if not text or not text.strip():
        return np.zeros(EMBEDDING_DIMENSIONS, dtype=np.float32)

    embedding = _model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
    return embedding


def embed_batch(texts: list[str]) -> np.ndarray:
    """
    Embed a list of strings in one efficient batch call.
    Much faster than calling embed_text() in a loop.
    GPU processes the whole batch in parallel.

    Input:  list of strings
    Output: numpy array of shape (len(texts), 384)
    """
    if not texts:
        return np.zeros((0, EMBEDDING_DIMENSIONS), dtype=np.float32)

    valid_texts = []
    valid_indices = []
    for i, text in enumerate(texts):
        if text and text.strip():
            valid_texts.append(text)
            valid_indices.append(i)

    if not valid_texts:
        return np.zeros((len(texts), EMBEDDING_DIMENSIONS), dtype=np.float32)

    embeddings = _model.encode(
        valid_texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        batch_size=64 if DEVICE != "cpu" else 32,  # larger batches on GPU
        show_progress_bar=False,
    )

    # Reconstruct full array with zeros for any empty inputs
    result = np.zeros((len(texts), EMBEDDING_DIMENSIONS), dtype=np.float32)
    for result_idx, original_idx in enumerate(valid_indices):
        result[original_idx] = embeddings[result_idx]

    return result


def get_device() -> str:
    """Return which device the model is running on — useful for debugging."""
    return DEVICE