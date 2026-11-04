# Strands Agent Web Interface
## Product & Architecture Brief

## 1. Project Overview

Build a web interface for an existing modular Python Strands AI agent using Vercel's AI Chatbot as the starting point.

The web interface will be an additional way to interact with the existing agent, alongside its current CLI adapter.

**The central idea is simple: create another adapter for the existing agent, not another agent.**

The existing Strands agent remains responsible for its intelligence, tools, instructions, authentication and business logic.

The new web adapter should translate communication between the Vercel chatbot frontend and the existing Strands agent.

The initial objective is to get the existing agent working through a browser with minimal changes to the existing architecture.

---

# PART ONE: MVP — WEB ADAPTER

## 2. MVP Objective

The MVP should establish a working connection between the Vercel chatbot and the existing Strands agent.

A user should be able to open the web interface, send a message and receive a response from the same agent currently accessible through the CLI.

The web interface should provide the basic chat experience without requiring changes to how the agent operates internally.

### What the MVP should achieve

1. Display a functional web-based chat interface.
2. Allow users to send messages to the existing Strands agent.
3. Receive and display agent responses.
4. Support streaming responses where practical.
5. Preserve the existing agent's tools and capabilities.
6. Reuse the existing authentication mechanism.
7. Maintain the existing CLI adapter as a separate, working interface.

### What the MVP should NOT include

Do not implement the following as part of the initial version:

- Advanced session management.
- Multiple concurrent agent execution contexts.
- Persistent conversation history and session recovery.
- Pause, resume or interrupt controls.
- Human approval workflows.
- Global tool management dashboards.
- Session-level tool configuration.
- Advanced execution monitoring.
- Full file and artifact management workspace.
- Complex user accounts or authentication systems.

These are future enhancements.

## 3. Proposed MVP Architecture

The initial architecture should be straightforward.

### A. Existing Strands Agent

The existing Python agent remains unchanged wherever possible.

It continues to handle:
- Agent reasoning and response generation.
- Tool invocation.
- Agent instructions.
- Authentication.
- Business logic.
- Model configuration.
- Execution.

### B. Existing CLI Adapter

The CLI adapter remains operational.

It should not be replaced or broken by the new web integration.

### C. New Web Adapter

A new Python adapter/API layer connects the web interface to the existing Strands agent.

Its responsibilities include:
- Receiving messages from the frontend.
- Passing messages to the existing agent interface.
- Receiving agent responses.
- Streaming responses back to the frontend.
- Translating between the frontend's communication protocol and the agent's interaction mechanism.

### D. Vercel Chatbot Frontend

Use Vercel's AI Chatbot as the starting point.

The frontend handles:
- Chat interface.
- Message input.
- Displaying conversation messages.
- Streaming responses.
- Basic loading and error states.

The frontend should not contain Strands-specific business logic.

### Architecture overview

```text
                USER
                  |
                  v
          VERCEL CHATBOT
             FRONTEND
                  |
                  v
          PYTHON WEB ADAPTER
              /       \
             /         \
            v           v
     STRANDS AGENT    RESPONSE
            |
            v
       AGENT TOOLS
```

The existing CLI adapter remains another independent way to communicate with the same agent.

## 4. Technical Considerations

The existing Strands agent is implemented in Python, while the Vercel chatbot uses a Next.js/React frontend.

A backend communication layer is therefore required.

Potential technologies:

- **Frontend:** Next.js and React.
- **Chat interface:** Vercel AI Chatbot.
- **Frontend streaming:** Vercel AI SDK.
- **Backend:** Existing Python environment, potentially FastAPI if appropriate.
- **Agent:** Existing Strands implementation.
- **Communication:** HTTP endpoints and streaming responses.

These are proposed technologies, not mandatory decisions. Inspect the existing repository before selecting the final implementation.

### Adapter responsibilities

The web adapter should:

1. Receive a message from the frontend.
2. Pass the message into the existing agent interaction mechanism.
3. Consume the agent's response.
4. Translate the response into the format expected by the frontend.
5. Stream the response where supported.
6. Return errors in a format the frontend can handle.

The implementation should reuse the existing agent invocation abstractions rather than duplicating agent logic.

### Authentication

The existing agent already has a phone number + OTP authentication mechanism.

The MVP should reuse this mechanism.

Do not build a separate authentication system unless inspection reveals a genuine technical requirement.

