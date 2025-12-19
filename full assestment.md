# AI Integrity Assistant: Bot in a Box Extension Analysis

## Executive Summary

This document analyzes the feasibility of extending the current **Bot in a Box (BIAB) V2** pattern to support the **AI Integrity Assistant** requirements, including integration with **OpenText Livelink** document management system.

**Assessment**: Extension is **feasible** but requires **significant architectural enhancements**. The current BIAB pattern provides a solid foundation (~60% reusable), but critical gaps exist in document source integration, entity extraction, and cross-document analysis capabilities.

---

## 1. Current Bot in a Box Pattern Analysis

### 1.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           BOT IN A BOX V2 ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐         ┌──────────────────┐        ┌──────────────────┐  │
│  │   Frontend   │ ──────► │      APIM        │ ─────► │     Backend      │  │
│  │  (Streamlit) │         │   (Gateway)      │        │    (FastAPI)     │  │
│  └──────────────┘         └──────────────────┘        └────────┬─────────┘  │
│                                                                 │            │
│                                                                 ▼            │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                        SERVICE LAYER                                     │ │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌──────────────────┐   │ │
│  │  │ RAG         │ │ LLM Client  │ │ Embedding   │ │ Chat History     │   │ │
│  │  │ Orchestrator│ │ (Azure      │ │ Client      │ │ Service          │   │ │
│  │  │             │ │ OpenAI)     │ │             │ │                  │   │ │
│  │  └──────┬──────┘ └─────────────┘ └─────────────┘ └──────────────────┘   │ │
│  │         │                                                                │ │
│  │         ▼                                                                │ │
│  │  ┌─────────────────────────────────────────────────────────────────────┐ │ │
│  │  │                      DATA LAYER                                      │ │ │
│  │  │  ┌─────────────────┐      ┌─────────────────┐                       │ │ │
│  │  │  │ Azure AI Search │      │ Azure Blob      │                       │ │ │
│  │  │  │ (Vector Store)  │      │ Storage         │                       │ │ │
│  │  │  └─────────────────┘      └─────────────────┘                       │ │ │
│  │  └─────────────────────────────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Key Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Frontend** | Streamlit | Chat interface, file viewer, admin panels |
| **Backend** | FastAPI | REST API, business logic, orchestration |
| **RAG Framework** | LlamaIndex | Document indexing, retrieval, query processing |
| **Vector Store** | Azure AI Search | Semantic search with hybrid mode (text + vector) |
| **Document Store** | Azure Blob Storage | PDF/Word document storage |
| **LLM** | Azure OpenAI (GPT-4o) | Response generation |
| **Embeddings** | text-embedding-3-large | 3072-dimensional vectors |
| **Auth** | Azure AD JWT | Role-based access (User/Admin/Super Admin) |

### 1.3 Current Capabilities

| Feature | Status | Notes |
|---------|--------|-------|
| Document Upload (PDF/Word) | ✅ Available | Manual upload via UI |
| Chunk-based Indexing | ✅ Available | Chapter chunking for Word docs |
| Semantic Search | ✅ Available | Hybrid mode with Azure AI Search |
| Chat with Citations | ✅ Available | Page-level citations |
| Chat History | ✅ Available | Session-based persistence |
| Role-Based Access | ✅ Available | 3 permission levels |
| Metadata Filtering | ✅ Available | Basic filter support |
| Multi-language Support | ⚠️ Partial | Configurable per bot |

---

## 2. AI Integrity Assistant Requirements Analysis

### 2.1 Core Functional Requirements (from Email)

Based on the requirements document, the AI Integrity Assistant must answer complex queries such as:

