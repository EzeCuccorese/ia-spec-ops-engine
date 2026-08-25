# Functional Specification (`spec.md`)

**Feature**: {feature_name}  
**Date**: {date}  
**Status**: 🟢 SPECIFIED / 🟡 UNDER REVIEW

---

## 🎯 1. User Story
**As a** {user_role},  
**I want to** {desired_action},  
**So that** {business_benefit}.

---

## 🧪 2. Acceptance Criteria (Gherkin Scenarios)

### Scenario 1: {Happy path scenario title}
- **Given** {precondition state},
- **When** {action is triggered},
- **Then** {expected outcome},
- **And** {additional confirmation}.

### Scenario 2: {Edge case / Error scenario title}
- **Given** {invalid precondition state},
- **When** {action is triggered},
- **Then** {appropriate error response is returned}.

---

## 🛡️ 3. Non-Functional Requirements (NFRs)
- **Performance**: Response time $< 200\\text{ms}$ at 95th percentile.
- **Security**: Authentication required via JWT Bearer token.
- **Reliability**: Idempotent execution on retried requests.
