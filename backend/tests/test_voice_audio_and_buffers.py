import pytest
from app.core.exceptions import AudioBufferOverflowError
from app.voice.audio import AudioEncoding, AudioFrame, BoundedAudioBuffer


def test_audio_frame_duration_calculation():
    # 16000 Hz, 1 channel, 16-bit PCM = 32000 bytes per second = 32 bytes per ms
    # 640 bytes = 20 ms
    payload = b"\x00" * 640
    frame = AudioFrame(
        payload=payload,
        encoding=AudioEncoding.PCM_S16LE,
        sample_rate=16000,
        channels=1,
    )
    assert frame.duration_ms == pytest.approx(20.0, rel=1e-2)


@pytest.mark.asyncio
async def test_bounded_audio_buffer_normal_push_and_drain():
    buffer = BoundedAudioBuffer(
        max_chunk_bytes=1024,
        max_buffer_bytes=4096,
        max_queue_size=10,
    )

    frame1 = AudioFrame(payload=b"\x01" * 500)
    frame2 = AudioFrame(payload=b"\x02" * 500)

    await buffer.push(frame1)
    await buffer.push(frame2)

    assert buffer.queue_size == 2
    assert buffer.total_buffered_bytes == 1000

    drained = buffer.drain()
    assert len(drained) == 2
    assert buffer.queue_size == 0
    assert buffer.total_buffered_bytes == 0


@pytest.mark.asyncio
async def test_bounded_audio_buffer_rejects_oversized_chunk():
    buffer = BoundedAudioBuffer(
        max_chunk_bytes=512,
        max_buffer_bytes=4096,
        max_queue_size=10,
    )

    oversized_frame = AudioFrame(payload=b"\x00" * 1024)
    with pytest.raises(AudioBufferOverflowError) as exc_info:
        await buffer.push(oversized_frame)

    assert "exceeds maximum allowed" in exc_info.value.message


@pytest.mark.asyncio
async def test_bounded_audio_buffer_rejects_memory_overflow():
    buffer = BoundedAudioBuffer(
        max_chunk_bytes=512,
        max_buffer_bytes=1000,
        max_queue_size=10,
    )

    await buffer.push(AudioFrame(payload=b"\x00" * 500))
    await buffer.push(AudioFrame(payload=b"\x00" * 400))

    # Pushing 200 more bytes would exceed 1000 max bytes
    with pytest.raises(AudioBufferOverflowError) as exc_info:
        await buffer.push(AudioFrame(payload=b"\x00" * 200))

    assert "Audio buffer total memory limit exceeded" in exc_info.value.message


@pytest.mark.asyncio
async def test_bounded_audio_buffer_queue_size_limit():
    buffer = BoundedAudioBuffer(
        max_chunk_bytes=512,
        max_buffer_bytes=4096,
        max_queue_size=2,
    )

    await buffer.push(AudioFrame(payload=b"\x00" * 10))
    await buffer.push(AudioFrame(payload=b"\x00" * 10))

    # 3rd item exceeds max queue size of 2
    with pytest.raises(AudioBufferOverflowError) as exc_info:
        await buffer.push(AudioFrame(payload=b"\x00" * 10))

    assert "queue limit exceeded" in exc_info.value.message