| Requirement ID | Query Type | Complexity |
|----------------|------------|------------|
| **REQ-01** | Party assessment lookup | "Has OCCO previously assessed (party name)?" |
| **REQ-02** | Integrity concerns extraction | "What integrity concerns were identified for (party)?" |
| **REQ-03** | Mitigating factors identification | "Were there any mitigating factors in assessment?" |
| **REQ-04** | Cross-document mentions | "Are there other documents mentioning (party)?" |
| **REQ-05** | Risk rating by role | "How were projects risk rated where party was (role)?" |
| **REQ-06** | Board disclosures | "What was disclosed to board regarding DAQ for (party)?" |
| **REQ-07** | External due diligence | "Are there external integrity due diligence reports?" |
| **REQ-08** | OCCO notes summary | "Summarize OCCO's assessment in past projects" |
| **REQ-09** | Concern type history | "How has OCCO assessed (concern type) for (party role)?" |
| **REQ-10** | Domiciliation analysis | "Has (party) featured in domiciliation notes?" |

### 2.2 Non-Functional Requirements

| Requirement | Description | Priority |
|-------------|-------------|----------|
| **NFR-01** | Livelink Integration | Connect to OpenText Content Server | HIGH |
| **NFR-02** | Document Recency | Return documents ordered by most recent | HIGH |
| **NFR-03** | Entity Recognition | Identify party names, roles, concern types | HIGH |
| **NFR-04** | Multi-doc Synthesis | Aggregate information across documents | MEDIUM |
| **NFR-05** | Audit Trail | Track which documents were used | MEDIUM |
| **NFR-06** | Security | Maintain document-level access controls | HIGH |

---

## 3. Gap Analysis

### 3.1 Critical Gaps (Must Address)

| Gap ID | Current State | Required State | Impact |
|--------|--------------|----------------|--------|
| **GAP-01** | Azure Blob Storage only | Livelink/OpenText integration | HIGH - Core data source missing |
| **GAP-02** | No entity extraction | Party name, role recognition (NER) | HIGH - Cannot search by party |
| **GAP-03** | Basic metadata schema | Extended schema for integrity domains | HIGH - Cannot classify documents |
| **GAP-04** | Single-doc RAG context | Multi-document synthesis | HIGH - Cannot aggregate findings |
| **GAP-05** | No document type classification | DAQ, Due Diligence, Notes categorization | MEDIUM - Cannot filter by type |

### 3.2 Moderate Gaps (Should Address)

| Gap ID | Current State | Required State | Impact |
|--------|--------------|----------------|--------|
| **GAP-06** | Basic chronological sort | Recency-weighted retrieval | MEDIUM - User expectation |
| **GAP-07** | Generic prompts | Domain-specific prompts for integrity | MEDIUM - Response quality |
| **GAP-08** | Chunk-level citations | Document-section citations | MEDIUM - Compliance needs |
| **GAP-09** | No role-based indexing | Party role as metadata | MEDIUM - Query accuracy |
| **GAP-10** | Keyword search only | Complex query understanding | MEDIUM - User experience |

### 3.3 Gap Visualization

```
                         CURRENT BIAB                    REQUIRED FOR AI INTEGRITY
                    ┌────────────────────┐              ┌────────────────────────┐
  Data Sources      │ Azure Blob Storage │      ──►     │ + Livelink Connector   │
                    └────────────────────┘              │ + Multi-source Routing │
                                                        └────────────────────────┘
                                                        
                    ┌────────────────────┐              ┌────────────────────────┐
  Entity Extract    │       None         │      ──►     │ NER for Parties/Roles  │
                    └────────────────────┘              │ Entity Linking         │
                                                        └────────────────────────┘
                                                        
                    ┌────────────────────┐              ┌────────────────────────┐
  Search Schema     │ Basic Metadata     │      ──►     │ Extended Integrity     │
                    │ (file, page, date) │              │ Schema (party, role,   │
                    └────────────────────┘              │ concern, doc_type)     │
                                                        └────────────────────────┘
                                                        
                    ┌────────────────────┐              ┌────────────────────────┐
  Query Processing  │ Single-doc RAG     │      ──►     │ Multi-doc Aggregation  │
                    └────────────────────┘              │ Cross-reference Engine │
                                                        └────────────────────────┘
```

---

## 4. OpenText Livelink Integration Analysis

### 4.1 Livelink REST API Capabilities

