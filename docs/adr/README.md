# Architecture Decision Records

This folder records the significant technical decisions made on Darwin AI
Workbench. Each ADR captures context, decision, and consequences of choosing
one approach over alternatives.

Format loosely follows Michael Nygard's original ADR proposal
(https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

## Numbering

ADRs are numbered sequentially starting at 0001. Once accepted, a number is
never reused even if the ADR is later superseded.

## When to write an ADR

Write an ADR when:

- A decision constrains future work across multiple files or features
- A reasonable alternative was rejected (capture WHY, not just WHAT)
- A future contributor might reasonably wonder "why didnt we just...?"

Don't write an ADR for:

- Implementation details contained within a single module
- Decisions easily reversible in an afternoon

## Index

- [0001 - Foundational project setup](./0001-foundational-project-setup.md):
  Python 3.12, uv as project manager, repo layout per v5.0 spec Section 15.
