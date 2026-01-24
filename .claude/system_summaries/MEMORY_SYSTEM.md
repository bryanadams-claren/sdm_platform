# Memory System Architecture

This document describes how the memory system works in the SDM Platform, particularly for conversation points in shared decision-making journeys.

## Overview

The memory system tracks what information has been discussed with users during their decision-making conversations. It enables the AI to:
- Remember what it has already learned about a user
- Ask targeted follow-up questions instead of repeating questions
- Assess whether conversation goals have been achieved
- Generate personalized summaries

## Key Components

### 1. Conversation Points (Database Model)

**Model**: `sdm_platform/memory/models.py` → `ConversationPoint`

Conversation points represent topics that should be discussed during a journey. Each point is stored in the database and defines:

```python
class ConversationPoint(models.Model):
    journey = ForeignKey(Journey)
    slug = SlugField()  # e.g., "clarify-values"
    title = CharField()  # e.g., "Clarify your values and preferences"
    description = TextField()  # Technical description
    curiosity_prompt = TextField()  # First-person UI text (e.g., "I'd like to understand...")

    # Guidance for the AI
    system_message_template = TextField()  # High-level instruction
    elicitation_goals = JSONField()  # Specific info to gather
    example_questions = JSONField()  # Sample questions to adapt
    completion_criteria = JSONField()  # What "complete" means (informational)
    suggested_questions = JSONField()  # Question starters shown as clickable bubbles

    # Semantic extraction config
    semantic_keywords = JSONField()  # Keywords indicating topic discussed
    confidence_threshold = FloatField()  # Min confidence for "addressed"
```

**Data Source**: `sdm_platform/journeys/fixtures/journeys/backpain.json`

Conversation points are loaded from JSON fixtures via:
```bash
uv run python manage.py load_journeys --force
```

### 2. Conversation Point Memory (LangGraph Store)

**Schema**: `sdm_platform/memory/schemas.py` → `ConversationPointMemory`

For each user × journey × conversation point, we store extracted semantic memory:

```python
class ConversationPointMemory(BaseModel):
    conversation_point_slug: str
    journey_slug: str

    # Semantic content (extracted by LLM)
    is_addressed: bool
    confidence_score: float  # 0.0-1.0
    extracted_points: list[str]  # Key facts learned
    relevant_quotes: list[str]  # User's actual words
    structured_data: dict  # Structured extraction

    # Metadata
    first_addressed_at: datetime | None
    last_analyzed_at: datetime
    message_count_analyzed: int
```

**Storage Location**: LangGraph PostgreSQL store at namespace:
```python
("memory", "users", "<user_id_hash>", "conversation_points", "<journey_slug>")
```

**Manager**: `sdm_platform/memory/managers.py` → `ConversationPointManager`

Key methods:
- `get_point_memory(user_id, journey_slug, point_slug)` - Retrieve memory
- `update_point_memory(...)` - Update/create memory (merge semantics)
- `get_all_point_memories(user_id, journey_slug)` - Get all for journey

### 3. User Profile Memory (LangGraph Store)

**Schema**: `sdm_platform/memory/schemas.py` → `UserProfileMemory`

Demographic and preference information:

```python
class UserProfileMemory(BaseModel):
    name: str | None
    preferred_name: str | None
    birthday: date | None
    updated_at: datetime
    source: Literal["user_input", "llm_extraction", "system"]
```

**Storage Location**: LangGraph PostgreSQL store at namespace:
```python
("memory", "users", "<user_id_hash>", "profile")
```

**Manager**: `sdm_platform/memory/managers.py` → `UserProfileManager`

Key methods:
- `get_profile(user_id)` - Retrieve profile
- `update_profile(user_id, updates)` - Merge updates (only non-None values)
- `format_for_prompt(profile)` - Format for system prompt

## How It Works: Conversation Flow

### When a User Clicks a Conversation Point

**Entry Point**: User clicks conversation point in UI

**API**: `POST /memory/conversation/{conv_id}/points/{point_slug}/initiate/`

**Handler**: `sdm_platform/memory/views.py` → `initiate_conversation_point()`

**Flow**:
1. View marks point as `manually_initiated` in memory store
2. Triggers Celery task: `send_ai_initiated_message.delay(thread_id, user_email, point_slug, journey_slug)`

