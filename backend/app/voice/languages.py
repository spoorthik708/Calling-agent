"""Language Foundation for YAVURA Voice Layer.

Explicitly models supported languages for STT, LLM, and TTS:
- English (en)
- Hindi (hi)
- Telugu (te)
- Tamil (ta)

Architecture is extensible to additional regional and international languages.
"""

from enum import Enum
from typing import Optional, Set


class VoiceLanguage(str, Enum):
    ENGLISH = "en"
    HINDI = "hi"
    TELUGU = "te"
    TAMIL = "ta"

    # Convenient short aliases
    EN = "en"
    HI = "hi"
    TE = "te"
    TA = "ta"


SUPPORTED_VOICE_LANGUAGES: Set[str] = {
    VoiceLanguage.ENGLISH.value,
    VoiceLanguage.HINDI.value,
    VoiceLanguage.TELUGU.value,
    VoiceLanguage.TAMIL.value,
}


def normalize_voice_language(language_code: Optional[str]) -> str:
    """
    Validates and normalizes incoming language code.
    Defaults to English ('en') if unspecified.
    Raises ValueError if language is unsupported.
    """
    if not language_code:
        return VoiceLanguage.ENGLISH.value

    norm = language_code.strip().lower()
    # Normalize variants like 'en-US' -> 'en', 'hi-IN' -> 'hi', 'te-IN' -> 'te', 'ta-IN' -> 'ta'
    base_code = norm.split("-")[0].split("_")[0]
    if base_code not in SUPPORTED_VOICE_LANGUAGES:
        raise ValueError(
            f"Voice language '{language_code}' is not supported. "
            f"Approved languages: {sorted(list(SUPPORTED_VOICE_LANGUAGES))}"
        )
    return base_code
