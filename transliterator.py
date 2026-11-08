"""
Universal Indic to Romanized English Transliteration Engine
Supports: Telugu, Hindi (Devanagari), Tamil, Kannada, Malayalam, Bengali, Gujarati, Punjabi, Marathi.
Converts native regional speech text into natural, readable English Latin script (e.g. "హాయ్ రా తిన్నావా?" -> "Hi ra tinnava?").
100% Free, zero external dependencies, sub-millisecond execution.
"""

from typing import Tuple, Dict

# Unicode ranges for Indic Brahmic scripts
INDIC_RANGES = [
    (0x0900, 0x097F, "hi"),  # Devanagari (Hindi, Marathi, Nepali)
    (0x0980, 0x09FF, "bn"),  # Bengali / Assamese
    (0x0A00, 0x0A7F, "pa"),  # Gurmukhi (Punjabi)
    (0x0A80, 0x0AFF, "gu"),  # Gujarati
    (0x0B00, 0x0B7F, "or"),  # Odia
    (0x0B80, 0x0BFF, "ta"),  # Tamil
    (0x0C00, 0x0C7F, "te"),  # Telugu
    (0x0C80, 0x0CFF, "kn"),  # Kannada
    (0x0D00, 0x0D7F, "ml"),  # Malayalam
]

# Brahmic relative offset phonetic mappings (offset = ord(char) - base)
INDEPENDENT_VOWELS = {
    0x05: "a",
    0x06: "aa",
    0x07: "i",
    0x08: "ee",
    0x09: "u",
    0x0A: "oo",
    0x0B: "ru",
    0x0E: "e",
    0x0F: "e",
    0x10: "ai",
    0x12: "o",
    0x13: "o",
    0x14: "au",
}

DEPENDENT_MATRAS = {
    0x3E: "aa",
    0x3F: "i",
    0x40: "ee",
    0x41: "u",
    0x42: "oo",
    0x43: "ru",
    0x46: "e",
    0x47: "e",
    0x48: "ai",
    0x4A: "o",
    0x4B: "o",
    0x4C: "au",
}

CONSONANTS = {
    0x15: "k",  0x16: "kh", 0x17: "g",  0x18: "gh", 0x19: "ng",
    0x1A: "ch", 0x1B: "chh", 0x1C: "j", 0x1D: "jh", 0x1E: "ny",
    0x1F: "t",  0x20: "th", 0x21: "d",  0x22: "dh", 0x23: "n",
    0x24: "t",  0x25: "th", 0x26: "d",  0x27: "dh", 0x28: "n",
    0x2A: "p",  0x2B: "ph", 0x2C: "b",  0x2D: "bh", 0x2E: "m",
    0x2F: "y",  0x30: "r",  0x31: "r",  0x32: "l",  0x33: "l",
    0x34: "l",  0x35: "v",  0x36: "sh", 0x37: "sh", 0x38: "s",
    0x39: "h",  0x58: "q",  0x59: "kh", 0x5A: "gh", 0x5B: "z",
    0x5C: "d",  0x5D: "dh", 0x5E: "f",  0x5F: "y",
}

VIRAMA_OFFSET = 0x4D
ANUSVARA_OFFSET = 0x02
VISARGA_OFFSET = 0x03
NUKTA_OFFSET = 0x3C

# Common colloquial Indian slang dictionary for natural conversions (e.g. "హాయ్" -> "Hi", "రా" -> "ra")
COLLOQUIAL_MAP: Dict[str, str] = {
    "హాయ్": "Hi",
    "హలో": "Hello",
    "రా": "ra",
    "తిన్నావా": "tinnava",
    "తిన్నారా": "tinnara",
    "ఎలా": "ela",
    "ఉన్నావు": "unnavu",
    "ఉన్నారు": "unnaru",
    "బాగున్నాను": "bagunnanu",
    "బాగున్నారా": "bagunnara",
    "ఏంటి": "enti",
    "సంగతులు": "sangatulu",
    "నమస్తే": "Namaste",
    "ధన్యవాదాలు": "Dhanyavadalu",
    "అవును": "avunu",
    "కాదు": "kaadu",
    "नमस्ते": "Namaste",
    "हाँ": "Haan",
    "नहीं": "Nahi",
    "क्या": "Kya",
    "हाल": "haal",
    "है": "hai",
    "कैसा": "kaisa",
    "कैसी": "kaisi",
    "हो": "ho",
    "வணக்கம்": "Vanakkam",
    "ನಮಸ್ಕಾರ": "Namaskara",
}