The web interface should support the existing authentication interaction as naturally as possible.

### Model configuration

Model selection should not be exposed in the frontend.

The web interface should use whichever model is already configured for the existing agent.

### Conversation handling

For the MVP, focus on basic conversation functionality.

Do not introduce a complex persistence or session-management architecture prematurely.

Claude should inspect how the existing agent handles conversation state and recommend the simplest approach that supports the web interface without breaking existing behaviour.

## 5. MVP Development Approach

Claude should act as the technical architect and development orchestrator.

OpenCode should handle implementation tasks.

The work should proceed in the following order.

### Phase 1: Inspect the existing project

Before making changes, inspect:

- Existing project structure.
- Strands agent implementation.
- CLI adapter.
- Agent invocation mechanism.
- Authentication mechanism.
- Tool registration.
- Response and event handling.
- Dependencies.

Understand how the CLI adapter currently communicates with the agent.

### Phase 2: Set up the frontend

- Obtain and configure the Vercel AI Chatbot starting point.
- Understand its message handling and streaming requirements.
- Establish the frontend/backend communication contract.

### Phase 3: Build the web adapter

- Implement the Python API layer.
- Connect it to the existing Strands agent.
- Reuse existing invocation abstractions.
- Handle incoming messages and outgoing responses.

### Phase 4: Connect the frontend

- Connect the chatbot to the Python backend.
- Implement message submission.
- Display agent responses.
- Implement streaming where practical.
- Handle loading and error states.

### Phase 5: Test the integration

Verify that:

- Messages reach the correct agent.
- Responses are displayed correctly.
- Existing tools remain functional.
- Existing authentication works.
- Conversation behaviour is correct.
- The CLI adapter still works.
- The web adapter does not introduce unintended changes to the agent.

### MVP completion criteria

The MVP is complete when a user can interact with the existing Strands agent through the browser and successfully use its existing capabilities without needing the CLI.

The web interface and CLI should coexist independently.

## 6. Expected MVP Timeline

Initial planning estimate: **2–4 focused working days**, subject to inspection of the existing architecture.

| Task | Estimated time |
|---|---:|
| Inspect existing architecture | 1–3 hours |
| Set up Vercel chatbot | 2–4 hours |
| Build Python web adapter/API | 3–6 hours |
| Connect frontend and backend | 2–4 hours |
| Implement streaming responses | 2–4 hours |
| Integration testing | 2–4 hours |

These are planning estimates, not fixed deadlines. Existing abstractions, authentication integration and streaming compatibility may affect the actual duration.

---

# PART TWO: POST-MVP ROADMAP

The following features are part of the broader product vision.

They should be considered after the basic web adapter is working.

They must not delay or unnecessarily complicate the MVP.

## 7. Multi-session Management

Support multiple independent chat sessions.

Each chat should have its own:
- Conversation history.
- Agent execution context.
- Authentication state.
- Execution history.
- Session-specific settings.
- File workspace.

A conversation in one chat must not carry over into another.

### Session architecture

Use shared agent configuration and reusable resources, but isolated mutable execution contexts.

Multiple sessions should be able to operate independently.

A chat session and an agent execution should be treated as separate concepts. One chat can contain multiple executions.

## 8. Session Persistence and Expiry

Introduce persistent conversation and execution history.

Expected behaviour:

- Chats belong to the browser session that created them.
- Users cannot retrieve conversations using their phone numbers.
- Refreshing the page should restore a valid existing chat.
- Sessions should expire after a configurable period of inactivity.
- Sessions should also have a maximum retention period.
- Expired sessions and their associated data should be deleted.

Active executions should not automatically resume after a server restart.

Interrupted executions should be marked accordingly and made available for inspection.

## 9. Authentication and Security Enhancements

Continue using the existing phone number + OTP mechanism.

Authentication should be scoped to individual chats.

For example:
- Chat A authenticates independently.
- Chat B remains unauthenticated.
- The same phone number can authenticate in both chats, but each requires its own verification.

Keep these concepts separate:

- Authentication: Establishes identity.
- Authorization: Determines permitted actions.
- Approval: Confirms sensitive operations.

All security enforcement must happen on the backend.

## 10. Execution Monitoring

Introduce a dedicated execution activity panel alongside the chat.

The panel should show:
- Current execution status.
- Tool invocations.
- Tool results.
- Timestamps.
- Execution duration.
- Errors.
- Pending approvals.
- Completion status.

