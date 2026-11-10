"""Container decoding must never reinterpret compressed bytes as PCM samples."""
import io
import struct
import subprocess
import unittest
import wave
from unittest import mock

from hermes_gaze.audio import voice

try:
    import numpy as np
except ImportError:
    np = None


@unittest.skipIf(np is None, "numpy not installed")
class TestAudioDecode(unittest.TestCase):
    def test_rejected_containers_never_become_pcm_noise(self):
        # Test both parities: odd lengths used to crash; even lengths became noise.
        for payload, mime in ((b"\x1aE\xdf\xa3x", None), (b"\x1aE\xdf\xa3xx", None),
                              (b"ID3xxx", None), (b"missing-header", "audio/webm;codecs=opus")):
            with self.subTest(payload=payload, mime=mime), \
                    mock.patch("shutil.which", return_value="/ffmpeg"), \
                    mock.patch("os.path.isfile", return_value=True), \
                    mock.patch("subprocess.run", side_effect=subprocess.CalledProcessError(
                        1, "ffmpeg", stderr=b"Invalid data found when processing input")):
                with self.assertRaisesRegex(ValueError, "Could not decode recorded audio: Invalid data"):
                    voice.decode_audio_to_float32(payload, mime_type=mime)

    def test_missing_decoder_never_reinterprets_browser_audio(self):
        with mock.patch("shutil.which", return_value=None), \
                mock.patch("os.path.isfile", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "requires ffmpeg"):
                voice.decode_audio_to_float32(b"\x1aE\xdf\xa3xx")

    def test_pcm_and_stereo_wav_decode_without_external_decoder(self):
        raw = struct.pack("<hhhh", -32768, 32767, 16384, -16384)
        wav = io.BytesIO()
        with wave.open(wav, "wb") as writer:
            writer.setnchannels(2)
            writer.setsampwidth(2)
            writer.setframerate(16000)
            writer.writeframes(raw)
        with mock.patch("subprocess.run", side_effect=AssertionError("PCM/WAV fast path spawned a decoder")):
            np.testing.assert_array_equal(voice.decode_audio_to_float32(raw),
                                          np.array([-1, 32767 / 32768, .5, -.5], dtype=np.float32))
            np.testing.assert_array_equal(voice.decode_audio_to_float32(wav.getvalue()),
                                          np.array([-1 / 65536, 0], dtype=np.float32))
        with self.assertRaisesRegex(ValueError, "complete 16-bit samples"):
            voice.decode_audio_to_float32(raw + b"x")


if __name__ == "__main__":
    unittest.main()