def detect_indic_script(text: str) -> str:
    """Detects whether text contains Indic scripts and returns the ISO language code (e.g. 'te', 'hi', 'ta')."""
    counts: Dict[str, int] = {}
    for ch in text:
        cp = ord(ch)
        for start, end, code in INDIC_RANGES:
            if start <= cp <= end:
                counts[code] = counts.get(code, 0) + 1
                break
    if not counts:
        return "en"
    return max(counts, key=counts.get)

def transliterate_indic_word(word: str) -> str:
    """Transliterates a single Indic word into natural phonetic Romanized English script."""
    clean_word = word.strip(".,!?:;\"'()[]{}/-")
    punct_suffix = word[len(clean_word):] if len(clean_word) < len(word) else ""
    
    if clean_word in COLLOQUIAL_MAP:
        return COLLOQUIAL_MAP[clean_word] + punct_suffix

    out = []
    i = 0
    n = len(clean_word)

    while i < n:
        ch = clean_word[i]
        cp = ord(ch)
        
        # Check which Indic block this character belongs to
        block_base = None
        for start, end, _ in INDIC_RANGES:
            if start <= cp <= end:
                block_base = start
                break
        
        if block_base is None:
            # Non-Indic character (Latin, punctuation, number, emoji)
            out.append(ch)
            i += 1
            continue

        offset = cp - block_base

        if offset in INDEPENDENT_VOWELS:
            out.append(INDEPENDENT_VOWELS[offset])
            i += 1
        elif offset in CONSONANTS:
            cons = CONSONANTS[offset]
            # Check next character to determine vowel or halant
            if i + 1 < n:
                next_cp = ord(clean_word[i + 1])
                next_offset = next_cp - block_base
                if next_offset == VIRAMA_OFFSET:
                    # Halant suppresses inherent 'a'
                    out.append(cons)
                    i += 2
                    continue
                elif next_offset in DEPENDENT_MATRAS:
                    # Dependent vowel
                    matra = DEPENDENT_MATRAS[next_offset]
                    out.append(cons + matra)
                    i += 2
                    continue
                elif next_offset == ANUSVARA_OFFSET:
                    out.append(cons + "am")
                    i += 2
                    continue
                elif next_offset == VISARGA_OFFSET:
                    out.append(cons + "ah")
                    i += 2
                    continue
            # End of word consonant or followed by another consonant -> inherent 'a'
            # In colloquial Telugu/Hindi, final consonant often has soft vowel or natural ending
            if i + 1 == n:
                # Word-final consonant in Telugu usually has short 'u' or soft 'a'
                out.append(cons)
            else:
                out.append(cons + "a")
            i += 1
        elif offset in DEPENDENT_MATRAS:
            out.append(DEPENDENT_MATRAS[offset])
            i += 1
        elif offset == ANUSVARA_OFFSET:
            out.append("m")
            i += 1
        elif offset == VISARGA_OFFSET:
            out.append("h")
            i += 1
        elif offset == VIRAMA_OFFSET:
            # Standalone virama
            i += 1
        else:
            i += 1

    result = "".join(out)
    # Simplify double vowels like 'aa' at end of word to single 'a' for conversational readability
    # e.g. "tinnavaa" -> "tinnava"
    if result.endswith("aa"):
        result = result[:-2] + "a"
    return result + punct_suffix

def to_romanized(text: str) -> Tuple[str, str]:
    """
    Universal Transliteration function.
    Returns: (romanized_text, detected_language)
    Example: to_romanized("హాయ్ రా తిన్నావా?") -> ("Hi ra tinnava?", "te")
    """
    if not text or not text.strip():
        return text, "en"
    
    lang = detect_indic_script(text)
    if lang == "en":
        return text, "en"

    words = text.split(" ")
    romanized_words = [transliterate_indic_word(w) for w in words]
    romanized_text = " ".join(romanized_words)
    
    # Capitalize first letter of sentence if applicable
    if romanized_text and romanized_text[0].islower():
        romanized_text = romanized_text[0].upper() + romanized_text[1:]

    return romanized_text, lang
