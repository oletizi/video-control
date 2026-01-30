# Project Management Standards

**Version:** 2.0
**Created:** 2026-01-29
**Purpose:** Unified project management approach using GitHub

---

## Table of Contents

1. [Overview](#overview)
2. [Feature Design and Planning Workflow](#feature-design-and-planning-workflow)
3. [GitHub Project Organization](#github-project-organization)
4. [Weekly Milestone Structure](#weekly-milestone-structure)
5. [Feature Documentation Standards](#feature-documentation-standards)
6. [Branch and Workplan Requirements](#branch-and-workplan-requirements)
7. [Git Worktree Structure](#git-worktree-structure)
8. [Issue Naming Conventions](#issue-naming-conventions)
9. [Status Tracking](#status-tracking)
10. [Validation Checklist](#validation-checklist)

---

## Overview

This document establishes unified project management standards using GitHub as the primary tracking system. The approach ensures:

- **Clear weekly delivery cadence**: GitHub milestones represent weeks, not features
- **Traceable work items**: Every issue links to feature documentation and code
- **Consistent naming**: Issue titles make project contents immediately understandable
- **Cross-module visibility**: Work across all modules follows the same structure

### Core Principles

1. **Weekly milestones are primary**: All issues belong to the weekly milestone for their delivery week
2. **Issues are organized by milestone**: Maintains hierarchy and enables progress tracking
3. **Feature documentation drives implementation**: Every feature has a workplan with GitHub references
4. **Branch naming aligns with features**: Feature slugs match branch names
5. **Labels organize by domain**: Use labels to categorize work by module or type

---

## Feature Design and Planning Workflow

Features progress through a structured workflow from concept to trackable issues.

### Workflow Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│  1. REQUIREMENTS          2. PLANNING             3. ISSUE CREATION      │
│  ─────────────────        ───────────────         ──────────────────    │
│  Create PRD           →   Create workplan.md  →   Issues added to       │
│  document                                         GitHub via CLI         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Phase 1: Requirements Definition

**Inputs:**

- Feature request or technical need
- User feedback or community requests
- Technical constraints (if known)

**Actions:**

1. **Create feature directory** following naming conventions:

   ```
   docs/<version>/<feature-slug>/
   ```

   Or for module-specific features:

   ```
   modules/<module-name>/docs/<version>/<feature-slug>/
   ```

2. **Write PRD document** (`prd.md`) containing:
   - Problem statement
   - User stories / jobs to be done
   - Success criteria and metrics
   - Scope (in/out of scope)
   - Dependencies and constraints
   - Open questions

**Output:** `docs/<version>/<feature-slug>/prd.md`

### PRD Template

```markdown
# [Feature Name] - Product Requirements Document

**Created:** YYYY-MM-DD
**Status:** Draft | Review | Approved
**Owner:** [Author]

## Problem Statement

[What problem are we solving? Why does it matter?]

## User Stories

- As a [user type], I want [goal] so that [benefit]
- ...

## Success Criteria

- [ ] [Measurable outcome 1]
- [ ] [Measurable outcome 2]

## Scope

### In Scope

- [Feature/capability 1]
- [Feature/capability 2]

### Out of Scope

- [Explicitly excluded item 1]
- [Explicitly excluded item 2]

## Dependencies

- [External dependency 1]
- [Technical dependency 2]

## Open Questions

- [ ] [Question requiring clarification]
- [ ] [Decision needed]

## Appendix

[Supporting research, mockups, references]
```

### Phase 2: Implementation Planning

Once the PRD is approved, create the implementation plan.

**Inputs:**

- Approved PRD (`prd.md`)
- Technical context from codebase exploration
- Resource availability

**Actions:**

1. **Create workplan.md** in the feature directory containing:
   - Technical approach
   - Implementation phases
   - Task breakdown
   - Target delivery week

2. **Create README.md** with status tracking links

3. **Create implementation-summary.md** (draft template for completion)

**Output:** Complete feature documentation directory:

```
docs/<version>/<feature-slug>/
├── prd.md                      # From Phase 1
├── README.md                   # Status and tracking
├── workplan.md                 # Implementation plan
└── implementation-summary.md   # Draft for completion
```

### Phase 3: Issue Creation (via GitHub CLI)

The workplan is decomposed into discrete, actionable issues and added to GitHub.

**Inputs:**

- Completed workplan.md with task breakdown
- Target delivery week
- Module/label assignment

**Actions:**

1. **Identify or create weekly milestone:**
   - Search for existing `Week of [Mon Date]-[Fri Date]` milestone
   - Create if it doesn't exist

2. **Create parent feature issue:**
   - Title: `[module] Feature Name` (e.g., `[core] User Authentication`)
   - Description **must** include:
     - GitHub link to PRD (`prd.md`)
     - GitHub link to workplan (`workplan.md`)
   - Due date: Friday of the delivery week
   - Assign to milestone

3. **Create implementation issues** referencing the parent:
   - Title: Action-focused (e.g., "Add database schema")
   - Description includes:
     - Reference to parent issue (`Part of #NNN`)
     - Link to specific workplan section (if applicable)
     - Acceptance criteria
   - Assign to same milestone

4. **Update workplan.md** with GitHub issue links (parent + implementation)

5. **Update README.md** with milestone link

**GitHub CLI Operations:**

```bash
# 1. List existing milestones
gh milestone list

# 2. Create milestone if needed
gh milestone create "Week of Jan 27-31" --due-date 2026-01-31

# 3. Create parent feature issue
gh issue create \
  --title "[core] User Authentication" \
  --body "$(cat <<'EOF'
## Overview
Brief description of the feature.

## Documentation
- PRD: [link to prd.md]
- Workplan: [link to workplan.md]

## Implementation Tasks
- [ ] #NNN Task 1
- [ ] #NNN Task 2
EOF
)" \
  --milestone "Week of Jan 27-31" \
  --label "core,enhancement"

# 4. Create implementation issues
gh issue create \
  --title "Add authentication validation logic" \
  --body "Part of #NNN

## Acceptance Criteria
- [ ] Validates credentials securely
- [ ] Reports errors clearly" \
  --milestone "Week of Jan 27-31" \
  --label "core"
```

### Task Decomposition Guidelines

When breaking down the workplan into issues:

| Guideline       | Requirement                                                |
| --------------- | ---------------------------------------------------------- |
| **Granularity** | Each issue = 1-2 days of work maximum                      |
| **Actionable**  | Issue title starts with a verb (Implement, Add, Fix, Update) |
| **Testable**    | Clear acceptance criteria in description                   |
| **Independent** | Minimize dependencies between issues where possible        |
| **Traceable**   | Links back to workplan section and PRD requirement         |

**Example Decomposition:**

```
Workplan Phase: "Implement user authentication"
    ↓
Parent Feature Issue:
└── [core] User Authentication (#42)
    ↓
    Implementation Issues (reference parent):
    ├── Create login form component (#43)
    ├── Implement JWT token handling (#44)
    ├── Add session persistence (#45)
    ├── Write authentication tests (#46)
    └── Update documentation (#47)
```

### Workflow Checkpoints

| Checkpoint        | Gate Criteria                                | Who Approves     |
| ----------------- | -------------------------------------------- | ---------------- |
| PRD Complete      | All sections filled, open questions resolved | Maintainer       |
| Workplan Complete | Technical approach validated, tasks defined  | Tech lead        |
| Issues Created    | All issues in GitHub, linked to docs         | Project manager  |

---

## GitHub Project Organization

### Label-Based Organization

Use labels to categorize issues by module and type:

| Label Category | Examples                                      |
| -------------- | --------------------------------------------- |
| Module         | `core`, `api`, `ui`, `cli`, `docs`            |
| Type           | `bug`, `enhancement`, `documentation`, `refactor` |
| Priority       | `priority:high`, `priority:medium`, `priority:low` |
| Status         | `blocked`, `needs-review`, `ready-for-merge` |

### When Work Spans Multiple Modules

If a feature spans multiple modules:

1. Create the primary issue in the **dominant module's label**
2. Add additional module labels
3. Document the cross-module nature in the feature's workplan.md

---

## Weekly Milestone Structure

### Milestone Naming Convention

**Format:** `Week of [Mon Date]-[Fri Date]`

**Examples:**

- `Week of Jan 27-31`
- `Week of Feb 3-7`
- `Week of Feb 10-14`

### Milestone Properties

| Property    | Requirement                               |
| ----------- | ----------------------------------------- |
| Title       | `Week of [Mon Date]-[Fri Date]`           |
| Due Date    | Friday of the delivery week               |
| Description | Brief focus summary for the week          |

### One Milestone Per Week Rule

**CRITICAL**: There should be exactly **one milestone per week** that all features for that week attach to.

### Issue Hierarchy Under Milestones

Issues use a reference-based hierarchy under milestones:

```
Week of Jan 27-31 (milestone)
├── [core] User Authentication (#42) - parent feature
│   ├── Add login validation (#43) - references #42
│   ├── Implement JWT handling (#44) - references #42
│   └── Write integration tests (#45) - references #42
├── [api] Rate Limiting (#46) - parent feature
│   ├── Parse rate config (#47) - references #46
│   └── Add middleware (#48) - references #46
└── [ui] Dashboard Updates (#49) - parent feature
    └── Optimize rendering (#50) - references #49
```

**Rules:**

| Level               | What Goes Here                               | Naming Convention                            |
| ------------------- | -------------------------------------------- | -------------------------------------------- |
| Milestone           | Weekly delivery target                       | `Week of [Mon Date]-[Fri Date]`              |
| Parent Feature Issue | One per feature, assigned to milestone      | `[Module] Feature Name`                      |
| Implementation Issue | Work items, reference parent in body        | Action-focused (e.g., "Add database schema") |

**Benefits:**

- **Clean milestone view** - See features at a glance, not implementation noise
- **Progress tracking** - Feature completion visible at milestone level
- **Easy scoping** - Quickly understand what's in/out of a given week
- **Drill-down** - Click parent issue to see all related implementation issues

### Creating a Weekly Milestone

```bash
# Check for existing milestone
gh milestone list

# Create if it doesn't exist
gh milestone create "Week of Jan 27-31" \
  --due-date 2026-01-31 \
  --description "Focus: User authentication, rate limiting improvements"

# Assign issues to milestone
gh issue edit 42 --milestone "Week of Jan 27-31"
```

### Milestone Completion Summary

At the end of each week, update the milestone description with a summary of completed work:

**Required format:**

```
## Week Summary

### [Feature Name 1]
**Status:** Complete | In Progress | Blocked
**Branch:** feature/[feature-slug]

Brief description of what was accomplished.

**Documentation:**
- PRD: [link to GitHub]
- Workplan: [link to GitHub]
- Implementation Summary: [link to GitHub]

### [Feature Name 2]
...
```

---

## Feature Documentation Standards

### Directory Structure

All projects use consistent documentation structure:

```
docs/
└── <version>/                     # Semantic version (1.0, 1.1, etc.)
    └── <feature-slug>/            # Feature identifier
        ├── prd.md                 # [REQUIRED] Product requirements
        ├── README.md              # [REQUIRED] Status + tracking links
        ├── workplan.md            # [REQUIRED] Implementation plan + GitHub refs
        ├── implementation-summary.md  # [REQUIRED] Post-completion report
        └── [additional docs]      # [OPTIONAL] Phase docs, strategies, etc.
```

For module-specific features:

```
modules/<module-name>/docs/
└── <version>/
    └── <feature-slug>/
        └── [same structure as above]
```

### Version Format

- Use semantic versioning: `1.0`, `1.1`, `2.0`
- Group features by the version they target

### Feature Slug Requirements

| Rule              | Example                |
| ----------------- | ---------------------- |
| 2-4 words maximum | `user-authentication`  |
| Lowercase only    | `rate-limiting`        |
| Hyphen-separated  | `dashboard-updates`    |
| Descriptive       | `parallel-processing`  |

**Invalid examples:**

- `User_Authentication` (uppercase, underscores)
- `user authentication` (spaces)
- `userAuthentication` (camelCase)

---

## Branch and Workplan Requirements

### Feature Branch Naming

**Format:** `feature/<feature-slug>`

**Examples:**

- `feature/user-authentication`
- `feature/rate-limiting`
- `feature/dashboard-updates`

Branch names must match the feature slug in documentation.

### Workplan Requirements

Every feature must have a `workplan.md` that includes:

1. **GitHub tracking section** (at top):

```markdown
# [Feature Name] - Workplan

**GitHub Milestone:** [Week of Jan 27-31](https://github.com/owner/repo/milestone/N)
**GitHub Issues:**

- [Parent: Feature Name (#42)](https://github.com/owner/repo/issues/42)
- [Task 1 Name (#43)](https://github.com/owner/repo/issues/43)
- [Task 2 Name (#44)](https://github.com/owner/repo/issues/44)
```

2. **Implementation phases** with issue references
3. **Success criteria** per phase
4. **Dependencies** (if any)

### Linking Code to Issues

Each GitHub issue description **must** include links to the feature documentation.

**Required format:**

```markdown
## Documentation

- PRD: https://github.com/owner/repo/blob/main/docs/1.0/feature-slug/prd.md
- Workplan: https://github.com/owner/repo/blob/main/docs/1.0/feature-slug/workplan.md

## Code

- Feature Branch: `feature/[feature-slug]`
- Related Issues: #NNN, #NNN
```

**Why GitHub URLs are required:**

- **Portable:** Anyone can click the link from any interface
- **Accessible:** Works without local repository access
- **Versioned:** Links to specific branch show work-in-progress
- **Traceable:** Creates bidirectional linking (docs → issues, issues → docs)

---

## Git Worktree Structure

Git worktrees allow working on multiple features simultaneously without switching branches. Each feature gets its own directory with a dedicated checkout.

### Directory Layout

**Format:** `~/work/<repo-name>-work/<repo-name>-<feature-slug>`

**Structure:**

```
~/work/
├── <repo-name>/                           # Main repository clone (on main branch)
└── <repo-name>-work/                      # Worktree container directory
    ├── <repo-name>-<feature-slug-1>/      # Worktree for feature 1
    ├── <repo-name>-<feature-slug-2>/      # Worktree for feature 2
    └── <repo-name>-<feature-slug-3>/      # Worktree for feature 3
```

**Example for `ol_dsp` repository:**

```
~/work/
├── ol_dsp/                                # Main clone (main branch)
└── ol_dsp-work/                           # Worktree container
    ├── ol_dsp-user-authentication/        # feature/user-authentication
    ├── ol_dsp-rate-limiting/              # feature/rate-limiting
    └── ol_dsp-dashboard-updates/          # feature/dashboard-updates
```

### Creating Worktrees

```bash
# 1. Ensure you're in the main repository
cd ~/work/<repo-name>

# 2. Create the worktree container if it doesn't exist
mkdir -p ~/work/<repo-name>-work

# 3. Create a new worktree for a feature
git worktree add ~/work/<repo-name>-work/<repo-name>-<feature-slug> -b feature/<feature-slug>

# Example:
git worktree add ~/work/ol_dsp-work/ol_dsp-user-auth -b feature/user-auth
```

### Managing Worktrees

```bash
# List all worktrees
git worktree list

# Remove a worktree (after feature is merged)
git worktree remove ~/work/<repo-name>-work/<repo-name>-<feature-slug>

# Prune stale worktree references
git worktree prune
```

### Worktree Naming Rules

| Component        | Format                  | Example                    |
| ---------------- | ----------------------- | -------------------------- |
| Container dir    | `<repo-name>-work`      | `ol_dsp-work`              |
| Worktree dir     | `<repo-name>-<feature>` | `ol_dsp-user-auth`         |
| Branch name      | `feature/<feature-slug>`| `feature/user-auth`        |

### Benefits of This Structure

- **Parallel development**: Work on multiple features without stashing or switching
- **Clean separation**: Each feature has isolated dependencies and build artifacts
- **Easy navigation**: Predictable paths make scripting and tooling straightforward
- **IDE friendly**: Open each worktree as a separate project/workspace

### Cleanup After Merge

When a feature is complete and merged:

```bash
# 1. Remove the worktree
git worktree remove ~/work/<repo-name>-work/<repo-name>-<feature-slug>

# 2. Delete the feature branch (if not auto-deleted by PR merge)
git branch -d feature/<feature-slug>

# 3. Prune any stale references
git worktree prune
```

---

## Issue Naming Conventions

### Issue Title Format

**Format:** `[Module] [Feature]: [Specific Action]`

For parent issues:
**Format:** `[Module] Feature Name`

**Examples:**

| Issue Title                                          | Why It Works                       |
| ---------------------------------------------------- | ---------------------------------- |
| `[core] Auth: Add validation logic`                  | Clear module, feature, and action  |
| `[api] Rate Limiting: Parse controller config`       | Immediately identifies scope       |
| `[ui] Dashboard: Optimize component rendering`       | Module and specific action clear   |

### Module Prefixes

Define module prefixes appropriate to your project. Examples:

| Prefix     | Module                           |
| ---------- | -------------------------------- |
| `[core]`   | Core business logic              |
| `[api]`    | API layer                        |
| `[ui]`     | User interface                   |
| `[cli]`    | Command-line interface           |
| `[docs]`   | Documentation                    |

### What Makes a Good Issue Title

**DO:**

- Be specific about what will be delivered
- Include the module prefix
- Use action verbs (Implement, Add, Fix, Update, Deploy)

**DON'T:**

- Use vague titles like "Work on stuff"
- Omit the module prefix
- Create issues without clear deliverables

---

## Status Tracking

### Status Labels

Use consistent labels across all issues:

| Label          | Meaning                |
| -------------- | ---------------------- |
| `status:planning` | Not yet started     |
| `status:in-progress` | Active work      |
| `status:blocked` | Waiting on dependency |
| `status:review` | Ready for review      |

### Status Markers in Documentation

Use consistent text across all documentation:

| Text        | Meaning                |
| ----------- | ---------------------- |
| Planning    | Not yet started        |
| In Progress | Active work            |
| Complete    | Delivered and verified |
| Blocked     | Waiting on dependency  |

### Status Sync Frequency

| Location         | Update Frequency        |
| ---------------- | ----------------------- |
| GitHub issues    | Daily                   |
| README.md status | Weekly                  |
| workplan.md      | At milestone completion |

### Milestone Completion Checklist

When a weekly milestone completes:

1. Verify all issues are closed or moved to next milestone
2. Update feature README.md status to Complete
3. Fill in implementation-summary.md
4. Update milestone description with Week Summary
5. Close the GitHub milestone
6. Remove feature worktrees for completed/merged features
7. Prune stale worktree references (`git worktree prune`)

---

## Validation Checklist

### Phase 1: Requirements

- [ ] Feature slug chosen (2-4 words, lowercase, hyphen-separated)
- [ ] Feature directory created (`docs/<version>/<feature-slug>/`)
- [ ] PRD created (`prd.md`) with all required sections
- [ ] PRD reviewed and approved

### Phase 2: Planning

- [ ] workplan.md created with implementation phases
- [ ] Task breakdown included in workplan
- [ ] Target delivery week identified
- [ ] Module labels determined
- [ ] README.md created with status tracking
- [ ] implementation-summary.md created (draft template)
- [ ] Worktree created (`~/work/<repo>-work/<repo>-<feature-slug>`)
- [ ] Feature branch created (`feature/<feature-slug>`)

### Phase 3: Issue Creation (via GitHub CLI)

- [ ] Weekly milestone exists or created (`Week of [Mon Date]-[Fri Date]`)
- [ ] Parent feature issue created with milestone (`[Module] Feature Name`)
- [ ] Parent issue description includes GitHub links to PRD and workplan
- [ ] Implementation issues created referencing parent issue
- [ ] Implementation issue titles are action-focused (no module prefix)
- [ ] Implementation issue descriptions include acceptance criteria
- [ ] Issues assigned to milestone with appropriate labels
- [ ] workplan.md updated with GitHub issue links
- [ ] README.md updated with milestone link

### Documentation Complete

- [ ] prd.md has approved status
- [ ] README.md has GitHub milestone link
- [ ] README.md has status marker
- [ ] workplan.md has GitHub issue links
- [ ] workplan.md has implementation phases defined

---

## Quick Reference

### Phase 1: Requirements

```bash
# 1. Determine target version and feature slug
# 2. Create documentation directory
mkdir -p docs/1.0/user-authentication

# 3. Create PRD
# Write docs/1.0/user-authentication/prd.md
# Get approval
```

### Phase 2: Planning

```bash
# 4. Create workplan and supporting docs
# Write docs/1.0/user-authentication/workplan.md
# Write docs/1.0/user-authentication/README.md
# Create docs/1.0/user-authentication/implementation-summary.md (draft)

# 5. Create worktree for feature development
mkdir -p ~/work/<repo>-work
git worktree add ~/work/<repo>-work/<repo>-user-authentication -b feature/user-authentication

# 6. Navigate to worktree
cd ~/work/<repo>-work/<repo>-user-authentication
```

### Phase 3: Issue Creation (via GitHub CLI)

```bash
# 7. Find or create weekly milestone
gh milestone list
gh milestone create "Week of Jan 27-31" --due-date 2026-01-31

# 8. Create parent feature issue
gh issue create \
  --title "[core] User Authentication" \
  --body "Documentation links and overview..." \
  --milestone "Week of Jan 27-31" \
  --label "core,enhancement"

# 9. Create implementation issues
gh issue create \
  --title "Add login validation logic" \
  --body "Part of #42..." \
  --milestone "Week of Jan 27-31" \
  --label "core"

# 10. Update workplan.md and README.md with issue links
```

### Weekly Status Update

1. Review GitHub milestone progress
2. Update README.md status field
3. Close completed issues
4. Move incomplete issues to next milestone if needed
5. Commit documentation changes

---

## Document Control

**Version History:**

- v2.0 (2026-01-29): Migrated to GitHub-only tracking (removed Asana)
- v1.0 (2025-11-25): Initial project management standards with Asana

**Review Cadence:** Quarterly

**Feedback:** Create issue with `documentation` label

---

**This document establishes project management standards. All projects should follow these standards for consistency and cross-project visibility.**
