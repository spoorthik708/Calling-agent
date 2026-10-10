import pytest
from app.voice.audio import AudioEncoding, AudioFrame
from app.voice.turn_detector import TurnDetector, TurnEvent
from app.voice.vad import EnergyVAD, MockVAD


def test_energy_vad_speech_detection():
    vad = EnergyVAD(energy_threshold=100.0)

    # 1. Pure silence (all zero bytes)
    silent_payload = b"\x00" * 640
    silent_frame = AudioFrame(
        payload=silent_payload,
        encoding=AudioEncoding.PCM_S16LE,
        sample_rate=16000,
        channels=1,
    )
    result_silent = vad.is_speech(silent_frame)
    assert result_silent.is_speech is False
    assert result_silent.confidence < 0.1

    # 2. Loud synthetic tone (large amplitude 16-bit values)
    import struct
    loud_samples = [10000, -10000] * 160
    loud_payload = struct.pack(f"<{len(loud_samples)}h", *loud_samples)
    loud_frame = AudioFrame(
        payload=loud_payload,
        encoding=AudioEncoding.PCM_S16LE,
        sample_rate=16000,
        channels=1,
    )
    result_loud = vad.is_speech(loud_frame)
    assert result_loud.is_speech is True
    assert result_loud.confidence > 0.5


def test_mock_vad_controllable():
    vad = MockVAD(default_speech=False)
    frame = AudioFrame(payload=b"\x00" * 640)
    assert vad.is_speech(frame).is_speech is False

    vad.set_speech_state(True)
    assert vad.is_speech(frame).is_speech is True


def test_turn_detector_full_lifecycle():
    detector = TurnDetector(
        silence_timeout_seconds=0.5,
        min_speech_duration_seconds=0.04,
        max_turn_duration_seconds=10.0,
    )

    frame_20ms = AudioFrame(payload=b"\x00" * 640, duration_ms=20.0)

    # 1. Initial silence
    event = detector.process_frame(frame_20ms, is_speech=False)
    assert event is None

    # 2. Speech begins: frame 1 (20ms) -> speech accum = 20ms (< 40ms min)
    event1 = detector.process_frame(frame_20ms, is_speech=True)
    # 3. Speech frame 2 (20ms) -> speech accum = 40ms (>= 40ms min) -> USER_STARTED_SPEAKING
    event2 = detector.process_frame(frame_20ms, is_speech=True)
    assert event2 == TurnEvent.USER_STARTED_SPEAKING

    # 4. Continued speech -> USER_CONTINUES
    event3 = detector.process_frame(frame_20ms, is_speech=True)
    assert event3 == TurnEvent.USER_CONTINUES

    # 5. User stops speaking -> USER_STOPPED_SPEAKING
    event4 = detector.process_frame(frame_20ms, is_speech=False)
    assert event4 == TurnEvent.USER_STOPPED_SPEAKING

    # 6. Silence continues for > 0.5s (25 frames of 20ms = 500ms)
    final_event = None
    for _ in range(25):
        evt = detector.process_frame(frame_20ms, is_speech=False)
        if evt == TurnEvent.TURN_COMPLETE:
            final_event = evt
            break

    assert final_event == TurnEvent.TURN_COMPLETE


def test_turn_detector_max_turn_duration_cutoff():
    # Enforce bounding: user speaking indefinitely must trigger TURN_COMPLETE
    detector = TurnDetector(
        silence_timeout_seconds=1.0,
        min_speech_duration_seconds=0.02,
        max_turn_duration_seconds=1.0,  # 1 second max
    )

    frame_100ms = AudioFrame(payload=b"\x00" * 3200, duration_ms=100.0)

    # First speech frame
    detector.process_frame(frame_100ms, is_speech=True)

    # Feed 10 more 100ms speech frames (total 1.1s > 1.0s max)
    completed_event = None
    for _ in range(10):
        evt = detector.process_frame(frame_100ms, is_speech=True)
        if evt == TurnEvent.TURN_COMPLETE:
            completed_event = evt
            break

    assert completed_event == TurnEvent.TURN_COMPLETE
