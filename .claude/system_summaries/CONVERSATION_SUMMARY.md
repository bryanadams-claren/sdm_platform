# Conversation Summary System
**SDM Platform – Persistent Conversation Memory & Review Context**

---

## 1. Purpose

This document defines the **Conversation Summary System** used by the `sdm_platform` to preserve high-value context from long-running conversations. It is intended to be loaded into future sessions to:

- Rapidly re-establish system intent and prior decisions
- Enable efficient review of system performance
- Support safe iteration, refactoring, and feature evolution
- Reduce reliance on full conversation transcripts

This file functions as **authoritative persistent context**, not as a user-facing artifact.

---

## 2. Application Context

- **Platform**: `sdm_platform`
- **Framework**: Django
- **Domain**: LLM-powered conversational application
- **Primary Concern**: Durable conversational memory across sessions and models
- **Primary Actor**: Individual user journeys spanning multiple conversations

---

## 3. Problem Being Solved

Raw conversation logs are:
- Too large to reload efficiently
- Poorly structured for evaluation or change planning
- Unsuitable as long-term system memory

The Conversation Summary System provides a **compressed, structured representation** of conversations that preserves intent, decisions, and system behavior while remaining concise and actionable.

---

## 4. Design Goals

- **Concise but information-dense**
- **Deterministic structure**
- **Human-readable and model-ingestable**
- **Optimized for diagnostics and iteration**
- **Stable across model upgrades**

---

## 5. Core Concepts

### 5.1 Conversation / Journey
A long-running interaction arc with a user, often spanning multiple sessions.

- Identified via `conversation_id` or slug
- Represents evolving goals, constraints, and outcomes

### 5.2 Conversation Summary
A structured condensation of a journey that captures:
- Intent
- Decisions
- Assumptions
- System behavior
- Open issues

Stored separately from raw transcripts.

### 5.3 Memory
Durable knowledge extracted from conversations that should persist across sessions, distinct from ephemeral dialogue.

---

## 6. Responsibilities of the Summary

Each summary SHOULD capture:

- **User Goals**
  - Primary objectives
  - Secondary or evolving goals

- **Key Decisions**
  - Architectural choices
  - Behavioral constraints
  - Trade-offs made

- **System Assumptions**
  - Explicit or implicit assumptions guiding behavior

- **Implementation Notes**
  - Relevant technical details
  - Integration points
  - Known limitations

- **Issues & Risks**
  - Observed failures or friction
  - Edge cases
  - Model or logic weaknesses

- **Open Questions / TODOs**
  - Deferred decisions
  - Areas requiring validation or redesign

---

## 7. Update Strategy

- Summaries are updated:
  - At defined checkpoints
  - After major decision points
  - When goals materially change

- Updates should:
  - Preserve prior context unless explicitly invalidated
  - Avoid speculative or low-confidence assertions
  - Favor clarity over verbosity

---

## 8. Usage in Future Conversations

When loaded into a new session, this summary should be treated as:

- Authoritative historical context
- The baseline for evaluating new proposals
- A guardrail against regressions or design drift

Raw conversation logs should only be consulted if:
- Specific wording matters
- A discrepancy is identified
- The summary is suspected to be incomplete or incorrect

---

## 9. Non-Goals

- Not a replacement for full transcripts
- Not intended for end-user visibility
- Not an audit log
- Not a narrative or conversational artifact

---

## 10. Open Design Considerations

The following remain intentionally unresolved:

- Optimal summarization cadence (event-based vs time-based)
- Automation vs human-in-the-loop editing
- Versioning and diffing strategies
- Formal schema (JSON/YAML) vs structured prose
- Memory decay and pruning rules

---

## 11. Change Log (Optional)

Use this section to track material updates to the summary system itself.

- YYYY-MM-DD — Description of change
- YYYY-MM-DD — Description of change

---

## 12. Recommended Next Steps

Possible extensions of this system include:

- Formal schema definition for summaries
- Automated summary validation checks
- Tooling for diffing summary versions
- Evaluation metrics for summary quality
- Integration with memory pruning logic

---

**End of Document**
