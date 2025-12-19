"""
Memory Management Service

This module provides chat memory management using LlamaIndex's Memory class
with short-term and long-term memory blocks. It integrates with the chat history
service to retrieve and maintain conversation context for improved RAG responses.
"""

import logging
from typing import Optional, List, Dict, Any
from llama_index.core.memory import Memory
from llama_index.core.llms import ChatMessage, MessageRole
from model import ChatHistoryQuery

logger = logging.getLogger(__name__)
BACKEND_EXCEPTION_TAG = "BACKEND_EXCEPTION"


class MemoryManager:
    """
    Manages chat memory for RAG conversations using LlamaIndex Memory.

    This class provides memory management by:
    - Retrieving conversation history from Cosmos DB via ChatHistoryService
    - Converting history to LlamaIndex ChatMessage format
    - Managing memory using LlamaIndex's Memory class with memory blocks
    - Providing conversation context for LLM queries
    - Storing references and images metadata for each interaction
    """

    def __init__(
        self,
        chat_history_service=None,
        token_limit: int = 100000,
        chat_history_token_ratio: float = 0.7,
        token_flush_size: int = 5000,
    ):
        """
        Initialize the Memory Manager.

        Args:
            chat_history_service: ChatHistoryService instance for retrieving history from Cosmos DB
            token_limit: Maximum number of tokens to store in memory (default: 100000)
            chat_history_token_ratio: Ratio of tokens allocated to short-term chat history (default: 0.7)
            token_flush_size: Number of tokens to flush at once to long-term memory (default: 5000)
        """
        self.chat_history_service = chat_history_service
        self.token_limit = token_limit
        self.chat_history_token_ratio = chat_history_token_ratio
        self.token_flush_size = token_flush_size

        # Cache for memory instances by session_id
        self._memory_cache: Dict[str, Memory] = {}

        # Cache for references and images metadata by session_id
        self._metadata_cache: Dict[str, List[Dict[str, Any]]] = {}

    def get_memory_for_session(self, SessionID: str, UserID: str, BotID: str) -> Memory:
        """
        Get or create a Memory instance for a specific session.

        Retrieves conversation history from Cosmos DB and loads it into memory.

        Args:
            SessionID: Session identifier
            UserID: User identifier
            BotID: Bot identifier

        Returns:
            Memory instance with conversation history loaded
        """
        try:
            # Check if we already have memory for this session
            if SessionID in self._memory_cache:
                cached_memory = self._memory_cache[SessionID]
                return cached_memory

            # Create new Memory instance for this session
            memory = Memory.from_defaults(
                session_id=SessionID,
                token_limit=self.token_limit,
                chat_history_token_ratio=self.chat_history_token_ratio,
                token_flush_size=self.token_flush_size,
                insert_method="user",  # Insert memory blocks into user messages
            )

            # Load conversation history from Cosmos DB if service is available
            if self.chat_history_service:
                chat_messages, metadata_list = self._retrieve_session_history(
                    SessionID, UserID, BotID
                )

                if chat_messages:
                    # Use put_messages to add all messages at once
                    memory.put_messages(chat_messages)

                    # Store metadata cache
                    self._metadata_cache[SessionID] = metadata_list
                else:
                    self._metadata_cache[SessionID] = []
            else:
                logger.warning(
                    "%s memory.service_unavailable session_id=%s",
                    BACKEND_EXCEPTION_TAG,
                    SessionID,
                )
                self._metadata_cache[SessionID] = []

            # Cache the memory instance
            self._memory_cache[SessionID] = memory
            return memory

        except Exception as e:
            logger.error(
                f"[ERROR] [MEMORY] Error getting memory for session {SessionID}: {e}"
            )
            logger.exception("Full exception details:")
            # Return empty memory as fallback
            return Memory.from_defaults(
                session_id=SessionID,
                token_limit=self.token_limit,
                chat_history_token_ratio=self.chat_history_token_ratio,
                token_flush_size=self.token_flush_size,
            )

    def _retrieve_session_history(
        self, session_id: str, user_id: str, bot_id: str, limit: int = 50
    ) -> tuple[List[ChatMessage], List[Dict[str, Any]]]:
        """
        Retrieve conversation history from Cosmos DB and convert to ChatMessage format.
        Also extracts references and images metadata.

        Args:
            session_id: Session identifier
            user_id: User identifier
            bot_id: Bot identifier
            limit: Maximum number of messages to retrieve

        Returns:
            Tuple of (List of ChatMessage objects, List of metadata dicts with references and images)
        """
        try:
            # Query chat history service
            query = ChatHistoryQuery(
                BotID=bot_id,
                UserID=user_id,
                SessionID=session_id,
                limit=limit,
            )

            # Call get_user_session with individual arguments instead of query object
            result = self.chat_history_service.get_user_session(
                UserID=query.UserID, SessionID=query.SessionID, BotID=query.BotID
            )

            if not result.get("success"):
                logger.warning(
                    "%s memory.history_fetch_failed session_id=%s error=%s",
                    BACKEND_EXCEPTION_TAG,
                    session_id,
                    result.get("error"),
                )
                return [], []

            # Extract messages from result
            history_data = result.get("data", {})
            messages = history_data.get("messages", [])

            if not messages:
                return [], []

            # Convert to ChatMessage format and extract metadata
            chat_messages = []
            metadata_list = []
            for msg in messages:
                # Add user message
                user_content = msg.get("query", "")
                if user_content:
                    chat_messages.append(
                        ChatMessage(role=MessageRole.USER, content=user_content)
                    )

                # Add assistant response
                assistant_content = msg.get("response", "")
                if assistant_content:
                    chat_messages.append(
                        ChatMessage(
                            role=MessageRole.ASSISTANT, content=assistant_content
                        )
                    )

                # Extract metadata (references and images)
                interaction_metadata = {
                    "query": user_content,
                    "response": assistant_content,
                    "references": msg.get("references", []),
                    "images": msg.get("images", []),
                    "timestamp": msg.get("timestamp"),
                }
                metadata_list.append(interaction_metadata)

            return chat_messages, metadata_list

        except Exception as e:
            logger.error(f"[ERROR] [MEMORY] Error retrieving session history: {e}")
            logger.exception("Full exception details:")
            return [], []

    def add_interaction(
        self,
        SessionID: str,
        UserID: str,
        BotID: str,
        user_message: str,
        assistant_response: str,
        references: Optional[List[Dict[str, Any]]] = None,
        images: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        Add a new interaction to the memory for a session.

        Args:
            SessionID: Session identifier
            UserID: User identifier
            BotID: Bot identifier
            user_message: User's query
            assistant_response: Assistant's response
            references: List of reference/citation objects
            images: List of image group objects
        """
        try:
            # Get or create memory for this session
            if SessionID not in self._memory_cache:
                # Create memory without loading from Cosmos (we're adding the current interaction)
                memory = Memory.from_defaults(
                    session_id=SessionID,
                    token_limit=self.token_limit,
                    chat_history_token_ratio=self.chat_history_token_ratio,
                    token_flush_size=self.token_flush_size,
                    insert_method="user",
                )
                self._memory_cache[SessionID] = memory
                self._metadata_cache[SessionID] = []
            else:
                memory = self._memory_cache[SessionID]

            # Add messages to memory
            messages = [
                ChatMessage(role=MessageRole.USER, content=user_message),
                ChatMessage(role=MessageRole.ASSISTANT, content=assistant_response),
            ]

            memory.put_messages(messages)

            # Store metadata
            if SessionID not in self._metadata_cache:
                self._metadata_cache[SessionID] = []

            self._metadata_cache[SessionID].append(
                {
                    "user_id": UserID,
                    "bot_id": BotID,
                    "query": user_message,
                    "response": assistant_response,
                    "references": references or [],
                    "images": images or [],
                }
            )

        except Exception as e:
            logger.error(f"[ERROR] [MEMORY] Error adding interaction: {e}")
            logger.exception("Full add_interaction exception:")

    def get_references_and_images(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Get references and images metadata for a session.

        Args:
            session_id: Session identifier

        Returns:
            List of metadata dicts containing references and images
        """
        return self._metadata_cache.get(session_id, [])

    def get_conversation_context(self, session_id: str) -> List[ChatMessage]:
        """
        Get the conversation context (chat history) for a session.

        Args:
            session_id: Session identifier

        Returns:
            List of ChatMessage objects representing the conversation context
        """
        try:
            if session_id in self._memory_cache:
                memory = self._memory_cache[session_id]
                chat_history = memory.get()
                logger.debug(
                    f"[DEBUG] [MEMORY] Retrieved {len(chat_history)} messages from memory"
                )
                return chat_history
            else:
                logger.debug(f"[DEBUG] [MEMORY] No memory cached for session: {session_id}")
                return []

        except Exception as e:
            logger.error(f"[ERROR] [MEMORY] Error getting conversation context: {e}")
            return []

    def clear_session_memory(self, session_id: str) -> None:
        """
        Clear memory for a specific session.

        Args:
            session_id: Session identifier
        """
        if session_id in self._memory_cache:
            del self._memory_cache[session_id]

        if session_id in self._metadata_cache:
            del self._metadata_cache[session_id]

    def clear_all_memory(self) -> None:
        """Clear all cached memory instances and metadata."""
        self._memory_cache.clear()
        self._metadata_cache.clear()
