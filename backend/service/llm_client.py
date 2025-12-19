# services/llm.py
import numpy as np
from azure.identity import DefaultAzureCredential
from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
from llama_index.llms.azure_openai import AzureOpenAI
import config as Config

config = Config.Config()


class LLMClient:
    def __init__(self):
        """
        Initialize the LLM client with Azure OpenAI using Managed Identity authentication.

        Args:
            endpoint: Azure OpenAI endpoint
            deployment_name: Name of the deployment
            api_version: API version to use
        """
        # Use managed identity authentication only
        credential = DefaultAzureCredential()

        # Create a token provider function that returns the access token
        def get_token_provider():
            """Get Azure AD token for OpenAI access."""
            token = credential.get_token("https://cognitiveservices.azure.com/.default")
            return token.token

        self._client = AzureOpenAI(
            model=config.llm_model_name,
            deployment_name=config.azure_openai_deployment_name,
            api_key="",  # Empty string to bypass key requirement
            azure_ad_token_provider=get_token_provider,
            azure_endpoint=config.azure_openai_endpoint,
            api_version=config.azure_openai_api_version,
            temperature=0.0,
            max_tokens=2000,
            use_azure_ad=True,  # Ensure Managed Identity is used
        )


class EmbeddingClient:
    def __init__(
        self,
    ):
        """
        Initialize the LLM client with Azure OpenAI using Managed Identity authentication.

        Args:
            endpoint: Azure OpenAI endpoint
            deployment_name: Name of the deployment
            api_version: API version to use
        """
        # Use managed identity authentication only
        credential = DefaultAzureCredential()

        # Create a token provider function that returns the access token
        def get_token_provider():
            """Get Azure AD token for OpenAI access."""
            token = credential.get_token("https://cognitiveservices.azure.com/.default")
            return token.token

        self.embed_model = AzureOpenAIEmbedding(
            model=config.embedding_model_name,
            deployment_name=config.azure_openai_embedding_deployment,
            api_key="",  # Empty string to bypass key requirement
            azure_ad_token_provider=get_token_provider,
            azure_endpoint=config.azure_openai_endpoint,
            api_version=config.azure_openai_api_version,
            dimensions=3072,  # Explicitly set dimensions
        )

        # Alias for compatibility
        self._client = self.embed_model

    def embed(self, text: str) -> np.ndarray:
        """Generate embedding for text using LlamaIndex AzureOpenAIEmbedding."""
        # LlamaIndex's get_text_embedding returns a list of floats
        embedding = self.embed_model.get_text_embedding(text)
        return np.array(embedding)
