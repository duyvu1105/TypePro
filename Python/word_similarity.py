from difflib import SequenceMatcher

def similarity_difflib(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

word1 = "reverse"
word2 = "Reversible"
print(similarity_difflib(word1, word2))

