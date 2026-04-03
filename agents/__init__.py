# agents/__init__.py
# Los agentes se importan directamente por nombre en el orquestador.
# Aquí se registran los disponibles en cada fase.

from agents import web_agent, youtube_agent, instagram_agent, instagram_stories_agent, facebook_agent

__all__ = ["web_agent", "youtube_agent", "instagram_agent", "instagram_stories_agent", "facebook_agent"]
