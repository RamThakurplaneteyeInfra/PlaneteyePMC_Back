
# Health & Safety Module

## Overview

* Tracks safety incidents and manhours per project
* Used for safety analysis and reporting

## Fields

* project_name
* report_date
* total_manhours
* fatalities, significant, major, minor, near_miss

## Derived Metrics

* total_incidents = sum of all incident types

## Performance Optimizations

* Indexed fields for faster filtering
* DecimalField for accurate manhours
* Composite indexes for efficient queries

## Developer Notes

* Do NOT modify total_incidents logic
* Always ensure valid data input

## Best Practices

* Avoid duplicate daily reports
* Maintain consistent project_name formatting

# Health & Safety Serializer

## Overview

* Handles input and output of health & safety data
* Supports dashboard-ready responses

## Input Format

* totalManhours
* incidents (dictionary of counts)

## Incident Types

* fatalities
* significant
* major
* minor
* near_miss

## Output Fields

* totalIncidents
* breakdown
* pyramid
* insights
* alerts
* severityIndex

## Validation Rules

* totalManhours ≥ 0
* incidents ≥ 0
* required keys must be present

## Performance Optimizations

* Decimal precision for manhours
* Efficient validation logic
* Structured serializers

## Developer Notes

* Do NOT modify response structure
* Keep validation strict
* Ensure compatibility with frontend

## Best Practices

* Always send valid incident data
* Maintain consistent API usage

# Health & Safety Views

## Overview

* Handles safety analytics and report management

## APIs

* POST /health-safety/status/
* GET /health-safety/example/
* CRUD /health-safety/reports/

## Features

* Incident analysis
* Pyramid visualization
* Safety insights and alerts

## Performance Optimizations

* Cached responses
* Optimized queries
* Reduced DB load

## Developer Notes

* Do NOT modify calculation logic
* Always use serializers for validation
* Ensure cache invalidation

## Best Practices

* Validate inputs before processing
* Use caching for heavy APIs
* Maintain consistent API usage
