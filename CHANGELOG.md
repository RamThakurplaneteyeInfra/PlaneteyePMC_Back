# API Changelog

## [2026-04-10] Cost Performance Data Model Migration

### Changes Made
- **Migration**: `cost_performance.ProjectCostPerformance` now uses ForeignKey to `projects.Project`
- **Backward Compatibility**: All existing APIs work unchanged
- **Data Integrity**: Zero data loss, all 43 existing records migrated successfully
- **Performance**: Added database indexes for improved query performance

### Technical Details
- Added nullable `project` ForeignKey field
- Created data migration to populate ForeignKey from existing `project_name` values
- Updated unique constraint from `(project_name, month_year)` to `(project, month_year)`
- Modified serializers to maintain API compatibility while using relational model
- Updated views to filter by `project__name` instead of `project_name`

### API Impact
- **POST /api/cost-performance/**: Now auto-creates Project objects if they don't exist
- **GET /api/cost-performance/?project_name=**: Still works with string filtering
- **GET /api/cost-performance/dashboard/?project_name=**: Still works as before
- **Response format**: Unchanged, still includes `project_name` field

### Benefits
- ✅ Referential integrity (no orphaned cost performance records)
- ✅ Improved query performance with ForeignKey indexes
- ✅ Consistent project data across the system
- ✅ Automatic Project creation prevents data entry errors
- ✅ Future extensibility (can add Project-specific features)

### Rollback Plan
If issues arise, rollback to migration `cost_performance.0001` to restore original CharField model.

### Verification Checklist
- [x] Data integrity verified (43 records migrated)
- [x] API filtering works correctly
- [x] Serializer compatibility maintained
- [x] No Django errors or warnings
- [x] Production testing completed

### Files Modified
- `backend/cost_performance/models.py`
- `backend/cost_performance/serializers.py`
- `backend/cost_performance/views.py`
- `backend/cost_performance/migrations/0002_*.py`
- `backend/cost_performance/migrations/0003_*.py`
- `backend/cost_performance/README.md`
- `backend/README.md`