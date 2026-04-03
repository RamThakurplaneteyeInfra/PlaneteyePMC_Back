from datetime import datetime, date, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Optional, Tuple
from django.db.models import Max, Min, Q
from .models import DailyProgressReport, DPRActivity


def get_week_range(year: int, month: int, week: int) -> Tuple[date, date]:
    """
    Get fixed calendar week start and end dates.
    
    Args:
        year: Year
        month: Month (1-12)
        week: Week number (1-5)
        
    Returns:
        Tuple of (start_date, end_date)
    """
    # Fixed calendar weeks
    week_ranges = {
        1: (1, 7),
        2: (8, 14),
        3: (15, 21),
        4: (22, 28),
        5: (29, 31)
    }
    
    start_day, end_day = week_ranges.get(week, (1, 7))
    
    # Adjust for months with fewer days
    try:
        start_date = date(year, month, start_day)
        end_date = date(year, month, end_day)
    except ValueError:
        # Handle invalid dates (e.g., February 30)
        if month == 2:
            # February has 28 or 29 days
            if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
                max_days = 29
            else:
                max_days = 28
        else:
            # Other months with 30 days
            max_days = 30
        
        end_day = min(end_day, max_days)
        start_date = date(year, month, start_day)
        end_date = date(year, month, end_day)
    
    return start_date, end_date


def get_week_number(day: int) -> int:
    """
    Calculate week number from day of month.
    Week = ceil(day_of_month / 7)
    
    Args:
        day: Day of the month (1-31)
        
    Returns:
        Week number (1-5)
    """
    return (day - 1) // 7 + 1


def normalize_task_identifier(activity: str, deliverables: str) -> str:
    """
    Create unique task identifier from activity and deliverables.
    Format: activity + "_" + deliverables (lowercase + trim)
    
    Args:
        activity: Activity description
        deliverables: Deliverables description
        
    Returns:
        Normalized task identifier
    """
    activity_clean = activity.strip().lower()
    deliverables_clean = deliverables.strip().lower()
    
    return f"{activity_clean}_{deliverables_clean}"


def calculate_status(target_achieved: float) -> str:
    """
    Determine task status based on progress percentage.
    
    Args:
        target_achieved: Progress percentage (0-100)
        
    Returns:
        Status: 'Completed', 'In Progress', or 'Pending'
    """
    if target_achieved >= 100:
        return 'Completed'
    elif target_achieved > 0:
        return 'In Progress'
    else:
        return 'Pending'


def calculate_performance(overall_progress: float) -> str:
    """
    Calculate performance label based on overall progress.
    
    Args:
        overall_progress: Overall progress percentage (0-100)
        
    Returns:
        Performance label: 'Excellent', 'Good', or 'Poor'
    """
    if overall_progress > 80:
        return 'Excellent'
    elif overall_progress >= 50:
        return 'Good'
    else:
        return 'Poor'


def calculate_days_taken(start_date: date, end_date: date) -> int:
    """
    Calculate the number of days taken for an activity.
    
    Args:
        start_date: Start date of the activity
        end_date: End date of the activity
        
    Returns:
        Number of days taken (inclusive)
    """
    return (end_date - start_date).days + 1


def generate_deliverables(tasks: Dict[str, Any]) -> List[str]:
    """
    Generate meaningful deliverables from completed activities.
    
    Args:
        tasks: Dictionary of aggregated tasks
        
    Returns:
        List of meaningful deliverables from completed activities
    """
    deliverables_set = set()
    
    for task in tasks.values():
        if task['status'] == 'Completed':
            # Generate meaningful deliverable from activity and deliverable
            activity = task['activity'].strip()
            deliverable = task['deliverable'].strip()
            
            if deliverable and deliverable.lower() != 'done':
                deliverables_set.add(deliverable)
            elif activity:
                # Create meaningful deliverable from activity
                deliverables_set.add(f"{activity} completed")
    
    # Return list or default message if no completed deliverables
    return list(deliverables_set) if deliverables_set else ["No completed deliverables"]


def calculate_trend(current_progress: float, previous_progress: float) -> str:
    """
    Calculate weekly trend based on progress comparison.
    
    Args:
        current_progress: Current week's overall progress
        previous_progress: Previous week's overall progress
        
    Returns:
        Trend label: 'Improving', 'Declining', or 'Stable'
    """
    if current_progress > previous_progress:
        return 'Improving'
    elif current_progress < previous_progress:
        return 'Declining'
    else:
        return 'Stable'


