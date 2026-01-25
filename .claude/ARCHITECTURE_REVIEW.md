# SDM Platform Architectural Review
**Date:** January 24, 2026
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

#### Access Control Logic (Fix Soon)
**Files:** `llmchat/views.py:20-23` and `memory/views.py:26-42`

Two similar functions handle conversation access:
- `_can_access_conversation()` - returns boolean
- `_get_conversation_for_user()` - returns conversation object

Both implement the same staff-vs-user check. **Recommendation:** Create `utils/permissions.py` with a unified `get_conversation_or_403(user, conv_id)` function.

#### Store Context Manager Pattern (Moderate)
**File:** `memory/managers.py`

This pattern appears **6+ times**:
```python
if store:
    return _get(store)
with get_memory_store() as s:
    return _get(s)
```

**Recommendation:** Create a decorator or base class that handles the store/context-manager fallback automatically.

#### Status Update Broadcasting (Moderate)
**File:** `llmchat/utils/status.py`

7 nearly identical functions (`send_thinking_start`, `send_thinking_end`, etc.) all follow the same pattern. **Recommendation:** Extract to a generic `send_status_update(thread_name, event_type, **data)` function.

#### Error Response Formatting (Minor)
**Files:** `journeys/views.py`, `memory/views.py`, `llmchat/views.py`

Inconsistent JSON error responses:
- Some use `{"success": False, "error": str}`
- Some use `{"error": str}`

**Recommendation:** Create `utils/responses.py` with `json_error()` and `json_success()` helpers.

### 1.2 Confusing Code Areas

#### `conv_id` vs `thread_id` in Conversation Model
**File:** `llmchat/models.py`

Two identifiers for the same conversation:
- `conv_id` - used in URLs and views
- `thread_id` - used for LangChain/graph history (unique constraint)

This creates confusion about which is the "source of truth." **Recommendation:** Document the distinction clearly or consolidate. Consider making `thread_id` derived from `conv_id` via a consistent transformation.

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

#### No User Role/Type System
**Impact:** Cannot add provider workflows

The `User` model has no concept of user types (patient vs provider vs admin). The system assumes all users are patients. Adding provider features (reviewing patient progress, multi-user conversations) would require significant refactoring.

**Recommendation (Larger Project):** Add a `user_type` or role field:
```python
class User(AbstractUser):
    class UserType(models.TextChoices):
        PATIENT = 'patient', 'Patient'
        PROVIDER = 'provider', 'Provider'
        ADMIN = 'admin', 'Admin'

    user_type = models.CharField(max_length=20, choices=UserType.choices, default=UserType.PATIENT)
```

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

#### Hardcoded LLM Model References
**Impact:** Switching providers requires code changes in 4+ places

Model selection is scattered:
- `llmchat/utils/graphs/base.py`: `CURRENT_MODEL = "openai:gpt-4.1"`
- `memory/tasks.py`: `EXTRACTION_MODEL = "openai:gpt-4.1"`
- `memory/services/narrative.py`: hardcoded in function call
- `llmchat/tasks.py`: hardcoded in `send_ai_initiated_message()`

**Recommendation:** Centralize in Django settings:
```python
# config/settings/base.py
LLM_CHAT_MODEL = env("LLM_CHAT_MODEL", default="openai:gpt-4.1")
LLM_EXTRACTION_MODEL = env("LLM_EXTRACTION_MODEL", default="openai:gpt-4.1")
```

### 3.2 Moderate Concerns

#### Fixture-Based Journey Loading
**Impact:** Adding new journeys requires filesystem changes + migrations

Journeys are loaded from JSON fixtures via `journeys/fixtures/journeys/`. There's no admin interface or API for creating journeys dynamically.

**Recommendation:** Add Django admin interface for Journey management (the models already support it).

#### Evidence Not Linked to Journeys
**Impact:** All evidence is searched for all journeys

Documents in the evidence app have no journey association. The RAG retrieval searches all collections regardless of which journey the conversation belongs to.

**Recommendation (Larger Project):** Add `journey` ForeignKey to Document model:
```python
class Document(models.Model):
    journey = models.ForeignKey(
        'journeys.Journey',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        help_text="If set, this evidence only applies to this journey"
    )
```

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

### 4.1 Cascade Delete Issues (Fix Soon)

**File:** `journeys/models.py:199-202`

