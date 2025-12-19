# AI Integrity Assistant: MVP Feasibility Plan

---

## 1. Executive Summary

This document outlines the Minimum Viable Product (MVP) plan for the **AI Integrity Assistant**, a solution enabling compliance officers and bankers to query historical integrity assessments stored in Livelink using natural language.

The MVP will validate the technical feasibility of the proposed architecture before committing to full implementation. This plan includes a gap analysis for extending the existing **Bot in a Box V2 (BIAB V2)** platform. At this point a decision must be taken if to reuse what is possible from BIAB v2 or do completelly something new from scratch. BIAB V2 is a good product for its purpose (blob-based document Q&A), but the Integrity Assistant has fundamentally different requirements (real-time Livelink access). Trying to force one into the other will creates problems for both.

**MVP Duration:** 8 weeks  
**MVP Effort:** ~2 FTE  
**BIAB V2 Reusability:** Hard to provide a good number but ~40%  
**Primary Objective:** Prove real-time Livelink integration with LLM-based document processing

---

## 2. Reference Documents

| Document | Purpose |
|----------|---------|
| https://ebrdtech.atlassian.net/wiki/spaces/AI1/pages/6050873455/AI+Integrity+Assessment+Assistant | Solution architecture and delivery considerations |
| https://ebrdtech.atlassian.net/wiki/spaces/AI1/pages/6065913911/Livelink+AI+Enablement+Approach | Strategic recommendations for Livelink AI enablement |
| https://ebrdtech.atlassian.net/wiki/spaces/AI1/pages/5757534372/AI+KDD+Livelink+RAG+AI+Chatbot+Enablement | RAG constraints and solution approach |
| https://ebrdtech.atlassian.net/wiki/spaces/AI1/pages/6049431553/Livelink+Integration+High+Level+Design | Custom Adapter design and OAuth2 authentication flow |
| https://ebrdtech.atlassian.net/wiki/spaces/AI1/pages/5665718275/Livelink+AI+Enablement+-+Aviator+Testing | Vendor assessment confirming need for custom solution |
| https://ebrdtech.atlassian.net/wiki/spaces/AI1/pages/5757534372/AI+KDD+Livelink+RAG+AI+Chatbot+Enablement | Metadata requirements for AI effectiveness |
| requirements.pdf | User query requirements from business stakeholders |

---

## 3. Business Requirements

Users need to ask questions such as:

| # | Query Type | Example |
|---|------------|---------|
| 1 | Party assessment history | "Has OCCO previously assessed [party name]?" |
| 2 | Integrity concerns | "What concerns were identified for [party]?" |
| 3 | Mitigating factors | "Were there mitigating factors in the assessment?" |
| 4 | Cross-document search | "Are there other documents mentioning [party]?" |
| 5 | Risk ratings | "How were projects risk-rated where [party] was [role]?" |
| 6 | Board disclosures | "What was disclosed to the board regarding [party]?" |
| 7 | Due diligence reports | "Summarize external due diligence reports for [party]" |
| 8 | Historical patterns | "How has OCCO assessed [concern type] for [party role]?" |
| 9 | Domiciliation notes | "Has [party] featured in any domiciliation notes?" |

---

## 4. Architecture Principles

The following principles from the architecture documents guide the solution design:

| Principle | Description |
|-----------|-------------|
| **Authoritative Source** | Data must come from Livelink as the designated source of truth; duplication minimised |
| **Industry Standards** | Use OAuth2 and open standards; avoid proprietary protocols |
| **Real-Time Access** | Prefer real-time Livelink access over custom vector indices |
| **Agentic AI** | Prioritise intelligent orchestration over simple RAG patterns |
| **SIMS Migration** | Design to de-risk future migration to Strategic Information Management System |
| **Least Privilege** | Users access only documents permitted by Livelink ACLs |

---

## 5. Solution Architecture

### 5.1 High-Level Design

