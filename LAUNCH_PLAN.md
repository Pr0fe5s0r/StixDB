# StixDB Open-Source Launch Plan

## Phase 1: Pre-Launch (Foundation & Polish)
*Goal: Ensure the repository is "contribution-ready" and the first impression is premium.*

### 1. Documentation & Visuals
*   [x] **README Final Polish**: Add the logo and ensure quickstart works.
*   [ ] **Create a Roadmap**: Add a `ROADMAP.md` or a section in README to communicate future direction (e.g., Qdrant integration, clustering improvements).
*   [ ] **Update Repo Links**: Replace placeholder URLs in `CONTRIBUTING.md` with the actual GitHub URLs.
*   [ ] **Create Issue Templates**: Add `.github/ISSUE_TEMPLATE/bug_report.md` and `feature_request.md`.

### 2. CI/CD & Reliability
*   [ ] **GitHub Actions CI**: Set up `.github/workflows/ci.yml` to run `pytest`, `ruff`, and `mypy` on every PR.
*   [ ] **PyPI Automation**: Automate uploading to PyPI on new tagged releases.

---

## Phase 2: The Launch (The Wave)
*Goal: Generate initial traction.*

### 1. Show HN (Hacker News)
*   Draft a "Show HN" post. Focus on the value prop: "**StixDB — The first memory database with an internal agent that autonomously optimizes its own graph.**"

### 2. Reddit Communities
*   Post in `r/MachineLearning`, `r/Python`, and `r/langchain`.
*   Focus on technical implementation (e.g., why you chose KuzuDB vs. Neo4j).

---

## Phase 3: Post-Launch (Community & Growth)
*Goal: Retain users and turn them into contributors.*

### 1. Engagement
*   **Prompt Issue Responses**: Aim for <24h response time on issues.
*   **Labels for Newcomers**: Use `good first issue` labels.

### 2. Content Marketing
*   Briefly explain "Why Vector DBs aren't enough for long-term memory" in a blog post or X thread.