### AI-Initiated Message Generation

**Task**: `sdm_platform/llmchat/tasks.py` → `send_ai_initiated_message()`

**Process**:
1. **Load conversation point** from database (with elicitation goals/examples)
2. **Load user profile** from LangGraph store
3. **Load point memory** from LangGraph store (what's already known)
4. **Build enhanced system prompt**:
   ```
   [Conversation system prompt]
   [User profile context]

   ## Conversation Point: [Title]
   [Description]

   ## Your Goals for This Discussion
   - [Elicitation goal 1]
   - [Elicitation goal 2]

   ## Example Questions You Could Adapt
   - [Example question 1]
   - [Example question 2]

   ## What You Already Know About This Topic
   Key points already discussed:
   - [Extracted point 1]
   - [Extracted point 2]

   Relevant things the patient has said:
   - "[Quote 1]"
   - "[Quote 2]"

   Build on this knowledge. Don't repeat questions.

   ## Your Task
   Ask ONE clear question that helps achieve your goals.
   ```
5. **Call LLM** with enhanced prompt + recent conversation history
6. **Store AI message** in conversation state
7. **Send via WebSocket** to user

**Key Helper**: `_build_elicitation_context(conversation_point, point_memory)` - Builds the elicitation prompt sections

### After User Responds

**Entry Point**: User sends message

**Task**: `sdm_platform/llmchat/tasks.py` → `send_llm_reply()`

**Flow**:
1. User message goes through normal LangGraph conversation flow
2. Graph includes `extract_memories` node (runs after AI responds)
3. Memory extraction happens automatically

### Memory Extraction

**Task**: `sdm_platform/memory/tasks.py` → `extract_all_memories()`

Called automatically by the conversation graph after each turn.

**Process**:
1. **Extract user profile** via `extract_user_profile_memory()`
2. **Extract conversation points** via `extract_conversation_point_memories()`
3. **Emit status events** for UI feedback:
   - `send_extraction_start()` when extraction begins
   - `send_extraction_complete()` when finished (includes `summary_triggered` flag)
4. **Check for summary generation** - If all points addressed, triggers PDF generation
5. **Pass thread_id** for real-time status updates to frontend

**Process for Each Conversation Point** (`extract_conversation_point_memories()`):
1. **Check if already addressed** with high confidence → skip if yes
2. **Build extraction prompt** with:
   - Conversation point description
   - Semantic keywords
   - Recent messages (since last extraction)
   - Existing memory (for continuity)
3. **Call LLM** to extract:
   ```json
   {
     "is_addressed": true/false,
     "confidence_score": 0.0-1.0,
     "extracted_points": ["list", "of", "facts"],
     "relevant_quotes": ["actual", "user", "quotes"],
     "structured_data": {"key": "value"}
   }
   ```
4. **Merge with existing memory**:
   - Combine `extracted_points` lists (dedupe)
   - Combine `relevant_quotes` lists
   - Update confidence using weighted average
   - Set `first_addressed_at` if newly addressed
5. **Store in LangGraph store**

**Confidence Merging Logic**:
```python
if existing_conf >= 0.8:
    # High existing confidence: bias toward existing
    merged = 0.7 * existing_conf + 0.3 * new_conf
elif existing_conf <= 0.2:
    # Low existing confidence: favor new assessment
    merged = 0.3 * existing_conf + 0.7 * new_conf
else:
    # Mid-range: balanced
    merged = 0.5 * existing_conf + 0.5 * new_conf
```

## Data Flow Diagram

```
User clicks "Clarify Values" conversation point
    ↓
initiate_conversation_point view
    ↓
send_ai_initiated_message task
    ↓
    ├─→ Load ConversationPoint (DB)
    ├─→ Load UserProfileMemory (LangGraph store)
    └─→ Load ConversationPointMemory (LangGraph store)
    ↓
Build enhanced prompt with:
    - What we want to learn (elicitation_goals)
    - Example questions
    - What we already know (extracted_points, quotes)
    ↓
LLM generates targeted question
    ↓
User responds
    ↓
send_llm_reply → conversation graph
    ↓
extract_memories node
    ↓
extract_all_memories task (Celery, async)
    ↓
    ├─→ send_extraction_start (WebSocket status event)
    ├─→ extract_user_profile_memory
    ├─→ extract_conversation_point_memories
    │   └─→ For each conversation point:
    │       ├─→ LLM analyzes if topic discussed
    │       └─→ Updates ConversationPointMemory in store
    ├─→ check_and_trigger_summary_generation
    │   └─→ If all points addressed → generate_conversation_summary_pdf task
    └─→ send_extraction_complete (includes summary_triggered flag)
```

## Key Files

### Models & Schemas
- `sdm_platform/memory/models.py` - Django models (ConversationPoint, ConversationSummary)
- `sdm_platform/memory/schemas.py` - Pydantic schemas (ConversationPointMemory, UserProfileMemory)

### Memory Managers
- `sdm_platform/memory/managers.py` - ConversationPointManager, UserProfileManager

### Tasks
- `sdm_platform/llmchat/tasks.py` - send_ai_initiated_message, send_llm_reply
- `sdm_platform/memory/tasks.py` - extract_all_memories, extract_conversation_point_memories, extract_user_profile, check_and_trigger_summary_generation, generate_conversation_summary_pdf

### Graph Nodes
- `sdm_platform/llmchat/utils/graphs/nodes/memory.py` - extract_memories node (calls extract_all_memories with thread_id)

### Views & APIs
- `sdm_platform/memory/views.py` - API endpoints:
  - `conversation_points_api()` - Get points with completion status (includes curiosity_prompt, suggested_questions)
  - `initiate_conversation_point()` - User clicks point to initiate discussion
  - `conversation_summary_status()` - Check if PDF summary is ready
  - `download_conversation_summary()` - Download PDF summary

### Fixtures
- `sdm_platform/journeys/fixtures/journeys/backpain.json` - Conversation point definitions

### Store & Status
- `sdm_platform/memory/store.py` - LangGraph store utilities (namespacing, connection)
- `sdm_platform/llmchat/utils/status.py` - WebSocket status broadcasts (extraction_start, extraction_complete, summary_complete)

## How Existing Conversations Interact with Updated Conversation Points

When you update conversation point definitions (via `load_journeys --force`):

1. **Database records are updated** - The `ConversationPoint` models get new `elicitation_goals`, `example_questions`, etc.

2. **Existing user memories are preserved** - The `ConversationPointMemory` data in LangGraph store remains intact

3. **Next interaction uses new guidance** - When a user clicks the conversation point again:
   - AI loads the *updated* conversation point (new goals/examples)
   - AI loads the *existing* memory (what's already known)
   - AI asks about what's *missing* using the new guidance

**Example**:
- Before migration: AI knows "User wants to garden again"
- After adding elicitation goal "Identify 2-3 specific activities"
- Next click: AI asks "You mentioned gardening. Are there other activities you miss?"

## Migration Strategy

To update conversation points:

1. Edit `sdm_platform/journeys/fixtures/journeys/backpain.json`
2. Run migration: `uv run python manage.py load_journeys --force`
3. Restart Celery workers (to pick up new code if tasks changed)

No data loss occurs - existing memories are preserved and enhanced by new guidance.

## Testing

### Memory Manager Tests
`sdm_platform/memory/tests.py` - Test classes:
- `UserProfileManagerTest` - Profile CRUD operations
- `ConversationPointManagerTest` - Point memory CRUD operations
- `ConversationPointMemorySchemaTest` - Schema validation
- `ConversationPointExtractionTaskTest` - Extraction logic

### Run Tests
```bash
uv run python manage.py test sdm_platform.memory.tests --keepdb
```

## Future Enhancements

### Potential Areas for Expansion

1. **Programmatic completion criteria** - Currently `completion_criteria` is informational. Could drive actual completion logic in extraction.

2. **Memory-based routing** - Use memory state to automatically suggest next conversation points.

3. **Cross-point memory** - Allow one conversation point to reference memory from another (e.g., values inform option discussion).

4. **Memory decay** - Add time-based confidence degradation for stale memories.

5. **Conflict resolution** - Handle contradictory information across conversation turns.

6. **Multi-modal memory** - Store and reference uploaded documents, images, or structured data.

## Debugging Tips

### View User's Memory

Django admin includes a memory viewer:
- Go to Users → Select user → "View Memory" button
- Shows profile and conversation point memories by journey

### Check Extraction

Look for logs:
```python
logger.info("Extracted conversation point memory for %s/%s:is_addressed=%s, confidence=%.2f")
```

### Force Re-extraction

Delete memory from store and trigger extraction:
```python
from sdm_platform.memory.managers import ConversationPointManager
from sdm_platform.memory.store import get_memory_store

with get_memory_store() as store:
    # This will cause re-extraction on next conversation
    ConversationPointManager.update_point_memory(
        user_id="user@example.com",
        journey_slug="backpain",
        point_slug="clarify-values",
        updates={"is_addressed": False, "confidence_score": 0.0},
        store=store
    )
```

## Type Hints for Reverse Relationships

The `ConversationSummary` model has a OneToOne relationship with `Conversation`:

```python
# In ConversationSummary
conversation = models.OneToOneField(
    "llmchat.Conversation",
    on_delete=models.CASCADE,
    related_name="summary",
)
```

To help IDEs and type checkers understand the reverse relationship (`conversation.summary`), the `Conversation` model includes a type hint:

```python
# In sdm_platform/llmchat/models.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sdm_platform.memory.models import ConversationSummary

class Conversation(models.Model):
    # ... fields ...

    if TYPE_CHECKING:
        # Reverse OneToOne relationship from ConversationSummary
        summary: "ConversationSummary"
```

This prevents IDE warnings when accessing `conversation.summary` while avoiding circular import issues.

## Common Pitfalls

1. **Forgetting to reload journeys** after editing JSON - Changes won't take effect until `load_journeys --force`

2. **Not restarting Celery** after code changes - Tasks cache Python code

3. **Mixing up namespaces** - User profile vs conversation points have different namespaces

4. **Assuming completion_criteria is enforced** - It's currently documentation only

5. **Expecting instant extraction** - Extraction runs after AI response, not immediately

6. **Missing thread_id** - Ensure thread_id is passed to extract_all_memories for status updates to work

## Frontend: Suggestion Bubbles

The chat interface includes clickable "suggestion bubbles" that help users formulate questions.

### How It Works

1. **"Ask A Question" button** (formerly "Guide Me") - Clicking shows default suggestions:
   - "Can you tell me more about..."
   - "What other options haven't we mentioned yet?"
   - "Help me decide between these options..."

2. **Conversation point click** - Clicking a conversation point in the sidebar:
   - Shows that point's `suggested_questions` as bubbles
   - Falls back to defaults if no suggestions configured

3. **Bubble interaction** - Clicking a bubble:
   - Populates the chat input field with the question text
   - Focuses the input for editing
   - Clears the bubbles

### Key Files

- `sdm_platform/templates/llmchat/conversation.html` - Contains `#suggestionBubbles` container
- `sdm_platform/static/js/conversationpoints.js` - Bubble rendering logic:
  - `renderSuggestionBubbles(questions)` - Displays bubbles
  - `handleBubbleClick(question)` - Populates input
  - `clearSuggestionBubbles()` - Removes bubbles
  - Exports via `window.ConversationPoints.renderSuggestions` / `clearSuggestions`
- `sdm_platform/static/css/project.css` - `.suggestion-bubbles` and `.suggestion-bubble` styles

### Configuring Suggestions

Add `suggested_questions` to conversation points in the fixture JSON:

```json
{
  "slug": "clarify-values",
  "title": "Clarify your values and preferences",
  "suggested_questions": [
    "How do I figure out what's most important to me?",
    "What questions should I ask myself?",
    "How does this fit with my lifestyle?"
  ],
  ...
}
```

Then reload: `uv run python manage.py load_journeys --force`

## Summary

The memory system is a two-layer architecture:
1. **Static layer** (DB): Conversation point definitions with AI guidance
2. **Dynamic layer** (LangGraph store): Per-user extracted memories

When the AI initiates a conversation point, it combines both layers to ask informed, targeted questions that build on what it already knows about the user.

The frontend complements this with suggestion bubbles that guide users toward productive questions, with each conversation point able to define its own contextual suggestions.