Based on **[AI Integrity Assessment Assistant](https://ebrdtech.atlassian.net/wiki/spaces/AI1/pages/6050873455/AI+Integrity+Assessment+Assistant)**:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              AZURE                                      │
│                                                                         │
│  ┌─────────────────────┐                                                │
│  │ Integrity Assistant │                                                │
│  │     Frontend        │                                                │
│  └──────────┬──────────┘                                                │
│             │                                                           │
│  ┌──────────▼──────────┐                                                │
│  │ Integrity Assistant │                                                │
│  │     Backend         │                                                │
│  │       + LLM         │                                                │
│  └──────────┬──────────┘                                                │
│             │  1. Search                                                │
│             │  2. Read document                                         │
│  ┌──────────▼──────────┐                                                │
│  │   Custom Adapter    │                                                │
│  │  (Azure Functions)  │                                                │
│  └──────────┬──────────┘                                                │
│             │                                                           │
└─────────────┼───────────────────────────────────────────────────────────┘
              │
┌─────────────▼───────────────────────────────────────────────────────────┐
│                         DATA CENTRE                                     │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                         Livelink                                    ││
│  │  ┌───────────┐  ┌─────────────────────┐                             ││
│  │  │ OCCOLink  │  │   Livelink Search   │                             ││
│  │  └───────────┘  └─────────────────────┘                             ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Authentication Flow

Based on **[Livelink Integration High Level Design](https://ebrdtech.atlassian.net/wiki/spaces/AI1/pages/6049431553/Livelink+Integration+High+Level+Design)**:

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│   User   │    │ EntraID  │    │  Custom  │    │   OTDS   │    │ Livelink │
│          │    │          │    │ Adapter  │    │          │    │          │
└────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘
     │               │               │               │               │
     │  1. Login     │               │               │               │
     │──────────────►│               │               │               │
     │               │               │               │               │
     │  2. OAuth2    │               │               │               │
     │     Token     │               │               │               │
     │◄──────────────│               │               │               │
     │               │               │               │               │
     │  3. API Call + Token          │               │               │
     │──────────────────────────────►│               │               │
     │               │               │               │               │
     │               │               │  4. Exchange  │               │
     │               │               │     Token     │               │
     │               │               │──────────────►│               │
     │               │               │               │               │
     │               │               │  5. OTDS      │               │
     │               │               │     Token     │               │
     │               │               │◄──────────────│               │
     │               │               │               │               │
     │               │               │  6. API Call  │               │
     │               │               │──────────────────────────────►│
     │               │               │               │               │
     │               │               │  7. Response  │               │
     │               │               │◄──────────────────────────────│
     │               │               │               │               │
     │  8. Answer    │               │               │               │
     │◄──────────────────────────────│               │               │
     │               │               │               │               │
```

**Key Design Decisions:**
- Adapter Public API Authentication: **OAuth2 PKCE**
- Content Server API Authentication: **OpenText Directory Services (OTDS) token**
- Token Exchange: **RFC9693** standard
- Adapter Execution Environment: **Azure Functions**

### 5.3 Query Processing Flow

```
1. User submits natural language query
2. Backend extracts search terms (party name, document type, date range)
3. Custom Adapter searches Livelink using native search endpoint
4. Custom Adapter retrieves relevant documents from Livelink
5. Backend processes documents using Azure OpenAI LLM
6. Backend generates answer with citations to source documents
7. Frontend displays answer with clickable document references
```

---

## 6. Gap Analysis: Bot in a Box V2 Extension

### 6.1 Current BIAB V2 Capabilities

| Component | Current Implementation |
|-----------|------------------------|
| Frontend | Streamlit chat interface with citations |
| Backend | FastAPI with LlamaIndex RAG framework |
| Document Storage | Azure Blob Storage |
| Search | Azure AI Search (hybrid text + vector) |
| Authentication | Azure AD JWT validation |
| Document Processing | PDF and Word upload/indexing |
| Chat History | External chat history service |
| LLM | Azure OpenAI GPT-4o |

### 6.2 Gap Analysis Summary

| Gap ID | Category | Current State (BIAB V2) | Required State (Architecture) | Priority | Effort |
|--------|----------|-------------------------|-------------------------------|----------|--------|
| GAP-01 | Data Source | Azure Blob Storage | Livelink real-time access | 🔴 Critical | High |
| GAP-02 | Search | Azure AI Search vector index | Livelink native search endpoint | 🔴 Critical | High |
| GAP-03 | API Layer | Direct service calls | Custom Adapter (Azure Functions) | 🔴 Critical | High |
| GAP-04 | Authentication | Azure AD JWT only | OAuth2 PKCE + OTDS token exchange | 🔴 Critical | High |
| GAP-05 | Document Retrieval | Blob download | Livelink REST API fetch | 🔴 Critical | Medium |
| GAP-06 | Entity Extraction | None | Party names, roles, concerns | 🟡 High | Medium |
| GAP-07 | Query Understanding | Basic text matching | Integrity-specific NLU | 🟡 High | Medium |
| GAP-08 | Citation Format | Blob URL + page number | Livelink document reference | 🟡 High | Low |
| GAP-09 | Multi-Document Synthesis | Single document context | Cross-document aggregation | 🟡 High | High |
| GAP-10 | Document Classification | Generic file types | OCCO document types (DAQ, Notes, DD) | 🟢 Medium | Medium |

### 6.3 Detailed Gap Analysis

#### GAP-01: Data Source Integration

| Aspect | Detail |
|--------|--------|
| **Current** | Documents uploaded to Azure Blob Storage manually |
| **Required** | Real-time access to documents in Livelink (OCCOLink) |
| **Impact** | Core data source completely different |
| **Resolution** | Build Custom Adapter service; replace blob storage calls with Livelink API calls |
| **BIAB Reuse** | 0% - New component required |

#### GAP-02: Search Mechanism

| Aspect | Detail |
|--------|--------|
| **Current** | Azure AI Search with vector embeddings + text search |
| **Required** | Livelink native search endpoint (no vector index) |
| **Impact** | Search infrastructure completely different |
| **Resolution** | Implement Livelink search wrapper in Custom Adapter; translate queries to Livelink syntax |
| **BIAB Reuse** | 0% - New implementation required |

#### GAP-03: API Abstraction Layer

| Aspect | Detail |
|--------|--------|
| **Current** | Backend calls Azure services directly |
| **Required** | Custom Adapter (Azure Functions) abstracts Livelink complexity |
| **Impact** | New architectural layer needed |
| **Resolution** | Develop Azure Functions service with search, retrieve, metadata endpoints |
| **BIAB Reuse** | 0% - New component required |

#### GAP-04: Authentication Flow

| Aspect | Detail |
|--------|--------|
| **Current** | Azure AD JWT validation for API access |
| **Required** | OAuth2 PKCE with EntraID → OTDS token exchange (RFC9693) |
| **Impact** | Authentication significantly more complex |
| **Resolution** | Implement token exchange service in Custom Adapter; configure OTDS integration |
| **BIAB Reuse** | 30% - EntraID authentication reusable; token exchange new |

#### GAP-05: Document Retrieval

| Aspect | Detail |
|--------|--------|
| **Current** | Stream document from Azure Blob Storage |
| **Required** | Fetch document content via Livelink REST API |
| **Impact** | Different retrieval mechanism |
| **Resolution** | Implement document retrieval endpoint in Custom Adapter |
| **BIAB Reuse** | 20% - Streaming logic partially reusable |

#### GAP-06: Entity Extraction

| Aspect | Detail |
|--------|--------|
| **Current** | No entity extraction |
| **Required** | Extract party names, roles, integrity concerns from queries and documents |
| **Impact** | New NLP capability needed |
| **Resolution** | Implement LLM-based entity extraction in query processing |
| **BIAB Reuse** | 0% - New capability required |

#### GAP-07: Query Understanding

| Aspect | Detail |
|--------|--------|
| **Current** | Generic RAG query processing |
| **Required** | Integrity-specific query understanding (party, role, concern, document type) |
| **Impact** | Domain-specific intelligence needed |
| **Resolution** | Create integrity-specific prompts and query parsers |
| **BIAB Reuse** | 40% - RAG orchestration patterns reusable; prompts new |

#### GAP-08: Citation Format

| Aspect | Detail |
|--------|--------|
| **Current** | Azure Blob URL with page number |
| **Required** | Livelink document reference (node ID, folder path) |
| **Impact** | Citation model changes |
| **Resolution** | Modify citation model to include Livelink metadata |
| **BIAB Reuse** | 70% - Citation display logic reusable; data model modified |

#### GAP-09: Multi-Document Synthesis

| Aspect | Detail |
|--------|--------|
| **Current** | Answer based on single document context |
| **Required** | Aggregate findings across multiple documents for same party |
| **Impact** | Complex orchestration needed |
| **Resolution** | Implement multi-document retrieval and synthesis prompts |
| **BIAB Reuse** | 30% - LLM integration reusable; orchestration new |

#### GAP-10: Document Classification

| Aspect | Detail |
|--------|--------|
| **Current** | Generic PDF/Word file handling |
| **Required** | Classify OCCO document types (DAQ, OCCO Notes, Due Diligence, Domiciliation) |
| **Impact** | Domain-specific classification |
| **Resolution** | Implement document type detection based on Livelink metadata or content |
| **BIAB Reuse** | 50% - File processing reusable; classification new |

### 6.4 Component Reusability Matrix

| BIAB V2 Component | Reusability | Notes |
|-------------------|-------------|-------|
| **Frontend (Streamlit)** | 70% | Chat UI reusable; citations and document viewer need modification |
| **Backend (FastAPI)** | 50% | API structure reusable; service layer needs replacement |
| **RAG Orchestrator** | 30% | LLM integration reusable; retrieval completely different |
| **Azure AI Search Service** | 0% | Not used - replaced by Livelink search |
| **Blob Storage Service** | 0% | Not used - replaced by Livelink retrieval |
| **Chat History Service** | 90% | Fully reusable |
| **Authentication Middleware** | 40% | EntraID validation reusable; OTDS exchange new |
| **Document Processors** | 60% | PDF/Word parsing reusable for content extraction |
| **LLM Client** | 80% | Azure OpenAI integration fully reusable |
| **File Models** | 40% | Base models reusable; Livelink-specific fields needed |

**Overall BIAB V2 Reusability: ~40%**

### 6.5 New Components Required

| Component | Purpose | Effort Estimate |
|-----------|---------|-----------------|
| **Custom Adapter Service** | Azure Functions wrapper for Livelink APIs | 3 weeks |
| **OTDS Token Exchange** | EntraID → OTDS authentication flow | 1 week |
| **Livelink Search Wrapper** | Translate queries to Livelink search syntax | 1 week |
| **Livelink Document Retriever** | Fetch document content via REST API | 1 week |
| **Entity Extractor** | Extract party names, roles, concerns | 1 week |
| **Integrity Query Parser** | Parse user queries for search parameters | 0.5 weeks |
| **Multi-Doc Synthesizer** | Aggregate findings across documents | 1.5 weeks |

---

## 7. MVP Scope

### 7.1 MVP Objective

Validate the feasibility of the architecture by demonstrating:

1. **OAuth2 authentication** flow (EntraID → OTDS token exchange)
2. **Livelink native search** integration via Custom Adapter
3. **Real-time document retrieval** from Livelink
4. **LLM-based answer generation** from document content
5. **End-to-end query response** for basic integrity questions

### 7.2 In Scope

| Component | Deliverable |
|-----------|-------------|
| Custom Adapter | Azure Functions service with OAuth2 authentication |
| Livelink Search | Integration with Livelink search endpoint |
| Document Retrieval | Real-time fetch of document content |
| LLM Processing | Azure OpenAI integration for answer generation |
| Frontend | Chat interface with Livelink document citations |
| Sample Queries | "Has OCCO assessed [party name]?" |

### 7.3 Out of Scope (for MVP)

| Item | Reason |
|------|--------|
| Metadata enrichment pipeline | Phase 2 enhancement |
| Multi-document synthesis | Phase 2 enhancement |
| Master data integration (EBX, Monarch) | Phase 2 enhancement |
| Automated metadata improvement | Separate KDD initiative |
| Full production deployment | Post-MVP activity |

### 7.4 Success Criteria

| Criterion | Target |
|-----------|--------|
| OAuth2 authentication | Successfully obtain OTDS token via EntraID |
| Livelink search | Return relevant documents from OCCOLink |
| Document retrieval | Fetch document content in <5 seconds |
| LLM accuracy | Correct answers on 5 sample queries |
| End-to-end response | Complete query in <15 seconds |
| Stakeholder acceptance | Positive feedback from demo |

---

## 8. MVP Timeline

### 8.1 Phase Overview

| Phase | Duration | Focus |
|-------|----------|-------|
| Phase 1 | Weeks 1-2 | Infrastructure and OAuth2 setup |
| Phase 2 | Weeks 3-4 | Livelink integration |
| Phase 3 | Weeks 5-6 | LLM processing |
| Phase 4 | Weeks 7-8 | Frontend integration and testing |

**Total Duration: 8 weeks**

### 8.2 Detailed Schedule

```
PHASE 1: Infrastructure (Weeks 1-2)
├── Configure OAuth2 in OpenText Livelink instance
├── Set up Azure Functions project for Custom Adapter
├── Implement EntraID authentication
├── Design OTDS token exchange flow
└── Establish development environment with Livelink access

PHASE 2: Livelink Integration (Weeks 3-4)
├── Implement OTDS token exchange (RFC9693)
├── Build Livelink search wrapper
├── Implement document retrieval endpoint
├── Handle Livelink search syntax
├── Test with OCCOLink repository
└── Implement error handling and retry logic

PHASE 3: LLM Processing (Weeks 5-6)
├── Integrate Azure OpenAI (reuse from BIAB V2)
├── Build document content extraction (reuse from BIAB V2)
├── Create integrity-specific prompts
├── Implement citation generation
├── Test with sample OCCO documents
└── Refine prompts based on results

PHASE 4: Frontend & Testing (Weeks 7-8)
├── Modify chat interface for Livelink citations (extend BIAB V2)
├── Update document viewer for Livelink sources
├── End-to-end testing
├── Performance measurement
├── Stakeholder demonstration
└── Feasibility assessment report
```

---

## 9. Summary

| Item | Value |
|------|-------|
| **MVP Duration** | 8 weeks |
| **MVP Effort** | ~2 FTE |
| **BIAB V2 Reusability** | ~40% |
| **Architecture** | Real-time Livelink access via Custom Adapter |
| **Authentication** | OAuth2 PKCE with EntraID → OTDS token exchange |
| **Search** | Livelink native search endpoint |
| **Processing** | Azure OpenAI LLM |
| **Primary Risk** | OAuth2 configuration dependency |
| **Critical Path** | Livelink team engagement for OAuth2 setup |