def aggregate_tasks(activities: List[DPRActivity]) -> Dict[str, Any]:
    """
    Aggregate activities by tasks and calculate metrics.
    
    Args:
        activities: List of DPRActivity objects
        
    Returns:
        Dictionary containing aggregated task data
    """
    tasks = {}
    
    for activity in activities:
        task_id = normalize_task_identifier(activity.activity, activity.deliverables)
        
        # Initialize task if not exists
        if task_id not in tasks:
            tasks[task_id] = {
                'activity': activity.activity,
                'deliverable': activity.deliverables,
                'max_progress': 0,
                'status': 'Pending',
                'start_date': activity.date,
                'end_date': activity.date,
                'completion_date': None,
                'dates_seen': [activity.date],
                'latest_entry': activity
            }
        
        # Update task progress and dates
        task = tasks[task_id]
        task['max_progress'] = max(task['max_progress'], activity.target_achieved)
        task['status'] = calculate_status(task['max_progress'])
        task['start_date'] = min(task['start_date'], activity.date)
        task['end_date'] = max(task['end_date'], activity.date)
        task['dates_seen'].append(activity.date)
        
        # Keep the latest entry (by date)
        if activity.date >= task['latest_entry'].date:
            task['latest_entry'] = activity
        
        # Set completion date if task reached 100%
        if task['max_progress'] >= 100 and task['completion_date'] is None:
            task['completion_date'] = activity.date
    
    # Calculate duration for each task
    for task in tasks.values():
        task['days_taken'] = calculate_days_taken(task['start_date'], task['end_date'])
    
    # Generate deliverables from completed tasks
    deliverables = generate_deliverables(tasks)
    
    return {
        'tasks': tasks,
        'deliverables': deliverables
    }