OpenText Content Server (Livelink) provides a comprehensive REST API (v1 and v2):

| API Category | Key Endpoints | Use Case |
|--------------|---------------|----------|
| **Authentication** | `POST /v1/auth` | Obtain OTCSTicket |
| **Node Operations** | `GET /v2/nodes/{id}` | Retrieve document metadata |
| **Content Retrieval** | `GET /v2/nodes/{id}/content` | Download document bytes |
| **Search** | `GET /v2/search` | Full-text and metadata search |
| **Categories** | `GET /v2/nodes/{id}/categories` | Retrieve document categories |
| **Versions** | `GET /v2/nodes/{id}/versions` | Access document versions |

### 4.2 Integration Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              EXTENDED ARCHITECTURE WITH LIVELINK INTEGRATION                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                         ┌──────────────────┐                                │
│                         │  Livelink Server │                                │
│                         │  (OpenText CS)   │                                │
│                         └────────┬─────────┘                                │
│                                  │ REST API                                 │
│                                  ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    NEW: DOCUMENT SOURCE LAYER                          │  │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    │  │
│  │  │ Livelink        │    │ Azure Blob      │    │ Source          │    │  │
│  │  │ Connector       │    │ Connector       │    │ Router          │    │  │
│  │  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘    │  │
│  │           │                      │                       │             │  │
│  │           └──────────────────────┴───────────────────────┘             │  │
│  │                                  │                                      │  │
│  │                                  ▼                                      │  │
│  │  ┌───────────────────────────────────────────────────────────────────┐ │  │
│  │  │              NEW: ENRICHMENT PIPELINE                              │ │  │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │ │  │
│  │  │  │ NER Entity  │  │ Document    │  │ Metadata    │               │ │  │
│  │  │  │ Extractor   │  │ Classifier  │  │ Enricher    │               │ │  │
│  │  │  └─────────────┘  └─────────────┘  └─────────────┘               │ │  │
│  │  └───────────────────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                  │                                          │
│                                  ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    EXISTING BIAB COMPONENTS                            │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │  │
│  │  │ RAG         │  │ Azure AI    │  │ LLM Client  │  │ Chat        │  │  │
│  │  │ Orchestrator│  │ Search      │  │             │  │ History     │  │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Livelink Integration Challenges

| Challenge | Description | Mitigation Strategy |
|-----------|-------------|---------------------|
| **Authentication** | OTCSTicket expiration (session-based) | Token refresh service, connection pooling |
| **Network Latency** | On-premises Livelink vs Azure cloud | Caching layer, batch document fetching |
| **Schema Mapping** | Livelink categories to Azure AI Search | ETL transformation layer |
| **Version Management** | Multiple document versions | Latest version retrieval with version tracking |
| **Access Control** | Livelink permissions vs Azure AD | Dual authorization checks |
| **Large Files** | Multipart upload/download handling | Streaming, chunked transfers |

---

## 5. Proposed Solution Approaches

### 5.1 Approach 1: Real-Time Livelink Query (Federated Search)

**Description**: Query Livelink directly at runtime, combine results with Azure AI Search.

```
User Query → Query Parser → [Livelink Search API] + [Azure AI Search] → Result Merger → LLM
```

**Pros**:
- Always up-to-date documents
- No data duplication
- Respects Livelink permissions in real-time

**Cons**:
- Higher latency per query
- Dependent on Livelink availability
- Complex result merging

**Estimated Effort**: 4-6 weeks

---

### 5.2 Approach 2: Incremental Sync (ETL Pipeline)

