# AI Integrity Assistant: MVP Feasibility Plan

---

## 1. Executive Summary

This document outlines the Minimum Viable Product (MVP) plan for the **AI Integrity Assistant**, a solution enabling compliance officers and bankers to query historical integrity assessments stored in Livelink using natural language.

The MVP will validate the technical feasibility of the proposed architecture before committing to full implementation.

**MVP Duration:** 8 weeks  
**MVP Effort:** ~2 FTE  
**Primary Objective:** Prove real-time Livelink integration with LLM-based document processing

---

## 2. Reference Documents

| Document | Purpose |
|----------|---------|
| AIIntegrityAssessmentAssistant.pdf | Solution architecture and delivery considerations |
| LivelinkAIEnablementApproach.pdf | Strategic recommendations for Livelink AI enablement |
| AIKDD_LivelinkRAGAIChatbotEnablement.pdf | RAG constraints and solution approach |
| LivelinkIntegrationHighLevelDesign.pdf | Custom Adapter design and OAuth2 authentication flow |
| LivelinkAIEnablementAviatorTesting.pdf | Vendor assessment confirming need for custom solution |
| AIKDD_LivelinkMetadataQualityImprovementToolsDRAFT.pdf | Metadata requirements for AI effectiveness |
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

Based on **AIIntegrityAssessmentAssistant.pdf**:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              AZURE                                       │
│                                                                          │
│  ┌─────────────────────┐                                                │
│  │  Integrity Assistant │                                                │
│  │      Frontend        │                                                │
│  └──────────┬──────────┘                                                │
│             │                                                            │
│  ┌──────────▼──────────┐                                                │
│  │  Integrity Assistant │                                                │
│  │      Backend         │                                                │
│  │        + LLM         │                                                │
│  └──────────┬──────────┘                                                │
│             │  1. Search                                                 │
│             │  2. Read document                                          │
│  ┌──────────▼──────────┐                                                │
│  │    Custom Adapter    │                                                │
│  │   (Azure Functions)  │                                                │
│  └──────────┬──────────┘                                                │
│             │                                                            │
└─────────────┼───────────────────────────────────────────────────────────┘
              │
┌─────────────▼───────────────────────────────────────────────────────────┐
│                         DATA CENTRE                                      │
│                                                                          │
│  ┌─────────────────────────────────────────┐                            │
│  │              Livelink                    │                            │
│  │  ┌───────────┐  ┌─────────────────────┐ │                            │
│  │  │ OCCOLink  │  │   Livelink Search   │ │                            │
│  │  └───────────┘  └─────────────────────┘ │                            │
│  └─────────────────────────────────────────┘                            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Authentication Flow

Based on **LivelinkIntegrationHighLevelDesign.pdf**:

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

## 6. MVP Scope

### 6.1 MVP Objective

Validate the feasibility of the architecture by demonstrating:

1. **OAuth2 authentication** flow (EntraID → OTDS token exchange)
2. **Livelink native search** integration via Custom Adapter
3. **Real-time document retrieval** from Livelink
4. **LLM-based answer generation** from document content
5. **End-to-end query response** for basic integrity questions

### 6.2 In Scope

| Component | Deliverable |
|-----------|-------------|
| Custom Adapter | Azure Functions service with OAuth2 authentication |
| Livelink Search | Integration with Livelink search endpoint |
| Document Retrieval | Real-time fetch of document content |
| LLM Processing | Azure OpenAI integration for answer generation |
| Frontend | Chat interface with Livelink document citations |
| Sample Queries | "Has OCCO assessed [party name]?" |

### 6.3 Out of Scope (for MVP)

| Item | Reason |
|------|--------|
| Metadata enrichment pipeline | Phase 2 enhancement |
| Multi-document synthesis | Phase 2 enhancement |
| Master data integration (EBX, Monarch) | Phase 2 enhancement |
| Automated metadata improvement | Separate KDD initiative |
| Full production deployment | Post-MVP activity |

### 6.4 Success Criteria

| Criterion | Target |
|-----------|--------|
| OAuth2 authentication | Successfully obtain OTDS token via EntraID |
| Livelink search | Return relevant documents from OCCOLink |
| Document retrieval | Fetch document content in <5 seconds |
| LLM accuracy | Correct answers on 5 sample queries |
| End-to-end response | Complete query in <15 seconds |
| Stakeholder acceptance | Positive feedback from demo |

---

## 7. MVP Timeline

### 7.1 Phase Overview

| Phase | Duration | Focus |
|-------|----------|-------|
| Phase 1 | Weeks 1-2 | Infrastructure and OAuth2 setup |
| Phase 2 | Weeks 3-4 | Livelink integration |
| Phase 3 | Weeks 5-6 | LLM processing |
| Phase 4 | Weeks 7-8 | Frontend integration and testing |

