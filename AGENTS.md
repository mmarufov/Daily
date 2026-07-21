# Daily App — Agent Guidelines

## Project Overview

iOS news app ("Daily") with a Python FastAPI backend. The iOS app uses SwiftUI, the backend uses FastAPI with OpenAI integration for content processing.

### Structure
- `Daily/` — iOS app (SwiftUI)
  - `Features/{Auth,Chat,News}/` — feature modules with Views, ViewModels
  - `Services/` — BackendService, BackgroundNewsFetcher
  - `Theme/` — AppTheme, styling
  - `Models/` — shared data models
- `backend/` — Python FastAPI backend
  - `app/main.py` — API entry point
  - `app/services/` — OpenAI, content extraction, feeds, news ingestion
- `scripts/` — setup, run, archive scripts

## Workflow Orchestration

Important: PRODUCTION-ONLY fixes, no localhost.

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update tasks/lessons.md with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops

### 4. Verification Before Done
- Never mark a task complete without proving it works
- git diff before/after; match your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Honest Elegance (balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky, "knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer

### 6. Autonomous Bug Fixing
- When given a bug report, just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user

## SwiftUI Guidelines

Follow the SwiftUI patterns from [Dimillian/Skills](https://github.com/Dimillian/Skills/blob/main/swiftui-ui-patterns/SKILL.md).

### State Management
- Use `@State`, `@Binding`, `@Observable`, `@Environment` — avoid unnecessary view models
- Choose ownership location first, then pick the wrapper
- Don't introduce a reference model when plain value state is enough

| Scenario | Pattern |
|---|---|
| Local UI state | `@State` |
| Child mutates parent value | `@Binding` |
| Root-owned model iOS 17+ | `@State` with `@Observable` type |
| Child reads injected model iOS 17+ | Explicit stored property |
| Shared app service | `@Environment(Type.self)` |
| Legacy iOS 16- | `@StateObject` / `@ObservedObject` |

### View Architecture
- Keep views small and focused — prefer composition
- Use async/await with `.task` and explicit loading/error states
- Keep shared services in `@Environment`, feature-local deps via initializer injection
- Prefer newest SwiftUI API that fits the deployment target

### Sheets & Navigation
- Prefer `.sheet(item:)` over `.sheet(isPresented:)` when state represents a selected model
- Sheets should own their actions and call `dismiss()` internally
- No multiple boolean flags for mutually exclusive sheets/alerts/navigation

### Anti-patterns to Avoid
- Giant views mixing layout, logic, networking, routing in one file
- Live service calls in `body`-driven code paths (use `.task` instead)
- Using `AnyView` to work around type mismatches
- Defaulting every dependency to `@EnvironmentObject` without clear ownership reason

### New View Workflow
1. Define state, ownership location, and minimum OS before writing UI
2. Identify `@Environment` vs explicit initializer dependencies
3. Sketch hierarchy, routing, presentation points; extract subviews. **Build first.**
4. Implement async loading with `.task`/`.task(id:)`, plus loading/error states
5. Add previews for primary and secondary states
6. Validate: no compiler errors, previews render, state propagates correctly

## Task Management
- Plan First: Write plan to tasks/plan.md with checklist items
- Track Progress: Mark items complete as you go
- Validate Changes: High-level summary at each step
- Capture Lessons: Update tasks/lessons.md after corrections

## Commit Messages

Use `type: small description` format.

| Type | When to use |
|---|---|
| feat | New user-facing feature |
| fix | Bug fix |
| refactor | Code restructuring (no feature or fix) |
| perf | Performance improvement |
| docs | Documentation only |
| test | Add or modify tests only |
| chore | Maintenance (tooling, deps, scripts) — no runtime change |
| build | Build system / deps affecting build output |
| ci | CI configuration changes |
| style | Formatting only (no logic change) |
| revert | Revert a prior commit |
