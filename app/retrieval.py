"""Fragmentación por palabras para la práctica local de recuperación."""


def chunk_text(text: str, size: int = 120, overlap: int = 20) -> list[str]:
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError('Se necesita size > 0 y 0 <= overlap < size')
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        chunks.append(' '.join(words[start:start + size]))
        if start + size >= len(words):
            break
        start += size - overlap
    return chunks


def literal_query(q: str) -> str:
    terms = q.split()
    if not terms:
        raise ValueError('Introduce al menos una palabra')
    return ' AND '.join('"' + term.replace('"', '""') + '"' for term in terms)