Use actual Strands execution events as the source of activity information.

### Progressive disclosure

Default view:
- Searching the web.
- Reading a document.
- Analysing information.
- Preparing results.

Expanded view:
- Tool names.
- Inputs and outputs.
- Timestamps.
- Detailed errors.
- Technical execution information.

Do not expose private model chain-of-thought.

## 11. Human-in-the-Loop Execution Controls

Allow users to control active executions.

Required capabilities:

### Pause
Pause execution at safe interruption points.

### Resume
Continue a paused execution where supported.

### Interrupt and redirect
Cancel the current execution and start another using the existing chat context.

The implementation must account for tools that have already performed external actions.

Investigate Strands checkpointing and execution lifecycle capabilities before deciding how these controls should work.

## 12. Human Approval System

Introduce risk-based approval for sensitive operations.

Illustrative classification:

| Action | Expected behaviour |
|---|---|
| Web search | Automatic |
| Read files | Automatic, subject to access policy |
| Generate documents | Automatic |
| Generate code | Automatic |
| Modify local files | Risk-dependent |
| Delete files | Approval required |
| Send emails/messages | Approval required |
| Destructive commands | Approval required |
| Financial transactions | Approval required |

The approval interface should display the exact proposed action and relevant parameters.

Approval must be enforced by the backend and tied to the exact action being approved.

## 13. Tool Management

Introduce global tool configuration and session-level overrides.

### Global configuration

Allow management of:
- Available tools.
- Global tool availability.
- Tool permissions.
- Approval requirements.

### Session configuration

Allow individual chats to customise tool settings where permitted.

Global security restrictions must always take precedence.

A tool disabled globally must remain disabled in every session.

## 14. File and Artifact Workspace

Introduce a session-specific file workspace.

Expected capabilities:

- Upload files.
- Preview supported formats.
- Download generated artifacts.
- Rename files.
- Organise files.
- Delete files.
- View file metadata.
- Associate files with executions.

Distinguish between:
1. Uploaded files.
2. Generated artifacts.
3. Working files.

The web workspace must not expose unrestricted host filesystem access.

Files must remain isolated between sessions.

## 15. User Interface Enhancements

The broader interface should adopt a ChatGPT-style layout.

### Sidebar
- New Chat.
- Active conversations.
- Previous conversations.
- Session status.
- Settings.

### Main area
- Conversation.
- Message input.
- File attachments.
- Authentication prompts.
- Approval interactions.

### Execution panel
- Agent activity.
- Tool calls.
- Results.
- Errors.
- Execution controls.

### Settings
- Global tool management.
- Session-level configuration.
- Other agent settings.

The interface should remain polished and user-friendly. Technical details should be available through expandable sections rather than dominating the default experience.

---

# PART THREE: INSTRUCTIONS FOR CLAUDE AND OPENCODE

## 16. Development Responsibilities

### Claude — Architect and Orchestrator

Claude should:
- Understand the existing project.
- Identify reusable components.
- Design the integration.
- Break work into manageable tasks.
- Define acceptance criteria.
- Review implementation decisions.
- Identify architectural and security issues.
- Coordinate implementation milestones.

### OpenCode — Implementor

OpenCode should:
- Implement assigned tasks.
- Modify the necessary files.
- Run tests.
- Resolve implementation errors.
- Report completed changes.
- Avoid unrelated refactoring.

## 17. Important Instructions

**Do not overengineer the MVP.**

The first objective is to connect the Vercel chatbot to the existing Strands agent.

Do not implement the entire post-MVP roadmap upfront.

Do not rewrite the agent in JavaScript or TypeScript.

Do not duplicate agent instructions, tools, authentication or business logic in the frontend.

Do not replace the existing CLI adapter.

Do not introduce unnecessary infrastructure before establishing that it is required.

Inspect the existing repository before deciding how the adapter should be implemented.

Prefer extending existing abstractions over introducing new ones.

Keep the implementation modular so that advanced features can be added later without restructuring the MVP.

## 18. Final Product Vision

The long-term objective is a web-based workspace for interacting with and managing an existing modular Strands AI agent.

However, the first version is deliberately much simpler:

**A Vercel chatbot connected to the existing Python Strands agent through a lightweight web adapter.**

Get that working first.

Everything else comes after.