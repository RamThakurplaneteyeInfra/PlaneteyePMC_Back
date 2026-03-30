# DPR Approval Workflow

## Overview

The Daily Progress Report (DPR) approval workflow implements a multi-level approval system where DPRs submitted by Site Engineers go through a hierarchical approval process.

## Approval Flow

```
Site Engineer submits DPR
         ↓
    Team Lead approves/rejects
         ↓
    Coordinator approves/rejects
         ↓
    PMC Head approves/rejects
         ↓
      Approved
```

## Status Values

| Status | Description |
|--------|-------------|
| `draft` | Initial state when DPR is created |
| `pending_team_lead` | Waiting for Team Lead approval |
| `pending_coordinator` | Waiting for Coordinator approval |
| `pending_pmc_head` | Waiting for PMC Head approval |
| `approved` | Fully approved by all roles |
| `rejected` | Rejected by any role with reason |

## API Endpoints

### 1. Submit DPR for Approval

**Endpoint:** `POST /api/dpr/{id}/submit/`

**Description:** Site Engineer submits DPR to start the approval workflow.

**Request Body:**
```json
{
  "role": "Site Engineer"
}
```

**Response:** Updated DPR with status `pending_team_lead`

---

### 2. Team Lead Approval

**Endpoint:** `POST /api/dpr/{id}/approve_team_lead/`

**Description:** Team Lead approves DPR and sends it to Coordinator.

**Request Body:**
```json
{
  "role": "Team Leader"
}
```

**Response:** Updated DPR with status `pending_coordinator`

---

### 3. Coordinator Approval

**Endpoint:** `POST /api/dpr/{id}/approve_coordinator/`

**Description:** Coordinator approves DPR and sends it to PMC Head.

**Request Body:**
```json
{
  "role": "Coordinator"
}
```

**Response:** Updated DPR with status `pending_pmc_head`

---

### 4. PMC Head Approval

**Endpoint:** `POST /api/dpr/{id}/approve_pmc_head/`

**Description:** PMC Head gives final approval to DPR.

**Request Body:**
```json
{
  "role": "PMC Head"
}
```

**Response:** Updated DPR with status `approved`

---

### 5. Reject DPR

**Endpoint:** `POST /api/dpr/{id}/reject/`

**Description:** Any role can reject DPR with a reason. The DPR is sent back to all lower roles for review.

**Request Body:**
```json
{
  "role": "Team Leader",
  "rejection_reason": "Missing activity details and target achieved percentages"
}
```

**Response:** Updated DPR with status `rejected` and rejection reason

**Rejection Behavior:**
- If Team Lead rejects → DPR goes back to Site Engineer
- If Coordinator rejects → DPR goes back to Team Lead and Site Engineer
- If PMC Head rejects → DPR goes back to Coordinator, Team Lead, and Site Engineer

---

### 6. Get Pending Approvals

**Endpoint:** `GET /api/dpr/pending_approval/?role={role}`

**Description:** Get all DPRs pending approval for a specific role.

**Query Parameters:**
- `role` (required): Role to filter by (`Team Leader`, `Coordinator`, `PMC Head`)

**Response:** List of DPRs pending approval for the specified role

---

### 7. Get Rejected DPRs

**Endpoint:** `GET /api/dpr/rejected/?role={role}`

**Description:** Get all rejected DPRs that need to be reviewed by a specific role.

**Query Parameters:**
- `role` (required): Role to filter by (`Team Leader`, `Coordinator`, `PMC Head`)

**Response:** List of rejected DPRs

---

## DPR Fields

### New Approval Fields

| Field | Type | Description |
|-------|------|-------------|
| `status` | CharField | Current approval status |
| `submitted_by` | ForeignKey | User who submitted the DPR |
| `current_approver_role` | CharField | Role that should currently approve |
| `rejection_reason` | TextField | Reason for rejection |
| `rejected_by` | ForeignKey | User who rejected the DPR |
| `approved_by` | ForeignKey | User who finally approved the DPR |
| `approved_at` | DateTimeField | Timestamp when DPR was approved |

---

## Example Workflow

### 1. Site Engineer Creates and Submits DPR

```bash
# Create DPR
curl -X POST http://localhost:8000/api/dpr/ \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "Highway Project",
    "job_no": "JOB-2024-001",
    "report_date": "2024-01-15",
    "issued_by": "pmc_se",
    "designation": "Site Engineer",
    "activities": [
      {
        "date": "2024-01-15",
        "activity": "Foundation excavation",
        "target_achieved": 85.5
      }
    ]
  }'

# Submit DPR for approval
curl -X POST http://localhost:8000/api/dpr/2/submit/ \
  -H "Content-Type: application/json" \
  -d '{"role": "Site Engineer"}'
```

