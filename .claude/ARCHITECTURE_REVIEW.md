# SDM Platform Architectural Review
**Date:** January 24, 2026 (updated January 27, 2026)
**Reviewer:** Claude (Opus 4.5)
**Requested by:** Bryan

---

## Executive Summary

Bryan, I've completed a comprehensive architectural review of the SDM Platform. Overall, the codebase is well-structured for a Django project of this complexity, with good separation between apps and thoughtful use of LangChain/LangGraph. However, I've identified several areas that warrant attention across four key dimensions:

1. **Code Complexity & Duplication** - Several patterns are repeated across the codebase
2. **Third-Party Replacement Opportunities** - Some custom code could leverage existing packages
3. **Architectural Concerns** - Some coupling and assumptions may impede future growth
4. **Database Structure** - A few schema issues and missing fields for analytics

Below is my detailed analysis with recommendations categorized by priority.

---

## 1. Code Complexity & Duplication

### 1.1 Critical Duplications

#### Error Response Formatting (Minor) (COMPLETED)
**Files:** `journeys/views.py`, `memory/views.py`, `llmchat/views.py`

Inconsistent JSON error responses:
- Some use `{"success": False, "error": str}`
- Some use `{"error": str}`

**Recommendation:** Create `utils/responses.py` with `json_error()` and `json_success()` helpers.

### 1.2 Confusing Code Areas

#### Two LLM Execution Paths
**File:** `llmchat/tasks.py`

User messages go through the LangGraph pipeline:
```
send_llm_reply() -> graph.invoke() -> [load_context -> human_turn -> retrieve_and_augment -> call_model -> extract_memories]
```

But AI-initiated messages bypass the graph:
```
send_ai_initiated_message() -> direct model.invoke() -> graph.update_state()
```

This means AI-initiated messages don't go through the `extract_memories` node, creating inconsistent behavior. **Recommendation (Larger Project):** Integrate AI-initiated messages into the graph as a special input type.

---

## 2. Third-Party Replacement Opportunities

### 2.1 High Priority

#### PDF Generation
**Current:** Custom ReportLab implementation in `memory/services/pdf_generator.py`
**Recommendation:** Replace with **WeasyPrint** + **django-weasyprint**

WeasyPrint generates PDFs from HTML/CSS, which would:
- Reduce code by ~60%
- Make styling easier (CSS instead of ReportLab styles)
- Enable reuse of existing Django templates

#### Multi-Step Onboarding Form
**Current:** Custom handling in `journeys/views.py`
**Recommendation:** Consider **django-formtools** (FormWizard) or **django-extra-views**

The current implementation mixes:
- JSON parsing
- User provisioning
- Transaction management
- Session state tracking

A wizard framework would separate these concerns and provide built-in step sequencing.

### 2.2 Medium Priority

#### Document Versioning
**Current:** Custom `bump_version()` method in `evidence/models.py`
**Recommendation:** **django-reversion** for model versioning

This would provide:
- Automatic version tracking
- Rollback capabilities
- Audit trail for changes

#### Document Processing State Machine
**Current:** Boolean `is_processed` field
**Recommendation:** **django-fsm** (Finite State Machine)

States: `uploaded -> queued -> processing -> completed | failed`

This would make the document lifecycle explicit and prevent invalid state transitions.

### 2.3 Lower Priority (Consider Later)

| Area | Current | Potential Package |
|------|---------|-------------------|
| Admin JSON display | Custom HTML in `users/admin.py` | django-admin-json-editor |
| Task progress | Custom status functions | celery-progress |
| Status updates (one-way) | WebSocket | Server-Sent Events (django-sse) |

---

## 3. Architectural Concerns

### 3.1 Critical Concerns


#### Memory Extraction Requires Journey Context
**Impact:** Cannot have non-journey conversations

