# ADR-001: Establish a Clean Python Project Structure

- Status: Accepted
- Date: 2026-08-30
- Decision: Use a src-layout Python project structure

## Context

Life OS began as a collection of documentation, automation scripts,
and product assets. The project was committed to GitHub with the
application files nested under `Desktop/life-os/`.

This structure makes the repository difficult to develop, test,
and eventually package as a software application.

## Decision

Life OS will use the following top-level structure:

```text
src/life_os/     Application source code
tests/           Automated tests
docs/            Product and engineering documentation
scripts/         Developer utilities
.github/         CI/CD workflows