### 2. Team Lead Approves

```bash
curl -X POST http://localhost:8000/api/dpr/2/approve_team_lead/ \
  -H "Content-Type: application/json" \
  -d '{"role": "Team Leader"}'
```

### 3. Coordinator Approves

```bash
curl -X POST http://localhost:8000/api/dpr/2/approve_coordinator/ \
  -H "Content-Type: application/json" \
  -d '{"role": "Coordinator"}'
```

### 4. PMC Head Approves

```bash
curl -X POST http://localhost:8000/api/dpr/2/approve_pmc_head/ \
  -H "Content-Type: application/json" \
  -d '{"role": "PMC Head"}'
```

### 5. Rejection Example

```bash
# Team Lead rejects DPR
curl -X POST http://localhost:8000/api/dpr/2/reject/ \
  -H "Content-Type: application/json" \
  -d '{
    "role": "Team Leader",
    "rejection_reason": "Missing activity details and target achieved percentages"
  }'

# Site Engineer can now modify and resubmit
curl -X PATCH http://localhost:8000/api/dpr/2/ \
  -H "Content-Type: application/json" \
  -d '{
    "activities": [
      {
        "date": "2024-01-15",
        "activity": "Foundation excavation with detailed specifications",
        "target_achieved": 85.5
      }
    ]
  }'

# Resubmit DPR
curl -X POST http://localhost:8000/api/dpr/2/submit/ \
  -H "Content-Type: application/json" \
  -d '{"role": "Site Engineer"}'
```

---

## Role Permissions

| Role | Can Submit | Can Approve | Can Reject | Can View All |
|------|------------|-------------|------------|--------------|
| Site Engineer | ✓ | ✗ | ✗ | ✗ |
| Billing Site Engineer | ✓ | ✗ | ✗ | ✗ |
| QAQC Site Engineer | ✓ | ✗ | ✗ | ✗ |
| Team Leader | ✗ | ✓ | ✓ | ✓ |
| Coordinator | ✗ | ✓ | ✓ | ✓ |
| PMC Head | ✗ | ✓ | ✓ | ✓ |
| CEO | ✗ | ✓ | ✓ | ✓ |

---

## Database Schema

```sql
-- New fields added to dailyprogressreport table
ALTER TABLE dailyprogressreport ADD COLUMN status VARCHAR(25) DEFAULT 'draft';
ALTER TABLE dailyprogressreport ADD COLUMN submitted_by_id INTEGER REFERENCES auth_user(id);
ALTER TABLE dailyprogressreport ADD COLUMN current_approver_role VARCHAR(50);
ALTER TABLE dailyprogressreport ADD COLUMN rejection_reason TEXT;
ALTER TABLE dailyprogressreport ADD COLUMN rejected_by_id INTEGER REFERENCES auth_user(id);
ALTER TABLE dailyprogressreport ADD COLUMN approved_by_id INTEGER REFERENCES auth_user(id);
ALTER TABLE dailyprogressreport ADD COLUMN approved_at TIMESTAMP;
```

---

## Testing

Run the test script to verify the approval workflow:

```bash
cd backend
python test_dpr_workflow.py
```

Expected output:
```
Created DPR: 2 Status: draft
Submitted DPR: 2 Status: pending_team_lead Current Approver: Team Leader
Team Lead approved: 2 Status: pending_coordinator Current Approver: Coordinator
Coordinator approved: 2 Status: pending_pmc_head Current Approver: PMC Head
PMC Head approved: 2 Status: approved
Created DPR2: 3 Status: pending_team_lead
Rejected DPR2: 3 Status: rejected Reason: Missing activity details

All tests passed!
```

---

## Notes

1. **Resubmission:** When a DPR is rejected, the Site Engineer can modify it and resubmit it for approval.

2. **Rejection Reason:** The rejection reason is mandatory when rejecting a DPR.

3. **Approval Chain:** The approval must follow the chain: Team Lead → Coordinator → PMC Head.

4. **Status Tracking:** The `current_approver_role` field tracks which role should currently approve the DPR.

5. **Audit Trail:** The `rejected_by` and `approved_by` fields provide an audit trail of who rejected or approved the DPR.
