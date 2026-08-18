"""voice_agent.tools — Tool dispatcher for LLM function calls."""
from .whatsapp import WhatsAppDispatcher, dispatch_tool_call, get_whatsapp

__all__ = ["WhatsAppDispatcher", "dispatch_tool_call", "get_whatsapp"]
