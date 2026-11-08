"""
Self-Hosted Universal Speech Transcriber & Language Detector
100% Free, zero third-party paid APIs, runs locally using faster-whisper and SpeechRecognition.
Supports: Any language (Telugu, Hindi, Tamil, Kannada, Malayalam, English, etc.) with auto-detection.
Includes phonetic transliteration into Romanized English script ("Hi ra tinava?").
"""

import io
import os
import wave
import tempfile
import threading
from typing import Dict, Any, Optional
import numpy as np

from transliterator import to_romanized, detect_indic_script

_model_lock = threading.Lock()
_whisper_model = None

def get_whisper_model():
    """Lazily loads faster-whisper tiny model on CPU with int8 quantization (~75MB RAM)."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    with _model_lock:
        if _whisper_model is not None:
            return _whisper_model
        try:
            from faster_whisper import WhisperModel
            print("⏳ Loading self-hosted faster-whisper model (tiny, int8)...")
            _whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
            print("✅ Self-hosted faster-whisper model loaded successfully!")
            return _whisper_model
        except Exception as e:
            print(f"⚠️ faster-whisper load notice: {e}")
            return None

def pcm16_to_wav_bytes(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """Wraps raw 16-bit PCM bytes into standard WAV format."""
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return out.getvalue()

def transcribe_audio_bytes(audio_bytes: bytes, filename: str = "audio.wav", language: Optional[str] = None) -> Dict[str, Any]:
    """
    Transcribes audio bytes into text + Romanized English script without any paid API.
    Auto-detects language if language is None or 'auto'.
    """
    if not audio_bytes:
        return {"text": "", "romanized": "", "language": "en", "success": False, "error": "Empty audio"}

    # 1. Try faster-whisper first (self-hosted offline open-source model)
    model = get_whisper_model()
    if model is not None:
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
                # If raw PCM, wrap as WAV
                if not audio_bytes.startswith(b"RIFF") and not audio_bytes.startswith(b"OggS") and not audio_bytes.startswith(b"\x1a\x45\xdf\xa3"):
                    wav_data = pcm16_to_wav_bytes(audio_bytes)
                    tmp.write(wav_data)
                else:
                    tmp.write(audio_bytes)

            try:
                lang_param = None if (not language or language == "auto") else language
                segments, info = model.transcribe(
                    tmp_path,
                    language=lang_param,
                    beam_size=3,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=400)
                )
                text_parts = [s.text.strip() for s in segments if s.text.strip()]
                full_text = " ".join(text_parts).strip()
                detected_lang = info.language if info and hasattr(info, "language") else "en"
                lang_prob = float(info.language_probability) if info and hasattr(info, "language_probability") else 1.0

                if full_text:
                    romanized_text, translit_lang = to_romanized(full_text)
                    eff_lang = translit_lang if translit_lang != "en" else detected_lang
                    return {
                        "success": True,
                        "text": full_text,
                        "romanized": romanized_text,
                        "language": eff_lang,
                        "language_probability": lang_prob,
                        "engine": "faster-whisper",
                    }
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
        except Exception as e:
            print(f"⚠️ faster-whisper transcribe notice: {e}")

    # 2. Free Fallback: speech_recognition (Google Web Speech open endpoint - 0 API key, 0 cost)
    try:
        import speech_recognition as sr
        r = sr.Recognizer()
        
        # Prepare WAV audio
        wav_data = audio_bytes if audio_bytes.startswith(b"RIFF") else pcm16_to_wav_bytes(audio_bytes)
        with io.BytesIO(wav_data) as audio_file:
            with sr.AudioFile(audio_file) as source:
                audio = r.record(source)

        # Detect candidate language: if user provided or check regional codes
        lang_code = language if language and language != "auto" else "te-IN"
        try:
            recognized_text = r.recognize_google(audio, language=lang_code)
        except Exception:
            # Fall back to English/Hindi
            recognized_text = r.recognize_google(audio, language="en-IN")

        if recognized_text:
            romanized_text, detected_lang = to_romanized(recognized_text)
            return {
                "success": True,
                "text": recognized_text,
                "romanized": romanized_text,
                "language": detected_lang,
                "engine": "speech_recognition_free",
            }
    except Exception as e:
        print(f"⚠️ speech_recognition fallback notice: {e}")

    return {
        "success": False,
        "text": "",
        "romanized": "",
        "language": "en",
        "error": "Transcription could not identify speech."
    }
