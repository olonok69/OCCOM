# services/search.py
import json
import logging
from typing import List, Dict, Any
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    VectorSearch,
    VectorSearchProfile,
    HnswAlgorithmConfiguration,
    HnswParameters,
    VectorSearchAlgorithmMetric,
)

# LlamaIndex imports
from llama_index.core import StorageContext
from llama_index.core.schema import TextNode
from llama_index.core import VectorStoreIndex
from llama_index.core.vector_stores.types import (
    VectorStoreQueryMode,
    MetadataFilters,
    ExactMatchFilter,
)
from llama_index.vector_stores.azureaisearch import (
    AzureAISearchVectorStore,
    MetadataIndexFieldType,
)

# Import embedding client for query embedding generation
from service.llm_client import EmbeddingClient

import config as Config

# Initialize logger
logger = logging.getLogger(__name__)
BACKEND_EXCEPTION_TAG = "BACKEND_EXCEPTION"

config = Config.Config()


class AzureAISearchService:
    def __init__(self, *, vector_dims: int = 3072):
        self.index_name = config.azure_search_index_name
        self.endpoint = config.azure_search_endpoint
        self.vector_dims = vector_dims
        credential = DefaultAzureCredential()

        # Initialize embedding client for query embedding generation
        self.embedding_client = EmbeddingClient()

        # Keep the original search clients for backward compatibility
        self.search = SearchClient(
            endpoint=self.endpoint, index_name=self.index_name, credential=credential
        )
        self.indexes = SearchIndexClient(endpoint=self.endpoint, credential=credential)

        # Initialize LlamaIndex Azure AI Search Vector Store
        # Define base metadata fields that should be filterable
        metadata_fields = {
            "file_name": ("file_name", MetadataIndexFieldType.STRING),
            "file_uri": ("file_uri", MetadataIndexFieldType.STRING),
            "language": ("language", MetadataIndexFieldType.STRING),
            "access_level": ("access_level", MetadataIndexFieldType.STRING),
            "page_number": ("page_number", MetadataIndexFieldType.INT64),
            "report_name": ("report_name", MetadataIndexFieldType.STRING),
            "publisher": ("publisher", MetadataIndexFieldType.STRING),
            "publisher_id": ("publisher_id", MetadataIndexFieldType.STRING),
            "geographical_area": ("geographical_area", MetadataIndexFieldType.STRING),
            "publishing_year": ("publishing_year", MetadataIndexFieldType.INT64),
            "period_covered": ("period_covered", MetadataIndexFieldType.STRING),
            "version_id": ("version_id", MetadataIndexFieldType.STRING),
            "uploaded_by": ("uploaded_by", MetadataIndexFieldType.STRING),
            "section_number": ("section_number", MetadataIndexFieldType.STRING),
            "chapter": ("chapter", MetadataIndexFieldType.STRING),
            "chunk_type": ("chunk_type", MetadataIndexFieldType.STRING),
            # Custom fields for document structure
            "images": ("images", MetadataIndexFieldType.COLLECTION),
            "charts": ("charts", MetadataIndexFieldType.COLLECTION),
            "tables": ("tables", MetadataIndexFieldType.COLLECTION),
            "created_at": ("created_at", MetadataIndexFieldType.STRING),
            "updated_at": ("updated_at", MetadataIndexFieldType.STRING),
        }

        # Dynamically add filter fields from config
        logger.debug(f"has_filters: {config.has_filters}")
        logger.debug(f"filters: {config.filters}")

        if config.has_filters and config.filters:
            for filter_key, filter_field_name in config.filters.items():
                if not filter_field_name:
                    continue

                if filter_field_name not in metadata_fields:
                    metadata_fields[filter_field_name] = (
                        filter_field_name,
                        MetadataIndexFieldType.STRING,
                    )

        self.create_or_update_index()

        # Store semantic configuration name for later use
        self.semantic_config_name = f"{self.index_name}_ranker"

        # Initialize the vector store with LlamaIndex
        self.vector_store = AzureAISearchVectorStore(
            search_or_index_client=self.indexes,
            index_name=self.index_name,
            id_field_key="id",
            chunk_field_key="text",
            embedding_field_key="vector",
            embedding_dimensionality=vector_dims,
            metadata_string_field_key="metadata",
            doc_id_field_key="doc_id",
            filterable_metadata_field_keys=metadata_fields,
            language_analyzer="en.lucene",
            vector_algorithm_type="hnsw",
            semantic_configuration_name=f"{self.index_name}_ranker",
        )

        # Create storage context
        self.storage_context = StorageContext.from_defaults(
            vector_store=self.vector_store
        )

        # Ensure index schema is up to date with expected fields
        self._ensure_index_schema_compatible()

        # --- OPTIMIZATION START ---
        # Initialize the LlamaIndex wrapper ONCE here.
        # This prevents rebuilding the Index object on every request.
        logger.info("[INFO] Initializing global LlamaIndex VectorStoreIndex...")
        self.llama_index = VectorStoreIndex.from_vector_store(
            vector_store=self.vector_store,
            storage_context=self.storage_context,
        )
        # --- OPTIMIZATION END ---

    def create_or_update_index(self):
        """Create the search index only if it doesn't exist. Preserve existing data."""
        try:
            # Check if index exists first
            existing_index = self.indexes.get_index(self.index_name)
            return existing_index
        except Exception as e:
            # Index doesn't exist, create it
            logger.debug(
                f"Index {self.index_name} doesn't exist, creating new index: {e}"
            )

        # Configure vector search with HNSW algorithm
        vector_search = VectorSearch(
            algorithms=[
                HnswAlgorithmConfiguration(
                    name=f"{self.index_name}-algorithm",
                    parameters=HnswParameters(
                        m=4,
                        ef_construction=400,
                        ef_search=500,
                        metric=VectorSearchAlgorithmMetric.COSINE,
                    ),
                )
            ],
            profiles=[
                VectorSearchProfile(
                    name=f"{self.index_name}-profile",
                    algorithm_configuration_name=f"{self.index_name}-algorithm",
                )
            ],
        )

        # Define all fields including custom metadata fields
        fields = [
            # ===== CORE FIELDS (Required by LlamaIndex) =====
            SimpleField(
                name="id", type=SearchFieldDataType.String, key=True, filterable=True
            ),
            SearchableField(name="text", type=SearchFieldDataType.String),
            # Vector field with proper dimensions and HNSW configuration
            SearchField(
                name="vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=self.vector_dims,
                vector_search_profile_name=f"{self.index_name}-profile",
            ),
            # ===== LLAMAINDEX-SPECIFIC FIELDS =====
            # metadata: Complete metadata backup as JSON string
            SimpleField(
                name="metadata",
                type=SearchFieldDataType.String,
                filterable=False,
                sortable=False,
                facetable=False,
                searchable=False,
            ),
            # ===== DOCUMENT STRUCTURE FIELDS =====
            SimpleField(
                name="doc_id", type=SearchFieldDataType.String, filterable=True
            ),
            SimpleField(
                name="images",
                type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            ),
            SimpleField(
                name="charts",
                type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            ),
            SimpleField(
                name="tables",
                type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            ),
            # ===== BASE METADATA FIELDS =====
            SimpleField(
                name="page_number", type=SearchFieldDataType.Int32, filterable=True
            ),
            SimpleField(
                name="created_at",
                type=SearchFieldDataType.DateTimeOffset,
                filterable=True,
                sortable=True,
            ),
            SimpleField(
                name="updated_at",
                type=SearchFieldDataType.DateTimeOffset,
                filterable=True,
                sortable=True,
            ),
            SimpleField(
                name="file_name",
                type=SearchFieldDataType.String,
                filterable=True,
                sortable=True,
            ),
            SimpleField(
                name="file_uri", type=SearchFieldDataType.String, filterable=True
            ),
            SimpleField(
                name="language",
                type=SearchFieldDataType.String,
                sortable=True,
                filterable=True,
                facetable=True,
                default_value="en",
            ),
            SimpleField(
                name="access_level",
                type=SearchFieldDataType.String,
                sortable=True,
                filterable=True,
                facetable=True,
                default_value="low",
            ),
            SimpleField(
                name="version_id", type=SearchFieldDataType.String, filterable=True
            ),
            SimpleField(
                name="uploaded_by", type=SearchFieldDataType.String, filterable=True
            ),
            SimpleField(
                name="report_name",
                type=SearchFieldDataType.String,
                filterable=True,
                searchable=True,
            ),
            SimpleField(
                name="publisher",
                type=SearchFieldDataType.String,
                filterable=True,
                searchable=True,
            ),
            SimpleField(
                name="publisher_id", type=SearchFieldDataType.String, filterable=True
            ),
            SimpleField(
                name="geographical_area",
                type=SearchFieldDataType.String,
                filterable=True,
                facetable=True,
            ),
            SimpleField(
                name="publishing_year",
                type=SearchFieldDataType.Int32,
                filterable=True,
                sortable=True,
            ),
            SimpleField(
                name="period_covered", type=SearchFieldDataType.String, filterable=True
            ),
            SimpleField(
                name="section_number",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="chapter",
                type=SearchFieldDataType.String,
                filterable=True,
                facetable=True,
            ),
            SimpleField(
                name="chunk_type",
                type=SearchFieldDataType.String,
                filterable=True,
                facetable=True,
            ),
        ]

        # ===== DYNAMIC FILTER FIELDS FROM CONFIG =====
        if config.has_filters and config.filters:
            for filter_key, filter_field_name in config.filters.items():
                if not filter_field_name:
                    continue

                existing_field_names = [f.name for f in fields]
                if filter_field_name in existing_field_names:
                    continue

                fields.append(
                    SimpleField(
                        name=filter_field_name,
                        type=SearchFieldDataType.String,
                        filterable=True,
                        facetable=True,
                        sortable=True,
                    )
                )

        # Configure semantic search with proper ranking
        semantic_config = SemanticConfiguration(
            name=f"{self.index_name}_ranker",
            prioritized_fields=SemanticPrioritizedFields(
                title_field=SemanticField(field_name="file_name"),
                content_fields=[SemanticField(field_name="text")],
                keywords_fields=[],
            ),
        )
        semantic_search = SemanticSearch(configurations=[semantic_config])

        index = SearchIndex(
            name=self.index_name,
            fields=fields,
            vector_search=vector_search,
            semantic_search=semantic_search,
        )

        result = self.indexes.create_or_update_index(index)
        return result

    def _ensure_index_schema_compatible(self):
        """Ensure the index schema matches the expected fields."""
        try:
            try:
                existing_index = self.indexes.get_index(self.index_name)
                existing_field_names = {field.name for field in existing_index.fields}
            except Exception:
                self.create_or_update_index()
                return

            expected_field_names = {
                "id",
                "text",
                "vector",
                "metadata",
                "doc_id",
                "images",
                "charts",
                "tables",
                "page_number",
                "created_at",
                "updated_at",
                "file_name",
                "file_uri",
                "language",
                "access_level",
                "version_id",
                "uploaded_by",
                "report_name",
                "publisher",
                "publisher_id",
                "geographical_area",
                "publishing_year",
                "period_covered",
                "section_number",
                "chapter",
                "chunk_type",
            }

            if config.has_filters and config.filters:
                for filter_field_name in config.filters.values():
                    if filter_field_name:
                        expected_field_names.add(filter_field_name)

            missing_fields = expected_field_names - existing_field_names

            if not missing_fields:
                return

            logger.warning(
                f"[WARNING] [SCHEMA UPDATE] Found {len(missing_fields)} missing fields: {missing_fields}"
            )
            self.create_or_update_index()

        except Exception as e:
            logger.error(f"[ERROR] [SCHEMA UPDATE] Error updating index schema: {e}")
            pass

    def upload_documents(self, docs: List[Dict[str, Any]]):
        """Upload documents to the vector store using LlamaIndex"""
        cleaned = []
        for doc in docs:
            try:
                json.dumps(doc)
                cleaned.append(doc)
            except (TypeError, ValueError) as e:
                logger.warning(f"Skipping non-serializable document: {e}")

        if not cleaned:
            return

        try:
            nodes = []
            for doc in cleaned:
                doc_id = doc.get("id", "")
                text = doc.get("text", "")
                vector = doc.get("vector", [])

                metadata = {
                    k: v
                    for k, v in doc.items()
                    if k not in ["id", "text", "vector"] and k is not None
                }

                node = TextNode(
                    id_=doc_id,
                    text=text,
                    embedding=vector if vector else None,
                    metadata=metadata,
                )
                nodes.append(node)

            self.vector_store.add(nodes)
            return {"success": True, "count": len(nodes)}
        except Exception as e:
            logger.exception("Error uploading documents: %s", e)
            raise

    def search_documents(
        self,
        query: str,
        top: int = 5,
        semantic_configuration_name: str = None,
        filters: Dict[str, Any] = None,
    ):
        """Search documents using hybrid (text + vector) semantic search with optional filters"""
        try:
            metadata_filters = None
            if filters:
                filter_list = []
                for key, value in filters.items():
                    filter_list.append(ExactMatchFilter(key=key, value=value))

                if filter_list:
                    metadata_filters = MetadataFilters(
                        filters=filter_list,
                        condition="and",
                    )

            # --- OPTIMIZATION: Use the globally cached index ---
            # Use HYBRID mode for best results (combines text + vector search)
            retriever = self.llama_index.as_retriever(
                similarity_top_k=top,
                vector_store_query_mode=VectorStoreQueryMode.HYBRID,
                filters=metadata_filters,
            )

            logger.debug("[DEBUG] [SEARCH] Performing hybrid search (text + vector)...")
            nodes = retriever.retrieve(query)

            documents = []
            for node_with_score in nodes:
                node = node_with_score.node
                doc = {
                    "id": node.node_id,
                    "text": node.text,
                    "@search.score": (
                        node_with_score.score
                        if hasattr(node_with_score, "score")
                        else None
                    ),
                    **node.metadata,
                }
                documents.append(doc)

            return documents

        except Exception as e:
            logger.exception("[ERROR] [SEARCH] Error searching documents: %s", e)
            return []

    def get_retriever(
        self,
        similarity_top_k: int = 10,
        filters: Dict[str, Any] = None,
        use_semantic_reranking: bool = False,
    ):
        """
        Get a LlamaIndex retriever instance for use with chat engines.
        """
        try:
            metadata_filters = None
            if filters:
                filter_list = []
                for key, value in filters.items():
                    filter_list.append(ExactMatchFilter(key=key, value=value))

                if filter_list:
                    metadata_filters = MetadataFilters(
                        filters=filter_list,
                        condition="and",
                    )
                    logger.debug(
                        f"[DEBUG] [RETRIEVER] Applying {len(filter_list)} filters: {list(filters.keys())}"
                    )

            # --- OPTIMIZATION: Use the globally cached index ---
            # We use the index initialized in __init__ instead of creating a new one.

            # Note: We are using SEMANTIC_HYBRID here to use Azure's server-side
            # semantic ranking instead of the slow client-side LLMRerank.
            query_mode = VectorStoreQueryMode.SEMANTIC_HYBRID

            retriever = self.llama_index.as_retriever(
                similarity_top_k=similarity_top_k,
                vector_store_query_mode=query_mode,
                filters=metadata_filters,
            )
            return retriever

        except Exception as e:
            logger.exception("[ERROR] [RETRIEVER] Error creating retriever: %s", e)
            raise

    def list_all_documents(self, select_fields: List[str] = None):
        """List all documents in the search index with optional field selection."""
        try:
            search_params = {
                "search_text": "",
                "top": 1000,
                "include_total_count": True,
            }

            if select_fields:
                search_params["select"] = select_fields

            try:
                results = self.search.search(**search_params)
            except Exception:
                search_params["search_text"] = "*"
                results = self.search.search(**search_params)

            documents = []
            for result in results:
                doc = dict(result)
                doc.pop("@search.score", None)
                doc.pop("@search.highlights", None)
                doc.pop("@search.captions", None)
                documents.append(doc)

            total_count = results.get_count()

            if total_count > len(documents):
                skip = len(documents)
                while skip < total_count:
                    batch_params = search_params.copy()
                    batch_params["skip"] = skip
                    batch_results = self.search.search(**batch_params)
                    batch_docs = []

                    for result in batch_results:
                        doc = dict(result)
                        doc.pop("@search.score", None)
                        doc.pop("@search.highlights", None)
                        doc.pop("@search.captions", None)
                        batch_docs.append(doc)

                    if not batch_docs:
                        break

                    documents.extend(batch_docs)
                    skip += len(batch_docs)

            return documents

        except Exception as e:
            logger.exception("Error listing documents: %s", e)
            return []

    def delete_file_documents(self, file_name: str):
        """Delete all documents for a specific file from the search index."""
        try:
            search_params = {
                "search_text": "*",
                "filter": f"file_name eq '{file_name}'",
                "select": ["id"],
                "top": 1000,
            }

            results = self.search.search(**search_params)
            document_ids = [doc["id"] for doc in results]

            if not document_ids:
                logger.warning(
                    "%s azure_search.delete_file_documents_no_results file=%s",
                    BACKEND_EXCEPTION_TAG,
                    file_name,
                )
                return {
                    "success": False,
                    "message": f"No documents found for file: {file_name}",
                    "deleted_count": 0,
                }

            documents_to_delete = [
                {"@search.action": "delete", "id": doc_id} for doc_id in document_ids
            ]

            self.search.upload_documents(documents_to_delete)

            return {
                "success": True,
                "message": f"Successfully deleted {len(document_ids)} documents for file: {file_name}",
                "deleted_count": len(document_ids),
            }

        except Exception as e:
            logger.exception("Error deleting file documents: %s", e)
            return {
                "success": False,
                "message": f"Failed to delete file: {str(e)}",
                "deleted_count": 0,
            }

    def delete_all_documents(self):
        """Delete ALL documents from the search index."""
        try:
            logger.warning(
                "[WARNING] [DELETE ALL] Starting deletion of ALL documents from search index"
            )

            search_params = {
                "search_text": "*",
                "select": ["id"],
                "top": 1000,
            }

            total_deleted = 0

            while True:
                results = list(self.search.search(**search_params))

                if not results:
                    break

                document_ids = [doc["id"] for doc in results]

                documents_to_delete = [
                    {"@search.action": "delete", "id": doc_id}
                    for doc_id in document_ids
                ]

                self.search.upload_documents(documents_to_delete)
                total_deleted += len(document_ids)

                if len(results) < 1000:
                    break

            return {
                "success": True,
                "message": f"Successfully deleted {total_deleted} documents from search index",
                "deleted_count": total_deleted,
            }

        except Exception as e:
            logger.exception("[ERROR] [DELETE ALL] Error deleting all documents: %s", e)
            return {
                "success": False,
                "message": f"Failed to delete all documents: {str(e)}",
                "deleted_count": 0,
            }
