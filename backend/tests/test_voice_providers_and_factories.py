import pytest
from app.core.config import get_settings
from app.core.exceptions import VoiceConfigurationError
from app.voice.audio import AudioEncoding
from app.voice.languages import (
    SUPPORTED_VOICE_LANGUAGES,
    VoiceLanguage,
    normalize_voice_language,
)
from app.voice.stt import (
    MockSTTProvider,
    TranscriptSegment,
    get_stt_provider,
)
from app.voice.tts import (
    MockTTSProvider,
    TTSAudioChunk,
    get_tts_provider,
)
from app.voice.vad import (
    MockVAD,
    get_vad_provider,
)


def test_language_foundation_normalization():
    # Valid explicit codes
    assert normalize_voice_language("en") == "en"
    assert normalize_voice_language("hi") == "hi"
    assert normalize_voice_language("te") == "te"
    assert normalize_voice_language("ta") == "ta"

    # Regional variants normalize to base
    assert normalize_voice_language("en-US") == "en"
    assert normalize_voice_language("hi-IN") == "hi"
    assert normalize_voice_language("te-IN") == "te"
    assert normalize_voice_language("ta-IN") == "ta"

    # Default fallback
    assert normalize_voice_language(None) == "en"
    assert normalize_voice_language("") == "en"

    # Unsupported language code raises ValueError
    with pytest.raises(ValueError) as exc:
        normalize_voice_language("fr-FR")
    assert "not supported" in str(exc.value)


@pytest.mark.asyncio
async def test_mock_stt_provider_transcription():
    provider = MockSTTProvider()
    dummy_audio = b"\x00" * 3200

    segment: TranscriptSegment = await provider.transcribe_audio(
        audio_data=dummy_audio,
        encoding=AudioEncoding.PCM_S16LE,
        sample_rate=16000,
        language=VoiceLanguage.EN,
    )

    assert segment.text != ""
    assert segment.is_final is True
    assert segment.confidence > 0.9
    assert segment.language == "en"
    assert segment.latency_ms > 0.0


@pytest.mark.asyncio
async def test_mock_tts_provider_streaming():
    provider = MockTTSProvider()
    text = "Hello, your order has shipped."

    chunks = []
    async for chunk in provider.stream_synthesis(
        text=text,
        language=VoiceLanguage.EN,
        generation_id=5,
    ):
        chunks.append(chunk)

    assert len(chunks) > 0
    first_chunk: TTSAudioChunk = chunks[0]
    assert first_chunk.generation_id == 5
    assert len(first_chunk.audio_payload) > 0
    assert first_chunk.sample_rate == 16000
    assert first_chunk.encoding == AudioEncoding.PCM_S16LE


def test_provider_factories_resolution():
    stt = get_stt_provider("mock")
    assert isinstance(stt, MockSTTProvider)

    tts = get_tts_provider("mock")
    assert isinstance(tts, MockTTSProvider)

    vad = get_vad_provider("mock")
    assert isinstance(vad, MockVAD)

    with pytest.raises(VoiceConfigurationError):
        get_stt_provider("unknown_vendor")

    with pytest.raises(VoiceConfigurationError):
        get_tts_provider("unknown_vendor")


def test_production_rejects_mock_providers(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    with pytest.raises(VoiceConfigurationError) as exc_stt:
        get_stt_provider("mock")
    assert "strictly prohibited in production" in exc_stt.value.message

    with pytest.raises(VoiceConfigurationError) as exc_tts:
        get_tts_provider("mock")
    assert "strictly prohibited in production" in exc_tts.value.message

    with pytest.raises(VoiceConfigurationError) as exc_vad:
        get_vad_provider("mock")
    assert "strictly prohibited in production" in exc_vad.value.message
