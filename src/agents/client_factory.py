from functools import lru_cache
from agent_framework.openai import OpenAIChatClient
from src.config import config

@lru_cache(maxsize=1)
def get_chat_client() -> OpenAIChatClient:
    """
    Creates and returns a cached, reusable MAF OpenAIChatClient configured for Microsoft Foundry / Azure AI OpenAI endpoints.
    """
    if not config.foundry_api_key:
        raise ValueError("FOUNDRY_API_KEY environment variable is not configured.")
    
    return OpenAIChatClient(
        model=config.foundry_model,
        api_key=config.foundry_api_key,
        base_url=config.foundry_openai_base_url if config.foundry_openai_base_url else None
    )

