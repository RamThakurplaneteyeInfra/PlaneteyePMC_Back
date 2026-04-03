# Weekly Progress Report (WPR) API

This API aggregates Daily Progress Report (DPR) data into weekly reports for better project management and tracking.

## Overview

The WPR API processes existing DPR data and groups it by weeks within a specified month/year. It provides comprehensive weekly summaries including activity progress, deliverables, issues, and status tracking.

## API Endpoint

```
GET /api/dpr/wpr/
```

## Query Parameters

### Required Parameters
- `project_name` (string): Filter by project name (case-insensitive) - Required

### Optional Parameters (for specific period)
- `month` (integer, 1-12): Month for the report - Optional, if not provided returns latest available
- `year` (integer, 2000-2100): Year for the report - Optional, if not provided returns latest available
- `week` (integer, 1-5): Specific week number to retrieve - Optional

**Note**: If `month` and `year` are not provided, the API automatically returns the latest available weekly report for the specified project.

## Example Usage

### Get latest weekly report for White Bliss project (auto-selects latest month/year)
```
GET /api/dpr/wpr/?project_name=White%20Bliss
```

### Get all weeks for January 2024 for Highway project
```
GET /api/dpr/wpr/?month=1&year=2024&project_name=Highway
```

### Get Week 2 for January 2024 for White Bliss project
```
GET /api/dpr/wpr/?month=1&year=2024&week=2&project_name=White%20Bliss
```

## Response Format

```json
{
  "project_name": "White Bliss",
  "period": {
    "month": 3,
    "year": 2026,
    "auto_selected": true
  },
  "project_summary": {
    "total_weeks": 3,
    "overall_completion": 65.5,
    "status": "In Progress"
  },
  "weeks": [
    {
      "week": "Week 1",
      "start_date": "2026-03-01",
      "end_date": "2026-03-07",
      "activities": [
        {
          "activity": "Foundation excavation",
          "deliverable": "Excavated area",
          "max_progress": 85.5,
          "status": "In Progress",
          "start_date": "2026-03-01",
          "end_date": "2026-03-05",
          "completion_date": null,
          "days_taken": 5
        }
      ],
      "summary": {
        "total_activities": 5,
        "completed": 2,
        "in_progress": 2,
        "pending": 1,
        "completion_rate": 40.0,
        "overall_progress": 65.5,
        "performance": "Good"
      },
      "deliverables": ["Excavated area", "Concrete foundation"],
      "pending_work": [
        {
          "activity": "Foundation excavation",
          "deliverable": "Excavated area",
          "progress": 85.5,
          "last_updated": "2026-03-05",
          "next_plan": "Complete remaining excavation work"
        }
      ],
      "issues": {
        "total": 2,
        "unresolved": ["Weather delays", "Material shortage"]
      },
      "remarks": ["Progress on track despite weather"],
      "quality_status": "OK",
      "incidents": ["Minor equipment breakdown"],
      "billing_status": "Submitted",
      "drawing_status": "Approved"
    }
  ]
}
```

## Key Improvements

### 1. **Enhanced Deliverables Logic**
- Only includes deliverables from completed activities
- Removes duplicates and meaningless entries like "Done"

### 2. **Structured Pending Work**
- Includes only tasks where status != "Completed"
- Takes only the latest DPR entry for each task
- Returns structured format with progress, last_updated, and next_plan

### 3. **Improved Issues Structure**
- Replaces simple list with structured object
- Includes total count and unresolved issues list
- Filters out "None" values

### 4. **Enhanced Summary Metrics**
- Added `overall_progress`: Average of max_progress of all activities
- Added `performance` label: "Excellent" (>80%), "Good" (50-80%), "Poor" (<50%)

### 5. **Fixed Week Date Ranges**
- Uses fixed calendar weeks:
  - Week 1 → 1–7
  - Week 2 → 8–14
  - Week 3 → 15–21
  - Week 4 → 22–28
  - Week 5 → 29–31

### 6. **Activity Duration**
- Added `days_taken` field to each activity
- Calculates difference between start_date and end_date (inclusive)

### 7. **Project-Level Summary**
- Added `project_summary` at top level
- Includes `total_weeks`, `overall_completion`, and `status`
- Status is "Completed" if all weeks completed, otherwise "In Progress"

### 8. **Code Quality Improvements**
- Refactored into clean, modular helper functions
- Optimized queryset usage to avoid multiple loops
- Enhanced performance and maintainability

## Core Logic

### Week Calculation
Weeks are calculated using: `week = ceil(day_of_month / 7)`

### Task Identification
Tasks are uniquely identified using: `activity + "_" + deliverables` (lowercase + trim normalization)

### Progress Tracking
- **Maximum target_achieved** per task is tracked
- **Status determination**:
  - 100% → Completed
  - > 0% → In Progress  
  - 0% → Pending

### Date Tracking
- **start_date**: First occurrence of the task
- **end_date**: Last occurrence of the task
- **completion_date**: When progress reaches 100%

### Weekly Aggregations
- **Activities List**: All tasks with their progress and status
- **Summary**: Total activities, completion counts, and completion rate
- **Deliverables**: Unique list of all deliverables for the week
- **Pending Work**: Next day plans for incomplete tasks
- **Issues**: Combined unresolved issues from DPRs
- **Remarks**: Important remarks from activities
- **Quality Status**: "OK" if all entries are OK, otherwise "Not OK"
- **Incidents**: Combined incidents from DPRs
- **Billing Status**: Latest billing status of the week
- **Drawing Status**: Latest drawing/GFC status of the week

## Implementation Files

### Core Files
- `wpr_helpers.py`: Helper functions for week calculation and data aggregation
- `wpr_views.py`: Main API view class
- `wpr_serializers.py`: Response serializers
- `urls.py`: Updated URL routing

### Key Functions

#### wpr_helpers.py
- `get_week_number()`: Calculate week from day of month
- `get_week_range()`: Get start/end dates for a week
- `normalize_task_identifier()`: Create unique task IDs
- `get_task_status()`: Determine task status from progress
- `aggregate_dpr_activities_by_week()`: Main aggregation function

#### wpr_views.py
- `WeeklyProgressReportAPIView`: Main API endpoint with filtering and validation

## Performance Optimizations

- Uses `select_related('dpr')` to avoid N+1 queries
- Efficient database filtering with queryset methods
- Optimized date range queries
- Minimal data processing in Python

## Error Handling

- Parameter validation with detailed error messages
- 404 responses when no data found
- 500 error handling for aggregation failures
- Comprehensive input sanitization

## Integration Notes

The WPR API works with the existing DPR model structure:
- Uses `DailyProgressReport` and `DPRActivity` models
- Respects existing approval workflow status
- Compatible with current project structure

## Testing

Example test cases to consider:
1. Valid month/year with multiple weeks of data
2. Specific week retrieval
3. Project name filtering
4. Invalid parameter handling
5. No data scenarios
6. Edge cases (February, month boundaries)
