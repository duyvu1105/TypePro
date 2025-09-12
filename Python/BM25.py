import math
from collections import Counter
from typing import Iterable, Optional

def bm25_similarity(
    text1: str,
    text2: str,
    k1: float = 1.5,
    b: float = 0.75,
    *,
    # normalization options
    normalize: bool = True,
    method: str = "s_over_splusc",  # 's_over_splusc' | 'one_minus_exp' | 'sigmoid'
    c: float = 1.0,                 # for s/(s+c)
    alpha: Optional[float] = None,  # for one_minus_exp; default = 1/avgdl
    sigmoid_a: Optional[float] = None,  # for sigmoid slope
    sigmoid_b: Optional[float] = None,  # for sigmoid intercept
    return_raw: bool = False        # if True, return raw BM25 (unnormalized)
) -> float:
    """
    Compute symmetric BM25 similarity between two texts and (optionally) normalize to [0,1].

    Default normalization: s / (s + c) (monotonic, preserves ranking).
    Alternatives:
      - 'one_minus_exp': 1 - exp(-alpha * s)  (alpha default 1/avgdl)
      - 'sigmoid': sigmoid(a * s + b) remapped so s=0 -> 0 and s->inf -> 1

    Returns:
      float in [0,1] (unless return_raw=True then returns raw BM25 score).
    """

    # --- tokenize (simple whitespace)
    tokens1 = text1.split()
    tokens2 = text2.split()
    docs = [tokens1, tokens2]
    N = len(docs)

    # handle empty docs
    if len(tokens1) == 0 and len(tokens2) == 0:
        return 1.0 if not return_raw else 0.0

    # --- document frequencies
    all_terms = set(tokens1 + tokens2)
    df = {term: sum(1 for doc in docs if term in doc) for term in all_terms}

    # --- avg doc length
    avgdl = sum(len(doc) for doc in docs) / N if N > 0 else 0.0

    # --- idf with small smoothing (same formula as original)
    idf = {term: math.log((N - freq + 0.5) / (freq + 0.5) + 1) for term, freq in df.items()}

    def score(query_tokens: Iterable[str], doc_tokens: Iterable[str]) -> float:
        doc_len = len(list(doc_tokens))
        freq = Counter(doc_tokens)
        s = 0.0
        for term in query_tokens:
            f = freq.get(term, 0)
            if f == 0:
                continue
            numerator = f * (k1 + 1)
            denominator = f + k1 * (1 - b + b * doc_len / (avgdl if avgdl > 0 else 1.0))
            s += idf.get(term, 0.0) * (numerator / denominator)
        return s

    # symmetric BM25 (average of both directions)
    score12 = score(tokens1, tokens2)
    score21 = score(tokens2, tokens1)
    raw = (score12 + score21) / 2.0

    if return_raw:
        return raw

    # normalization
    eps = 1e-12
    if raw <= 0:
        return 0.0

    method = method.lower()
    if method == "s_over_splusc":
        # default c = 1.0 (you can choose c = mean/median of a sample of raw scores)
        return raw / (raw + max(c, eps))

    elif method == "one_minus_exp":
        # default alpha = 1/avgdl (fallback to 1.0 if avgdl == 0)
        a = alpha if (alpha is not None) else (1.0 / avgdl if avgdl > 0 else 1.0)
        return 1.0 - math.exp(-a * raw)

    elif method == "sigmoid":
        # default a = 1/avgdl, b = 0
        a = sigmoid_a if (sigmoid_a is not None) else (1.0 / avgdl if avgdl > 0 else 1.0)
        b = sigmoid_b if (sigmoid_b is not None) else 0.0
        sigmoid = lambda x: 1.0 / (1.0 + math.exp(-x))
        s_val = sigmoid(a * raw + b)
        s0 = sigmoid(b)  # value at raw==0
        # remap [s0, 1) -> [0, 1)
        return (s_val - s0) / (1.0 - s0 + eps)

    else:
        # unknown method -> fallback to s/(s+c)
        return raw / (raw + max(c, eps))