The memory extraction in `llmchat/tasks.py` assumes every conversation belongs to a journey:
```python
if conversation.journey:
    extract_all_memories.delay(user_id, journey_slug, ...)
else:
    extract_user_profile_memory.delay(...)  # Reduced extraction
```

**Recommendation:** Make memory extraction journey-agnostic with optional journey context enhancement.

### 3.2 Moderate Concerns

#### Fixture-Based Journey Loading
**Impact:** Adding new journeys requires filesystem changes + migrations

Journeys are loaded from JSON fixtures via `journeys/fixtures/journeys/`. There's no admin interface or API for creating journeys dynamically.

**Recommendation:** Add Django admin interface for Journey management (the models already support it).


#### Single Conversation Per User Per Journey
**Impact:** Cannot support multiple concurrent journeys or journey restarts with history

`JourneyResponse` has `unique_together = [["user", "journey"]]`. To restart a journey, the old response must be deleted/archived.

**Recommendation:** Consider adding a `version` or `attempt_number` field if you need to track multiple attempts.

### 3.3 Scaling Considerations (Future)

| Area | Current Limitation | Future Consideration |
|------|-------------------|---------------------|
| WebSocket | Single conversation per connection | Connection pooling for multi-window |
| Thread ID | Based on user email | Use conversation UUID for stability |
| Redis | Single instance assumed | Configure for clustering |
| LLM calls | No retry/fallback logic | Add circuit breaker pattern |

---

## 4. Database Structure Analysis

### 4.2 Missing Analytics Fields

#### Conversation Model (High Priority) (COMPLETED)
Missing fields that would help with reporting:

| Field | Purpose |
|-------|---------|
| `completion_status` | Enum: in_progress, completed, abandoned |
| `duration_seconds` | Total conversation time |
| `is_completed` | Whether SDM journey was completed |

#### User Model (Medium Priority)
| Field | Purpose |
|-------|---------|
| `last_active_at` | Track user engagement |
| `preferred_language` | For future i18n |

#### Document Model (Medium Priority)
| Field | Purpose |
|-------|---------|
| `processing_duration_seconds` | Performance tracking |

### 4.3 JSON Fields That Could Be Normalized

These are currently fine but may need normalization if you need to query/report on them:

| Model | Field | Consideration |
|-------|-------|---------------|
| `Journey` | `onboarding_questions` | If you need to reuse questions across journeys |
| `JourneyOption` | `benefits`, `drawbacks` | If you need to track which benefits users prioritize |
| `ConversationPoint` | `semantic_keywords`, `elicitation_goals` | If you need to query "which points use keyword X" |

### 4.5 Missing Tracking Model

There's no Django-level tracking of which conversation points have been addressed. This data exists only in the LangGraph store, making it impossible to run Django ORM queries like "how many conversations addressed topic X?"

**Recommendation (Larger Project):**
```python
class ConversationPointProgress(models.Model):
    conversation = models.ForeignKey('llmchat.Conversation', on_delete=models.CASCADE)
    conversation_point = models.ForeignKey(ConversationPoint, on_delete=models.CASCADE)
    is_addressed = models.BooleanField(default=False)
    addressed_at = models.DateTimeField(null=True)
    confidence_score = models.FloatField(default=0.0)

    class Meta:
        unique_together = [['conversation', 'conversation_point']]
```

---

## Summary: Prioritized Recommendations

### Medium Projects (Plan for Next Sprint)
7. Replace ReportLab with WeasyPrint for PDF generation

### Larger Projects (Separate Threads)
11. **User Role System:** Full implementation of patient/provider user types with permissions
12. **AI-Initiated Message Refactor:** Integrate into LangGraph pipeline instead of direct model.invoke()
13. **Evidence-Journey Linking:** Add journey association to documents for targeted RAG
14. **ConversationPointProgress Model:** Enable Django-level analytics on topic coverage
15. **Journey Admin Interface:** Allow dynamic journey creation without fixtures

---

This review represents a snapshot analysis. Let me know which areas you'd like to explore further or begin addressing, Bryan.