**Description**: Periodically sync documents from Livelink to Azure AI Search.

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐     ┌─────────────┐
│  Livelink   │ ──► │ Sync Agent  │ ──► │ Enrichment      │ ──► │ Azure AI    │
│  (Source)   │     │ (Scheduler) │     │ Pipeline        │     │ Search      │
└─────────────┘     └─────────────┘     └─────────────────┘     └─────────────┘
```

**Pros**:
- Fast query performance
- Offline resilience
- Full control over indexing

**Cons**:
- Stale data (sync delay)
- Storage duplication
- Complex change detection

**Estimated Effort**: 6-8 weeks

---

### 5.3 Approach 3: Hybrid (Recommended)

**Description**: Combine synced index for search with real-time Livelink fetch for document retrieval.

```
┌────────────────────────────────────────────────────────────────────────────┐
│                           HYBRID APPROACH                                   │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌────────────┐                         ┌────────────────────────────┐    │
│   │ User Query │                         │  Azure AI Search (Synced)  │    │
│   └─────┬──────┘                         │  - Metadata + Embeddings   │    │
│         │                                └──────────────┬─────────────┘    │
│         ▼                                               │                   │
│   ┌────────────────┐     Search      ┌─────────────────┼─────────────┐    │
│   │ Query          │ ───────────────►│ Search results (doc IDs,     │    │
│   │ Orchestrator   │                 │ relevance scores, metadata)   │    │
│   └────────┬───────┘                 └──────────────────┬────────────┘    │
│            │                                            │                   │
│            │ Fetch Document Content                     │                   │
│            ▼                                            ▼                   │
│   ┌────────────────┐                 ┌──────────────────────────────┐     │
│   │ Livelink API   │ ◄───────────────│ Real-time Content Retrieval  │     │
│   │ (Source of     │                 │ (for top-k relevant docs)    │     │
│   │  Truth)        │                 └──────────────────────────────┘     │
│   └────────────────┘                                                       │
│                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

**Pros**:
- Best of both worlds
- Fast search, fresh content
- Scalable architecture

**Cons**:
- More complex implementation
- Requires Livelink connectivity for retrieval

**Estimated Effort**: 8-10 weeks (Recommended)

---

## 6. Required New Components

### 6.1 Livelink Connector Service

```python
# Proposed interface for Livelink integration
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class LivelinkDocument:
    node_id: str
    name: str
    version: int
    content_type: str
    categories: Dict[str, Any]
    created_at: str
    modified_at: str
    
@dataclass 
class LivelinkSearchResult:
    documents: List[LivelinkDocument]
    total_count: int
    facets: Dict[str, List[str]]

class LivelinkConnector(ABC):
    """Abstract base class for Livelink integration."""
    
    @abstractmethod
    async def authenticate(self) -> str:
        """Obtain OTCSTicket for API authentication."""
        pass
    
    @abstractmethod
    async def search_documents(
        self, 
        query: str,
        categories: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50
    ) -> LivelinkSearchResult:
        """Search documents in Livelink."""
        pass
    
    @abstractmethod
    async def get_document_content(
        self, 
        node_id: str, 
        version: Optional[int] = None
    ) -> bytes:
        """Retrieve document content from Livelink."""
        pass
    
    @abstractmethod
    async def get_document_metadata(
        self, 
        node_id: str
    ) -> LivelinkDocument:
        """Get document metadata and categories."""
        pass
```

### 6.2 Enhanced Metadata Schema

```python
# Extended Azure AI Search schema for AI Integrity Assistant
INTEGRITY_ASSISTANT_SCHEMA = {
    # Core fields (from BIAB)
    "id": "string (key)",
    "text": "string (searchable)",
    "vector": "vector (3072 dimensions)",
    "file_name": "string (filterable)",
    "page_number": "int (filterable)",
    
    # New Integrity-specific fields
    "party_names": "Collection(string) (filterable, facetable)",
    "party_roles": "Collection(string) (filterable, facetable)",
    "integrity_concerns": "Collection(string) (filterable, facetable)",
    "mitigating_factors": "Collection(string) (searchable)",
    "document_type": "string (filterable, facetable)",  # DAQ, OCCO Note, DD Report, etc.
    "risk_rating": "string (filterable, facetable)",
    "assessment_date": "datetime (sortable, filterable)",
    "livelink_node_id": "string (filterable)",
    "livelink_version": "int",
    "project_id": "string (filterable)",
    "source_system": "string (filterable)"  # 'livelink' or 'blob'
}
```

