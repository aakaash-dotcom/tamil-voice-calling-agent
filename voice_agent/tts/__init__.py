"""voice_agent.tts — Text-to-Speech subsystem."""
from .edge_tts import EdgeTTS, get_tts, TTSError

__all__ = ["EdgeTTS", "get_tts", "TTSError"]
