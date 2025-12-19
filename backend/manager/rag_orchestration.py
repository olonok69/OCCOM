import logging
import re
from typing import Dict, Any, Optional

import tiktoken
from llama_index.core import Settings
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler
from llama_index.core.chat_engine import CondensePlusContextChatEngine
from llama_index.core.memory import ChatMemoryBuffer
from model import ContentFilteringResponse

from service.azure_ai_search import AzureAISearchService
from service.memory_manager import MemoryManager
from service.llm_client import LLMClient, EmbeddingClient
from llama_index.core.postprocessor import SimilarityPostprocessor

import config as Config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RAGOrchestrator:
    """
    A RAG system orchestrator using LlamaIndex with Azure AI Search and Azure OpenAI.
    """

    def __init__(
        self,
        chunk_size: int = 1024,
        chunk_overlap: int = 200,
        chat_history_service=None,
    ):
        """
        Initialize the Model Orchestrator with Azure configurations.

        Args:
            chunk_size: Size of text chunks for processing
            chunk_overlap: Overlap between chunks
            chat_history_service: ChatHistoryService instance for memory management

        Note:
            Authentication uses Managed Identity only for Azure OpenAI services.
        """
        # Get fresh config instance
        self.config = Config.Config()

        self.azure_openai_endpoint = self.config.azure_openai_endpoint
        self.azure_openai_api_version = self.config.azure_openai_api_version
        self.azure_openai_deployment_name = self.config.azure_openai_deployment_name
        self.azure_openai_embedding_deployment = (
            self.config.azure_openai_embedding_deployment
        )

        self.azure_search_service_name = self.config.azure_search_service_name
        self.azure_search_index_name = self.config.azure_search_index_name

        self.chunk_size = self.config.chunk_size
        self.chunk_overlap = self.config.chunk_overlap
        # Initialize LLM and embedding clients
        self.llm_client = LLMClient()
        self.embedding_client = EmbeddingClient()

        # Set global settings and store as instance attributes
        Settings.llm = self.llm_client._client
        Settings.embed_model = self.embedding_client._client

        # Create instance attribute for direct access
        self.llm = self.llm_client._client

        # Initialize Azure AI Search service and get the vector store
        self.search_service = AzureAISearchService()
        self.vector_store = self.search_service.vector_store

        # Initialize Memory Manager
        self.memory_manager = MemoryManager(chat_history_service=chat_history_service)

        # Initialize index and query engine
        self.index = None
        self.query_engine = None
        self.similarity_postprocessor = SimilarityPostprocessor(
            similarity_cutoff=1.5,  # Minimum similarity score to keep a source
        )

        # Initialize tokenizer for token counting
        try:
            self._tokenizer = tiktoken.encoding_for_model(self.config.llm_model_name)
        except Exception:
            self._tokenizer = tiktoken.get_encoding("cl100k_base")

        logger.debug("Model Orchestrator initialized successfully")

    def _count_tokens(self, text: Optional[str]) -> int:
        """Return number of tokens for the provided text using the configured tokenizer."""
        if not text:
            return 0
        try:
            return len(self._tokenizer.encode(str(text)))
        except Exception:
            return len(str(text))

    def count_tokens(self, text: Optional[str]) -> int:
        """Public helper for other modules (e.g., endpoints) to count tokens consistently."""
        return self._count_tokens(text)

    def _init_token_counter(self):
        handler = TokenCountingHandler(tokenizer=self._tokenizer, verbose=False)
        callback_manager = CallbackManager([handler])
        return handler, callback_manager

    def _log_token_totals(self, session_label: str, handler: TokenCountingHandler):
        if not handler:
            return

        logger.info(
            "LLM_USAGE_6 session=%s prompt_tokens=%d completion_tokens=%d total_tokens=%d embedding_tokens=%d",
            session_label,
            handler.prompt_llm_token_count,
            handler.completion_llm_token_count,
            handler.total_llm_token_count,
            handler.total_embedding_token_count,
        )

    def validate_user_input(self, user_input: str) -> Optional[str]:
        """
        Validates user input for potential injection attacks using regex patterns.

        Args:
            user_input: The user input string to validate

        Returns:
            Optional[str]: Error message if malicious content detected, None if input is safe
        """
        try:
            # Define security patterns for various injection attacks

            # 1. SQL Injection
            # Matches common SQL commands with context (e.g., SELECT...FROM),
            # boolean bypasses (OR 1=1), and SQL comments.
            sql_re = re.compile(
                r"(\b(union|select|insert|update|delete|drop|alter)\s+.*\s+(from|into|set|table|database))|"
                r"(\b(union\s+all|select\s+\*)\b)|"
                r"(\'\s*(or|and)\s*[\d\w]+\s*[=<>]\s*[\d\w]+)|"
                r"(--|#|\/\*|\*\/)",
                re.IGNORECASE | re.DOTALL,
            )

            # 2. Command Injection (OS / Shell)
            # Matches shell separators (;, |, &, etc.) followed by dangerous system commands.
            cmd_re = re.compile(
                r"(;|\||&|\$\(|\`)\s*(cat|nc|netcat|wget|curl|ping|rm|ls|whoami|id|sudo|chmod|chown|sh|bash)\b",
                re.IGNORECASE,
            )

            # 3. Code, JSON & HTML Injection (XSS)
            # Matches <script> tags, javascript: protocols, event handlers,
            # and Python/JSON specific injection attempts (e.g., __proto__, import os).
            code_html_re = re.compile(
                r"(<\s*script.*?>)|(<\s*/\s*script)|"  # Script tags
                r"(javascript:|vbscript:)|"  # Protocol handlers
                r"(on(load|error|click|mouseover)\s*=)|"  # HTML Event handlers
                r"(\"__proto__\"\s*:)|"  # JSON Prototype pollution
                r"(import\s+os|import\s+sys|subprocess\.)",  # Python code injection
                re.IGNORECASE,
            )

            # 4. Template Injection (SSTI)
            # Matches syntax for Jinja2, Django, Spring (${}), and ASP/ERB (<%).
            ssti_re = re.compile(
                r"(\{\{[^}]*\}\})|"  # Jinja/Django - matches {{...}} with any content including expressions
                r"(\{\{.*?\}\})|"  # Fallback for nested braces
                r"(\{\%.*?\%\})|"  # Template logic {%...%}
                r"(\$\{[^}]*\})|"  # Java/Spring ${...}
                r"(<%.*?%>)|"  # ASP/ERB <%...%>
                r"(__class__|__mro__|__subclasses__|__init__|__globals__)",  # Python introspection
                re.IGNORECASE | re.DOTALL,
            )

            # 5. Email / CRLF Injection
            # Matches carriage returns/newlines followed by header manipulation fields.
            crlf_re = re.compile(
                r"(\r\n|\r|\n|%0a|%0d).*(Content-Type:|Bcc:|Cc:|To:|Subject:|Location:)",
                re.IGNORECASE,
            )

            # 6. JSON Injection (Privilege Escalation)
            # Matches JSON objects attempting to manipulate user roles, permissions, or authentication.
            # Catches attempts to inject admin/superuser roles or bypass authentication.
            json_injection_re = re.compile(
                r"\{[^}]*[\"'](role|permission|access|user|username)[\"']\s*:\s*[\"']?(admin|superuser|root|administrator)[\"']?|"  # Role/permission with admin value
                r"\{[^}]*[\"'](admin|superuser)[\"']\s*:|"  # Direct admin/superuser key
                r"\{[^}]*[\"'](isAdmin|is_admin|isSuperuser|is_superuser|isAuthenticated)[\"']\s*:\s*(true|1)",  # Boolean privilege flags
                re.IGNORECASE,
            )

            security_patterns = [
                ("SQL Injection", sql_re),
                ("Command Injection", cmd_re),
                ("Code/HTML Injection", code_html_re),
                ("Template Injection", ssti_re),
                ("Email/CRLF Injection", crlf_re),
                ("JSON Injection", json_injection_re),
            ]

            # Check input against each security pattern
            for attack_name, pattern in security_patterns:
                if pattern.search(user_input):
                    logger.warning(
                        f"[WARNING] [SECURITY] {attack_name} pattern detected in user input"
                    )
                    return "I'm sorry, but I cannot assist with that request. Please rephrase your question or ask about a different topic."

            return None

        except Exception as e:
            logger.error(f"[ERROR] [SECURITY] Error in input validation: {e}")
            # If validation fails, err on the side of caution
            return "I'm sorry, but I cannot assist with that request. Please rephrase your question or ask about a different topic."

    def query_with_chat_engine(
        self,
        question: str,
        similarity_top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        SessionID: Optional[str] = None,
        UserID: Optional[str] = None,
        BotID: Optional[str] = None,
        use_llm_judge_citation_filtering: bool = False,
    ) -> Dict[str, Any]:
        """
        Query using LlamaIndex's CondensePlusContextChatEngine for seamless memory + retrieval integration.

        This approach automatically:
        1. Validates user input for security threats
        2. Retrieves conversation history from memory
        3. Condenses the current question with context
        4. Performs semantic search on Azure AI Search
        5. Combines memory + retrieval in a single coherent response

        Args:
            question: The question to ask
            similarity_top_k: Number of similar documents to retrieve
            filters: Dictionary of filter field names and values
            SessionID: Session identifier for memory management
            UserID: User identifier for memory management
            BotID: Bot identifier for memory management

        Returns:
            Dictionary containing the response and metadata
        """
        token_handler, callback_manager = self._init_token_counter()
        previous_callback_manager = getattr(Settings, "callback_manager", None)
        Settings.callback_manager = callback_manager

        try:
            session_label = SessionID or "anonymous"
            question_chars = len(question or "")
            question_tokens = self._count_tokens(question)
            response = None
            response_text = ""
            logger.info(
                "LLM_INPUT_2 session=%s question_chars=%d question_tokens=%d filters=%d top_k=%d",
                session_label,
                question_chars,
                question_tokens,
                len(filters or {}),
                similarity_top_k,
            )

            validation_error = self.validate_user_input(question)
            if validation_error:
                logger.warning("[WARNING] [SECURITY] Blocked malicious input from user")
                # Create ContentFilteringResponse for consistency with Azure OpenAI content filtering
                response_text = "I'm sorry, but I cannot assist with that request. Please rephrase your question or ask about a different topic."
                response = ContentFilteringResponse(response_text)
                return {
                    "answer": response_text,
                    "sources": [],
                    "num_sources_used": 0,
                    "method": "security_filter",
                }

            logger.info(
                "[INFO] [CHAT ENGINE] Using CondensePlusContextChatEngine approach"
            )

            # Get memory for this session
            memory = None
            if SessionID and UserID and BotID:
                memory = self.memory_manager.get_memory_for_session(
                    SessionID=SessionID,
                    UserID=UserID,
                    BotID=BotID,
                )
            else:
                logger.warning(
                    "[WARNING] [CHAT ENGINE] No session IDs provided, proceeding without memory"
                )
                memory = ChatMemoryBuffer.from_defaults(token_limit=3900)

            memory_char_count = 0
            memory_msg_count = 0
            memory_token_count = 0
            if memory:
                try:
                    memory_messages = memory.get()
                    memory_msg_count = len(memory_messages)
                    for msg in memory_messages:
                        content = getattr(msg, "content", "")
                        if content:
                            content_str = str(content)
                            memory_char_count += len(content_str)
                            memory_token_count += self._count_tokens(content_str)
                except Exception as mem_ex:
                    logger.debug(
                        "[DEBUG] [CHAT ENGINE] Unable to sample memory size: %s", mem_ex
                    )

            logger.info(
                "LLM_MEMORY_3 session=%s messages=%d memory_chars=%d memory_tokens=%d",
                session_label,
                memory_msg_count,
                memory_char_count,
                memory_token_count,
            )

            # Get retriever from search service
            # Uses HYBRID mode (text + vector with BM25 ranking)
            retriever = self.search_service.get_retriever(
                similarity_top_k=similarity_top_k,
                filters=filters,
            )

            # Get fresh config for current system_prompt (always reads latest from config)
            self.config.reload_config()

            # Create the chat engine with memory + retrieval
            context_prompt = self.config.system_prompt

            logger.info(
                "[INFO] [NODE FILTER] Using SimilarityPostprocessor cutoff=%.2f",
                self.similarity_postprocessor.similarity_cutoff,
            )

            # Option to use LLMRerank as postprocessor
            # Set to True to use built-in LlamaIndex reranking instead of custom filter_sources_with_llm
            chat_engine = CondensePlusContextChatEngine.from_defaults(
                retriever=retriever,
                memory=memory,
                llm=self.llm,
                context_prompt=context_prompt,
                verbose=False,
                node_postprocessors=[self.similarity_postprocessor],
                callback_manager=callback_manager,
            )

            try:
                response = chat_engine.chat(question)
                # Extract the response text
                response_text = str(response)
                logger.info(f"[INFO] [CHAT ENGINE] response_text:{response_text}")

            except Exception as chat_error:
                error_msg = str(chat_error)
                logger.error(f"[ERROR] [CHAT ENGINE] Error during chat: {error_msg}")

                # Check if it's a 400 error or content filter issue
                if (
                    "400" in error_msg
                    or "content_filter" in error_msg
                    or "ResponsibleAIPolicyViolation" in error_msg
                ):
                    logger.warning(
                        "[WARNING] [CHAT ENGINE] Content policy violation detected"
                    )
                    response_text = "I'm sorry, but I cannot assist with that request. Please rephrase your question or ask about a different topic."

                    # Create a content filtering response object for consistency
                    response = ContentFilteringResponse(response_text)
                else:
                    # Re-raise other errors
                    raise chat_error

            try:
                if response_text == "Empty Response":
                    logger.warning(
                        "[WARNING] [CHAT ENGINE] Received empty response from chat"
                    )
                    response_text = "I'm sorry, this topic does not coincide with the information I have in the Knowledge base. Kindly refer to the FAQs or contact support for further assistance."
            except Exception as e:
                logger.error(
                    f"[ERROR] [CHAT ENGINE] Error checking for empty response: {e}"
                )
            # Extract sources from the response - only include those that were actually cited
            sources = []
            citation_idx = 1
            retrieved_char_count = 0
            retrieved_token_count = 0
            retrieved_chunk_count = 0
            uniq_references = set()
            if hasattr(response, "source_nodes"):
                for _, node_with_score in enumerate(response.source_nodes, 1):
                    node = node_with_score.node
                    metadata = node.metadata
                    file_name = metadata.get("file_name", "Unknown")
                    ref_check = ""
                    try:
                        if metadata.get("section_number", ""):
                            ref_check = f"Section {metadata.get('section_number', '')}"
                        elif metadata.get("chapter", ""):
                            ref_check = f"Chapter {metadata.get('chapter', '')}"
                        elif metadata.get("page_number", ""):
                            ref_check = (
                                f"Page {metadata.get('page_number', '')}, {file_name}"
                            )
                        if ref_check and (
                            ref_check not in response_text
                            or ref_check in uniq_references
                        ):
                            continue
                        else:
                            uniq_references.add(ref_check)
                    except Exception as e:
                        logger.warning(
                            f"[WARNING] [CHAT ENGINE] Error filtering reference in metadata: {str(e)}"
                        )

                    text = node.get_content()
                    if text:
                        retrieved_char_count += len(text)
                        retrieved_token_count += self._count_tokens(text)
                    retrieved_chunk_count += 1
                    score = node_with_score.score
                    sources.append(
                        {
                            "content": text[:200] + "..." if len(text) > 200 else text,
                            "score": score,
                            "file_name": file_name,
                            "metadata": metadata,
                        }
                    )
                    citation_idx += 1
            else:
                logger.warning(
                    "[WARNING] [CHAT ENGINE] No source_nodes found in response"
                )

            logger.info(
                "RETRIEVAL_SUMMARY_4 session=%s chunks=%d retrieved_chars=%d retrieved_tokens=%d",
                session_label,
                retrieved_chunk_count,
                retrieved_char_count,
                retrieved_token_count,
            )

            # Use LLM agent to filter sources based on actual usage in response
            # Set to False to disable LLM filtering for debugging
            if sources and use_llm_judge_citation_filtering:
                logger.info(
                    "[INFO] [SOURCE FILTER] Starting LLM-based source filtering"
                )
                filtered_sources, response_text = self.filter_sources_with_llm(
                    question=question, response_text=response_text, sources=sources
                )
                sources = filtered_sources
            else:
                logger.info(
                    "[INFO] [SOURCE FILTER] Skipping LLM filtering - using all sources"
                )

            response_char_count = len(response_text or "")
            response_token_count = self._count_tokens(response_text)
            logger.info(
                "LLM_RESPONSE_5 session=%s answer_chars=%d answer_tokens=%d citations=%d",
                session_label,
                response_char_count,
                response_token_count,
                len(sources),
            )

            return {
                "answer": response_text,
                "sources": sources,
                "num_sources_used": len(sources),
                "method": "chat_engine_with_memory",
            }

        except Exception as e:
            logger.error(f"[ERROR] [CHAT ENGINE] Error: {str(e)}")
            logger.exception("Full exception details:")
            return {
                "answer": f"I encountered an error while processing your question: {str(e)}",
                "sources": [],
                "num_sources_used": 0,
                "method": "error",
            }
        finally:
            Settings.callback_manager = previous_callback_manager
            self._log_token_totals(session_label, token_handler)

    def filter_sources_with_llm(
        self, question: str, response_text: str, sources: list
    ) -> tuple[list, str]:
        """
        Use an LLM agent to evaluate which sources were actually used in the response.

        Args:
            question: The original user question
            response_text: The generated response text
            sources: List of source documents to evaluate

        Returns:
            Tuple of (filtered list of sources, updated response text with renumbered citations)
        """
        if not sources:
            return [], response_text

        try:
            # Build the evaluation prompt
            sources_summary = []
            for idx, source in enumerate(sources, 1):
                file_name = source.get("file_name", "Unknown")
                content_preview = source.get("content", "")[:300]
                sources_summary.append(
                    f"Source {idx}:\nFile: {file_name}\nContent: {content_preview}...\n"
                )

            evaluation_prompt = f"""You are a source relevance evaluator and citation renumberer. Your task is to:
1. Determine which sources were actually used to generate the response
2. Renumber the citations in the response text to match the filtered sources

User Question: {question}

Generated Response: {response_text}

Available Sources:
{chr(10).join(sources_summary)}

For each source, determine if it was actually used to answer the question. A source is considered "used" if:
1. The response contains information directly from that source
2. The response explicitly or implicitly references facts from that source
3. The source contributed to answering the user's question

INSTRUCTIONS:
1. Identify which sources were used (e.g., if sources 1, 3, 7, and 9 were used from 10 total sources)
2. Renumber the citations in the response text sequentially (e.g., [1] stays [1], [3] becomes [2], [7] becomes [3], [9] becomes [4])
3. Return your response in this exact format:

SOURCES: <comma-separated list of original source numbers>
UPDATED_RESPONSE: <the complete response text with renumbered citations>

Examples:
- If sources 1 and 3 were used, respond with:
SOURCES: 1,3
UPDATED_RESPONSE: <full response text with [1] and [3] renumbered to [1] and [2]>

- If no sources were used:
SOURCES: none
UPDATED_RESPONSE: <original response text unchanged>

- If all sources were used:
SOURCES: all
UPDATED_RESPONSE: <original response text unchanged>

Your response:"""

            # Call LLM for evaluation
            llm_response = self.llm.complete(evaluation_prompt)
            evaluation_result = str(llm_response).strip()

            # Extract sources line
            sources_match = re.search(
                r"SOURCES:\s*(.+?)(?:\n|$)", evaluation_result, re.IGNORECASE
            )
            # Extract updated response (everything after UPDATED_RESPONSE:)
            response_match = re.search(
                r"UPDATED_RESPONSE:\s*(.+)",
                evaluation_result,
                re.IGNORECASE | re.DOTALL,
            )

            if not sources_match:
                logger.warning(
                    "[WARNING] [SOURCE FILTER] Could not parse SOURCES line, keeping all sources"
                )
                return sources, response_text

            sources_line = sources_match.group(1).strip().lower()
            updated_response_text = (
                response_match.group(1).strip() if response_match else response_text
            )

            logger.info(f"[INFO] [SOURCE FILTER] Parsed sources: '{sources_line}'")
            logger.info(
                f"[INFO] [CITATION RENUMBER] Updated response (first 200 chars): '{updated_response_text[:200]}...'"
            )

            # Parse which sources were used
            if "none" in sources_line and len(sources) > 0:
                # Double-check: if response says "none" but response text is substantial, keep sources
                if (
                    len(response_text) > 600
                    and "do not contain" not in response_text.lower()
                ):
                    logger.warning(
                        "[WARNING] [SOURCE FILTER] LLM said 'none' but response is substantial - keeping all sources"
                    )
                    return sources, response_text
                logger.info(
                    "[INFO] [SOURCE FILTER] LLM determined no sources were used"
                )
                return [], updated_response_text

            # Extract source numbers
            source_numbers = re.findall(r"\d+", sources_line)

            if not source_numbers:
                # If no numbers found, check for "all" keyword
                if "all" in sources_line:
                    logger.info(
                        "[INFO] [SOURCE FILTER] LLM indicated all sources were used"
                    )
                    return sources, updated_response_text
                logger.warning(
                    "[WARNING] [SOURCE FILTER] Could not parse source numbers, keeping all sources"
                )
                return sources, response_text

            used_indices = {
                int(num) - 1
                for num in source_numbers
                if num.isdigit() and int(num) <= len(sources)
            }

            # Filter sources based on LLM evaluation
            filtered_sources = []
            for idx, source in enumerate(sources):
                if idx in used_indices:
                    file_name = source.get("file_name", "Unknown")
                    filtered_sources.append(source)
                else:
                    file_name = source.get("file_name", "Unknown")

            logger.info(
                f"[INFO] [SOURCE FILTER] Filtered from {len(sources)} to {len(filtered_sources)} sources"
            )
            logger.info(
                "[INFO] [CITATION RENUMBER] LLM renumbered citations in response text"
            )

            return filtered_sources, updated_response_text

        except Exception as e:
            logger.error(f"[ERROR] [SOURCE FILTER] Error during LLM evaluation: {e}")
            logger.info("[INFO] [SOURCE FILTER] Falling back to returning all sources")
            return sources, response_text  # Return all sources if evaluation fails