### 6.3 Entity Extraction Pipeline

```python
from typing import List, Dict
from dataclasses import dataclass

@dataclass
class ExtractedEntities:
    party_names: List[str]
    party_roles: List[Dict[str, str]]  # {"name": "...", "role": "..."}
    integrity_concerns: List[str]
    mitigating_factors: List[str]
    project_references: List[str]
    risk_ratings: List[str]

class IntegrityEntityExtractor:
    """Extract domain-specific entities from document text."""
    
    def __init__(self, llm_client, custom_patterns: Dict[str, str] = None):
        self.llm = llm_client
        self.patterns = custom_patterns or self._default_patterns()
    
    async def extract_entities(self, text: str) -> ExtractedEntities:
        """Use LLM to extract integrity-relevant entities."""
        prompt = self._build_extraction_prompt(text)
        response = await self.llm.generate(prompt)
        return self._parse_extraction_response(response)
    
    def _default_patterns(self) -> Dict[str, str]:
        return {
            "roles": ["borrower", "shareholder", "director", "EPC contractor", 
                     "parallel lender", "guarantor", "beneficial owner"],
            "concerns": ["political exposure", "criminal investigation", 
                        "sanctions", "corruption", "money laundering",
                        "unclear beneficial ownership", "reputational risk"],
            "doc_types": ["DAQ", "OCCO Note", "Domiciliation Note", 
                         "Due Diligence Report", "Board Paper"]
        }
```

---

## 7. Implementation Roadmap

### 7.1 Phase 1: Foundation (Weeks 1-4)

| Task | Description | Dependencies |
|------|-------------|--------------|
| 1.1 | Livelink API integration POC | Network access to Livelink |
| 1.2 | Authentication service (OTCSTicket) | Livelink credentials |
| 1.3 | Extended Azure AI Search schema | None |
| 1.4 | Basic document sync service | 1.1, 1.2 |

### 7.2 Phase 2: Enrichment (Weeks 5-8)

| Task | Description | Dependencies |
|------|-------------|--------------|
| 2.1 | Entity extraction pipeline | LLM access |
| 2.2 | Document type classifier | Training data |
| 2.3 | Metadata enrichment service | 2.1, 2.2 |
| 2.4 | Incremental sync scheduler | Phase 1 |

### 7.3 Phase 3: Integration (Weeks 9-12)

| Task | Description | Dependencies |
|------|-------------|--------------|
| 3.1 | Enhanced RAG orchestrator | Phases 1-2 |
| 3.2 | Multi-document synthesis | 3.1 |
| 3.3 | Domain-specific prompts | Query analysis |
| 3.4 | Frontend adaptations | UI/UX design |

### 7.4 Phase 4: Testing & Deployment (Weeks 13-16)

| Task | Description | Dependencies |
|------|-------------|--------------|
| 4.1 | Integration testing | All phases |
| 4.2 | Performance optimization | 4.1 |
| 4.3 | Security audit | 4.2 |
| 4.4 | Production deployment | 4.3 |

---

## 8. Difficulty Assessment

### 8.1 Technical Complexity Matrix

| Component | Difficulty | Reason |
|-----------|------------|--------|
| Livelink REST API Integration | 🟡 Medium | Well-documented API, authentication complexity |
| Entity Extraction (NER) | 🔴 High | Domain-specific, requires training/tuning |
| Multi-doc Synthesis | 🔴 High | Complex aggregation logic |
| Extended Search Schema | 🟢 Low | Standard Azure AI Search configuration |
| Sync Pipeline | 🟡 Medium | Change detection, conflict resolution |
| Real-time Content Fetch | 🟡 Medium | Latency, error handling |
| Security Integration | 🟡 Medium | Dual auth (Azure AD + Livelink) |