**Total Duration: 8 weeks**

### 7.2 Detailed Schedule

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
├── Integrate Azure OpenAI
├── Build document content extraction
├── Create integrity-specific prompts
├── Implement citation generation
├── Test with sample OCCO documents
└── Refine prompts based on results

PHASE 4: Frontend & Testing (Weeks 7-8)
├── Integrate chat interface with Custom Adapter
├── Display Livelink document citations
├── End-to-end testing
├── Performance measurement
├── Stakeholder demonstration
└── Feasibility assessment report
```

---

## 8. Resource Requirements

### 8.1 Team Composition

| Role | Allocation | Responsibilities |
|------|------------|------------------|
| Backend Developer | 1 FTE | Custom Adapter, Livelink integration |
| AI/ML Engineer | 0.5 FTE | LLM prompts, document processing |
| DevOps Engineer | 0.25 FTE | Azure Functions, OAuth2 configuration |
| Livelink SME | 0.25 FTE | API guidance, OTDS setup |
| Business Analyst | 0.25 FTE | Requirements validation, UAT |

**Total: ~2.25 FTE for 8 weeks**

### 8.2 Infrastructure

| Resource | Purpose |
|----------|---------|
| Azure Functions | Custom Adapter hosting |
| Azure OpenAI | LLM for document processing |
| Azure App Service | Frontend and Backend hosting |
| Azure Key Vault | Secrets management |

---

## 9. Dependencies and Prerequisites

| Dependency | Owner | Required By | Status |
|------------|-------|-------------|--------|
| OAuth2 configured in Livelink | Livelink Team | Week 1 | ⬜ Pending |
| OTDS token exchange enabled | Livelink Team | Week 2 | ⬜ Pending |
| Network path Azure ↔ Livelink | Infrastructure | Week 1 | ⬜ Pending |
| OCCOLink folder access granted | OCCO / Livelink | Week 3 | ⬜ Pending |
| Sample documents identified | Business | Week 5 | ⬜ Pending |
| Azure OpenAI deployment | AI Team | Week 5 | ⬜ Pending |

---

## 10. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| OAuth2 setup delays | High | High | Early engagement with Livelink team; start in Week -2 |
| OTDS token exchange complexity | Medium | Medium | Allocate buffer time; involve OpenText support |
| Livelink search relevance | Medium | Medium | Plan metadata improvement as follow-on phase |
| Network latency | Medium | Low | Implement response caching |
| LLM accuracy | Low | Medium | Iterative prompt refinement |

---

## 11. Decision Points

| Milestone | Week | Go/No-Go Criteria |
|-----------|------|-------------------|
| OAuth2 Working | 2 | Can obtain OTDS token via EntraID exchange |
| Search Functional | 4 | Can search and retrieve documents from Livelink |
| LLM Answers Accurate | 6 | Correct answers on sample queries |
| Demo Successful | 8 | Stakeholder approval to proceed |

---

## 12. Post-MVP Roadmap

Upon successful MVP completion, the following phases would deliver the full solution:

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| Metadata Improvement | 4 weeks | Entity extraction, document classification, Livelink metadata update |
| Multi-Document Synthesis | 3 weeks | Cross-document aggregation, concern summarization |
| Master Data Integration | 3 weeks | EBX and Monarch integration for entity resolution |
| Production Deployment | 2 weeks | Security hardening, monitoring, performance tuning |

**Full Implementation: 12 weeks after MVP**

---

## 13. Immediate Actions

| # | Action | Owner | Due |
|---|--------|-------|-----|
| 1 | Confirm OAuth2 configuration timeline with Livelink team | Project Lead | Week -2 |
| 2 | Request OTDS token exchange documentation | Livelink SME | Week -2 |
| 3 | Identify OCCOLink test folder and sample documents | Business Analyst | Week -1 |
| 4 | Confirm Azure ↔ Livelink network connectivity | Infrastructure | Week -1 |
| 5 | Allocate development team resources | Project Lead | Week 0 |

---

## 14. Summary

| Item | Value |
|------|-------|
| **MVP Duration** | 8 weeks |
| **MVP Effort** | ~2 FTE |
| **Architecture** | Real-time Livelink access via Custom Adapter |
| **Authentication** | OAuth2 PKCE with EntraID → OTDS token exchange |
| **Search** | Livelink native search endpoint |
| **Processing** | Azure OpenAI LLM |
| **Primary Risk** | OAuth2 configuration dependency |
| **Critical Path** | Livelink team engagement for OAuth2 setup |

The MVP will provide a clear feasibility assessment with minimal investment, enabling an informed decision on full implementation.

---

*Document Version: 1.0*  
*Date: December 2025*  
*Status: Draft*