def extract_pending_work(tasks: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract pending work from incomplete tasks.
    
    Args:
        tasks: Dictionary of aggregated tasks
        
    Returns:
        List of pending work items with structured format
    """
    pending_work = []
    
    for task_id, task in tasks.items():
        if task['status'] != 'Completed':
            latest_activity = task['latest_entry']
            pending_work.append({
                'activity': task['activity'],
                'deliverable': task['deliverable'],
                'progress': task['max_progress'],
                'last_updated': latest_activity.date.isoformat(),
                'next_plan': latest_activity.next_day_plan or ''
            })
    
    return pending_work


def extract_issues(dpr_queryset) -> Dict[str, Any]:
    """
    Extract and structure issues from DPR data.
    
    Args:
        dpr_queryset: DailyProgressReport queryset
        
    Returns:
        Dictionary with total issues count and unresolved issues list
    """
    unresolved_issues = []
    
    for dpr in dpr_queryset:
        if dpr.unresolved_issues and dpr.unresolved_issues.strip().lower() != 'none':
            unresolved_issues.append(dpr.unresolved_issues.strip())
    
    return {
        'total': len(unresolved_issues),
        'unresolved': unresolved_issues
    }


def calculate_week_summary(tasks: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate weekly summary statistics.
    
    Args:
        tasks: Dictionary of aggregated tasks
        
    Returns:
        Dictionary containing summary metrics
    """
    activities_list = list(tasks.values())
    total_activities = len(activities_list)
    
    if total_activities == 0:
        return {
            'total_activities': 0,
            'completed': 0,
            'in_progress': 0,
            'pending': 0,
            'completion_rate': 0,
            'overall_progress': 0,
            'total_work_done': 0,
            'performance': 'Poor',
            'status': 'Pending'
        }
    
    completed = sum(1 for task in activities_list if task['status'] == 'Completed')
    in_progress = sum(1 for task in activities_list if task['status'] == 'In Progress')
    pending = sum(1 for task in activities_list if task['status'] == 'Pending')
    
    completion_rate = (completed / total_activities) * 100
    overall_progress = sum(task['max_progress'] for task in activities_list) / total_activities
    total_work_done = sum(task['max_progress'] for task in activities_list)
    performance = calculate_performance(overall_progress)
    
    # Determine week-level status
    week_status = 'Completed' if completed == total_activities else 'In Progress'
    
    return {
        'total_activities': total_activities,
        'completed': completed,
        'in_progress': in_progress,
        'pending': pending,
        'completion_rate': round(completion_rate, 2),
        'overall_progress': round(overall_progress, 2),
        'total_work_done': round(total_work_done, 2),
        'performance': performance,
        'status': week_status
    }


def calculate_project_summary(weeks_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate project-level summary across all weeks.
    
    Args:
        weeks_data: List of week data dictionaries
        
    Returns:
        Dictionary containing project summary
    """
    total_weeks = len(weeks_data)
    
    if total_weeks == 0:
        return {
            'total_weeks': 0,
            'overall_completion': 0,
            'status': 'Pending'
        }
    
    # Use overall_progress instead of completion_rate
    overall_progress_values = [week['summary']['overall_progress'] for week in weeks_data]
    overall_completion = sum(overall_progress_values) / total_weeks
    
    # Determine project status
    all_completed = all(
        week['summary']['completed'] == week['summary']['total_activities'] 
        for week in weeks_data
    )
    project_status = 'Completed' if all_completed else 'In Progress'
    
    return {
        'total_weeks': total_weeks,
        'overall_completion': round(overall_completion, 2),
        'status': project_status
    }


def aggregate_dpr_activities_by_week(
    dpr_queryset, 
    year: int, 
    month: int, 
    week: Optional[int] = None
) -> Dict[str, Any]:
    """
    Aggregate DPR activities by week for the given month/year.
    
    Args:
        dpr_queryset: Filtered DailyProgressReport queryset
        year: Year for aggregation
        month: Month for aggregation
        week: Optional specific week to aggregate
        
    Returns:
        Dictionary containing weekly aggregated data
    """
    # Get all activities for the filtered DPRs
    activities = DPRActivity.objects.filter(
        dpr__in=dpr_queryset,
        date__year=year,
        date__month=month
    ).select_related('dpr').order_by('date')
    
    # Group activities by week
    weeks_data = {}
    
    # Process each activity
    for activity in activities:
        week_num = get_week_number(activity.date.day)
        
        # Skip if specific week requested and this doesn't match
        if week and week_num != week:
            continue
        
        week_key = f"Week {week_num}"
        
        if week_key not in weeks_data:
            # Initialize week data with fixed date range
            start_date, end_date = get_week_range(year, month, week_num)
            weeks_data[week_key] = {
                'week': week_key,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'activities': [],
                'remarks': set(),
                'quality_status': [],
                'incidents': set(),
                'billing_status': [],
                'drawing_status': [],
                'dprs_in_week': set()
            }
        
        # Add activity to week
        weeks_data[week_key]['dprs_in_week'].add(activity.dpr.id)
    
    # Process each week's data
    for week_key, week_data in weeks_data.items():
        # Get DPRs for this week
        week_dprs = dpr_queryset.filter(id__in=week_data['dprs_in_week'])
        
        # Get activities for this week
        week_activities = activities.filter(dpr__in=week_dprs)
        
        # Aggregate tasks
        task_data = aggregate_tasks(list(week_activities))
        
        # Calculate summary
        summary = calculate_week_summary(task_data['tasks'])
        
        # Extract pending work
        pending_work = extract_pending_work(task_data['tasks'])
        
        # Extract issues
        issues_data = extract_issues(week_dprs)
        
        # Collect other data
        remarks_set = set()
        quality_statuses = []
        incidents_set = set()
        billing_entries = []
        drawing_entries = []
        
        for activity in week_activities:
            # Remarks
            if activity.remarks:
                remarks_set.add(activity.remarks.strip())
            
            # DPR data
            dpr = activity.dpr
            
            # Quality status
            if dpr.quality_status:
                quality_statuses.append(dpr.quality_status.strip())
            
            # Incidents
            if dpr.next_day_incident:
                incidents_set.add(dpr.next_day_incident.strip())
            
            # Billing status
            if dpr.bill_status:
                billing_entries.append({
                    'status': dpr.bill_status.strip(),
                    'date': dpr.report_date
                })
            
            # Drawing status
            if dpr.gfc_status:
                drawing_entries.append({
                    'status': dpr.gfc_status.strip(),
                    'date': dpr.report_date
                })
        
        # Determine quality status for the week
        quality_statuses_lower = [status.lower() for status in quality_statuses if status]
        weekly_quality_status = "Not OK" if any(
            "not ok" in status or "issue" in status or "problem" in status 
            for status in quality_statuses_lower
        ) else "OK"
        
        # Get latest billing and drawing status
        latest_billing = max(billing_entries, key=lambda x: x['date']) if billing_entries else None
        latest_drawing = max(drawing_entries, key=lambda x: x['date']) if drawing_entries else None
        
        # Build week result
        week_result = {
            'week': week_key,
            'start_date': week_data['start_date'],
            'end_date': week_data['end_date'],
            'activities': list(task_data['tasks'].values()),
            'summary': summary,
            'deliverables': task_data['deliverables'],
            'pending_work': pending_work,
            'issues': issues_data,
            'remarks': list(remarks_set),
            'quality_status': weekly_quality_status,
            'incidents': list(incidents_set),
            'billing_status': latest_billing['status'] if latest_billing else None,
            'drawing_status': latest_drawing['status'] if latest_drawing else None,
            'status': summary['status']  # Add week-level status
        }
        
        weeks_data[week_key] = week_result
    
    # Convert to sorted list and calculate project summary
    weeks_list = sorted(
        weeks_data.values(), 
        key=lambda x: int(x['week'].split()[1])
    )
    
    # Calculate weekly trends
    for i, week in enumerate(weeks_list):
        if i == 0:
            # First week has no previous week to compare
            week['trend'] = 'Stable'
        else:
            current_progress = week['summary']['overall_progress']
            previous_progress = weeks_list[i-1]['summary']['overall_progress']
            week['trend'] = calculate_trend(current_progress, previous_progress)
    
    project_summary = calculate_project_summary(weeks_list)
    
    return {
        'weeks': weeks_list,
        'project_summary': project_summary
    }
