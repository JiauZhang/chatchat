import unicodedata

_HIDDEN_CATEGORIES = ('Cf', 'Co', 'Cn')
_HIDDEN_RANGES = (('\u200b', '\u200f'), ('\u202a', '\u202e'),
                  ('\u2066', '\u2069'), ('\ue000', '\uf8ff'))


def sanitize_unicode(text: str) -> str:
    current = text
    for _ in range(10):
        previous = current
        current = unicodedata.normalize('NFKC', current)
        current = ''.join(
            char for char in current
            if unicodedata.category(char) not in _HIDDEN_CATEGORIES
            and not any(low <= char <= high for low, high in _HIDDEN_RANGES)
            and char != '\ufeff')
        if current == previous:
            return current
    raise ValueError('unicode sanitization did not converge')
