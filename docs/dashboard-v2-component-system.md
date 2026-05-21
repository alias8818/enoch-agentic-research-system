# Dashboard V2 component system

Status: **Vite remains the dashboard shell.** This document defines the shared UI primitives operators see on list and detail pages so new work does not reintroduce one-off page components.

## Decision

Stay on Vite + React for Dashboard V2. New pages should compose from `dashboard/src/components/ui/` instead of copying class names inline.

## Import surface

```ts
import {
  ActionRow,
  EntityLinkChips,
  Eyebrow,
  InlineErrorStateCard,
  LoadingStateCard,
  OperatorDetailSummary,
  OperatorQuestionSections,
  PageShell,
  RawDetails,
  RawJsonDetails,
  StateCard,
} from './ui'
```

## Invariants (enforced by tests)

1. Raw JSON renders only through `RawJsonDetails` / `RawDetails`.
2. Operator detail pages use `OperatorDetailSummary` for state/next-action copy.
3. Loading/error cards use `StateCard` variants.
4. The `components/ui/index.ts` barrel exports every documented primitive.
