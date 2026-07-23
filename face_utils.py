import cv2
import numpy as np
from insightface.app import FaceAnalysis
from numpy.linalg import norm

app = FaceAnalysis(providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0)


def bytes_to_img(b):
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)


def get_embedding(img_bytes):
    img = bytes_to_img(img_bytes)
    faces = app.get(img)
    if not faces:
        return None
    return faces[0].embedding


def cosine_similarity(a, b):
    return np.dot(a, b) / (norm(a) * norm(b))


def face_match_score(live_bytes, doc_bytes, threshold=0.45):
    e1 = get_embedding(live_bytes)
    e2 = get_embedding(doc_bytes)

    if e1 is None or e2 is None:
        return 0.0, False

    sim = cosine_similarity(e1, e2)
    score = round((sim + 1) * 50, 2)  # 0–100 scale
    return score, sim >= threshold