```python
class JourneyResponse(models.Model):
    journey = models.ForeignKey(Journey, on_delete=models.DO_NOTHING, ...)
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING, ...)
```

Using `DO_NOTHING` will leave orphaned records if a Journey or User is deleted. The comment mentions archiving but there's no `archived_at` field.

**Recommendation:** Either:
1. Change to `on_delete=models.PROTECT` (prevent deletion if responses exist)
2. Add soft-delete fields (`is_archived`, `archived_at`) and implement properly
3. Change to `on_delete=models.CASCADE` if data loss is acceptable

### 4.2 Missing Analytics Fields

#### Conversation Model (High Priority)
Missing fields that would help with reporting:

| Field | Purpose |
|-------|---------|
| `message_count` | Track engagement without querying LangChain store |
| `last_message_at` | When was conversation last active |
| `completion_status` | Enum: in_progress, completed, abandoned |
| `duration_seconds` | Total conversation time |
| `is_completed` | Whether SDM journey was completed |

#### User Model (Medium Priority)
| Field | Purpose |
|-------|---------|
| `user_type` | Patient vs Provider vs Admin |
| `last_active_at` | Track user engagement |
| `preferred_language` | For future i18n |

#### Document Model (Medium Priority)
| Field | Purpose |
|-------|---------|
| `processing_status` | Enum: queued, processing, completed, failed |
| `processing_error` | Store error message on failure |
| `processing_duration_seconds` | Performance tracking |

### 4.3 JSON Fields That Could Be Normalized

These are currently fine but may need normalization if you need to query/report on them:

| Model | Field | Consideration |
|-------|-------|---------------|
| `Journey` | `onboarding_questions` | If you need to reuse questions across journeys |
| `JourneyOption` | `benefits`, `drawbacks` | If you need to track which benefits users prioritize |
| `ConversationPoint` | `semantic_keywords`, `elicitation_goals` | If you need to query "which points use keyword X" |

### 4.4 Vector Storage Concern

**File:** `evidence/models.py:84`

```python
embedding_cached = models.JSONField(blank=True, default=dict)
```

Storing embeddings (1536-dimension vectors) in a JSONField is inefficient. The vectors are already in ChromaDB, so this field is redundant.

**Recommendation:** Either:
1. Remove the field (vectors live in ChromaDB)
2. Or if local caching is needed, consider pgvector extension

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

### Quick Wins (Do This Week)
1. Create `utils/permissions.py` with unified conversation access check
2. Create `utils/responses.py` with standardized JSON response helpers
3. Fix `JourneyResponse` cascade delete (change to PROTECT or add soft-delete)
4. Add `message_count` and `last_message_at` to Conversation model

### Medium Projects (Plan for Next Sprint)
5. Centralize LLM model configuration in Django settings
6. Remove conv_id and use thread_id everywhere
7. Replace ReportLab with WeasyPrint for PDF generation
8. Add `user_type` field to User model
9. Add `processing_status` and `processing_error` to Document model
10. Refactor status broadcasting to use generic helper function

### Larger Projects (Separate Threads)
11. **User Role System:** Full implementation of patient/provider user types with permissions
12. **AI-Initiated Message Refactor:** Integrate into LangGraph pipeline instead of direct model.invoke()
13. **Evidence-Journey Linking:** Add journey association to documents for targeted RAG
14. **ConversationPointProgress Model:** Enable Django-level analytics on topic coverage
15. **Journey Admin Interface:** Allow dynamic journey creation without fixtures

---

## Files Referenced

| File | Issues Found |
|------|--------------|
| `llmchat/views.py` | Access control duplication |
| `llmchat/tasks.py` | Two LLM execution paths, hardcoded model |
| `llmchat/models.py` | conv_id/thread_id confusion |
| `llmchat/utils/status.py` | Duplicated status functions |
| `memory/views.py` | Access control duplication |
| `memory/managers.py` | Store context pattern duplication |
| `memory/tasks.py` | Hardcoded model, extraction assumptions |
| `memory/services/pdf_generator.py` | Could use WeasyPrint |
| `journeys/models.py` | Cascade delete issues |
| `journeys/views.py` | Could use form wizard |
| `evidence/models.py` | Missing processing status fields |

---

This review represents a snapshot analysis. Let me know which areas you'd like to explore further or begin addressing, Bryan.