### 8.2 Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Livelink API rate limits | Medium | High | Caching, batch operations |
| Network latency to on-prem | High | Medium | Edge caching, async processing |
| Entity extraction accuracy | Medium | High | Human-in-the-loop validation |
| Schema migration complexity | Low | Medium | Phased rollout |
| Permission synchronization | Medium | High | Explicit permission mapping |

---

## 9. Cost-Benefit Summary

### 9.1 Reusability from Current BIAB

| Component | Reuse % | Notes |
|-----------|---------|-------|
| Frontend (Streamlit) | 80% | Minor UI additions for new features |
| Backend (FastAPI) | 70% | New endpoints, extended services |
| RAG Orchestrator | 60% | Enhanced for multi-doc |
| Azure AI Search | 90% | Extended schema |
| Auth/Security | 85% | Additional Livelink auth |
| Chat History | 100% | Fully reusable |

**Overall Reuse Estimate**: ~65%

### 9.2 Effort Estimate

| Approach | Development | Testing | Total |
|----------|-------------|---------|-------|
| Federated Search | 4-6 weeks | 2 weeks | 6-8 weeks |
| ETL Pipeline | 6-8 weeks | 3 weeks | 9-11 weeks |
| **Hybrid (Recommended)** | 8-10 weeks | 3 weeks | 11-13 weeks |

---

## 10. Recommendations

### 10.1 Short-Term (Quick Wins)

1. **Extend metadata schema** for integrity-specific fields
2. **Add document type classification** to ingestion pipeline
3. **Create domain-specific prompts** for integrity queries
4. **Implement recency-weighted retrieval** in RAG orchestrator

### 10.2 Medium-Term (Core Delivery)

1. **Develop Livelink Connector Service** with authentication
2. **Implement incremental sync pipeline** with enrichment
3. **Add entity extraction** for party names and roles
4. **Build multi-document synthesis** capability

### 10.3 Long-Term (Enhancement)

1. **Add feedback loop** for entity extraction improvement
2. **Implement audit trail** for compliance
3. **Create admin dashboard** for sync monitoring
4. **Enable cross-system search** (Livelink + Blob)

---

## 11. Conclusion

The Bot in a Box pattern provides a **solid foundation** for the AI Integrity Assistant, with approximately 65% of components directly reusable. The primary challenges are:

1. **Livelink integration** - Requires new connector service
2. **Entity extraction** - Domain-specific NER pipeline
3. **Multi-document synthesis** - Enhanced RAG orchestrator

The **Hybrid Approach** is recommended as it balances query performance with data freshness while leveraging existing BIAB infrastructure.

**Estimated Total Effort**: 11-13 weeks for full implementation

**Key Success Factors**:
- Early access to Livelink API and test environment
- Sample documents for entity extraction training
- Clear document categorization guidelines
- Stakeholder alignment on MVP scope

---

## Appendix A: OpenText Content Server Key API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/auth` | POST | Authenticate, get OTCSTicket |
| `/api/v2/nodes/{id}` | GET | Get node metadata |
| `/api/v2/nodes/{id}/content` | GET | Download document |
| `/api/v2/nodes/{id}/categories` | GET | Get document categories |
| `/api/v2/search` | GET/POST | Search documents |
| `/api/v2/nodes/{id}/versions` | GET | List versions |

## Appendix B: Environment Variables for Extension

```bash
# Existing BIAB Variables
AZURE_OPENAI_ENDPOINT=
AZURE_SEARCH_ENDPOINT=
AZURE_STORAGE_ACCOUNT_NAME=

# New Livelink Variables
LIVELINK_BASE_URL=https://your-livelink-server.com/alpha/cs.exe/api
LIVELINK_USERNAME=
LIVELINK_PASSWORD=
LIVELINK_SYNC_INTERVAL_MINUTES=30
LIVELINK_ROOT_NODE_ID=

# Feature Flags
ENABLE_LIVELINK_INTEGRATION=true
ENABLE_ENTITY_EXTRACTION=true
ENABLE_MULTI_DOC_SYNTHESIS=true
```

---

*Document Version: 1.0*  
*Analysis Date: December 2025*  
*Author: AI Analysis System*