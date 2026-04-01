from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from projects.models import Project, Site, ProjectDashboardData
from cost_performance.models import ProjectCostPerformance
from health_safety.models import HealthSafetyReport
from operations.models import DailyProgressReport
from project_progress.models import ProjectProgressStatus
from cashflow.models import CashFlow
from budget_performance.models import BudgetCostPerformance
from equipment.models import ProjectEquipment
from datetime import date, timedelta
from decimal import Decimal

class Command(BaseCommand):
    help = 'Insert test data for White Bliss project'

    def handle(self, *args, **options):
        self.stdout.write('Inserting test data for White Bliss project...')
        
        # Get or create a test user for assignments
        test_user, created = User.objects.get_or_create(
            username='test_admin',
            defaults={
                'email': 'test@example.com',
                'first_name': 'Test',
                'last_name': 'Admin',
                'is_staff': True,
                'is_superuser': True
            }
        )
        if created:
            test_user.set_password('testpass123')
            test_user.save()
            self.stdout.write(self.style.SUCCESS('Created test user: test_admin'))
        
        # Create White Bliss project
        project, created = Project.objects.get_or_create(
            name='White Bliss',
            defaults={
                'client_name': 'White Bliss Corporation',
                'description': 'White Bliss is a premium residential and commercial development project featuring modern architecture and sustainable design.',
                'location': 'Mumbai, Maharashtra, India',
                'commencement_date': date(2024, 1, 15),
                'duration': '24 months',
                'budget': Decimal('500000000.00'),
                'salient_features': 'Premium residential towers, commercial spaces, green areas, modern amenities, sustainable design',
                'site_staff_details': 'Project Manager: John Doe, Site Engineers: 5, Safety Officers: 2, Quality Control: 3',
                'has_documentation': True,
                'has_iso_checklist': True,
                'has_test_frequency_chart': True,
                'status': 'active',
                'start_date': date(2024, 1, 15),
                'end_date': date(2026, 1, 15),
                'project_start': date(2024, 1, 15),
                'contract_finish': date(2026, 1, 15),
                'forecast_finish': date(2026, 3, 15),
                'original_contract_value': Decimal('450000000.00'),
                'approved_vo': Decimal('25000000.00'),
                'pending_vo': Decimal('15000000.00'),
                'bac': Decimal('480000000.00'),
                'working_hours_per_day': 8.0,
                'working_days_per_month': 26,
                'pmc_head': test_user,
                'team_lead': test_user,
                'billing_site_engineer': test_user,
                'qaqc_site_engineer': test_user,
                'created_by': test_user,
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS('Created White Bliss project'))
        else:
            self.stdout.write(self.style.WARNING('White Bliss project already exists'))
        
        # Create sites for White Bliss project
        sites_data = [
            {'name': 'Tower A - Residential', 'location': 'North Wing', 'status': 'active'},
            {'name': 'Tower B - Residential', 'location': 'South Wing', 'status': 'active'},
            {'name': 'Commercial Block', 'location': 'East Wing', 'status': 'active'},
            {'name': 'Clubhouse & Amenities', 'location': 'Central Area', 'status': 'not_started'},
        ]
        
        for site_data in sites_data:
            site, created = Site.objects.get_or_create(
                project=project,
                name=site_data['name'],
                defaults={
                    'location': site_data['location'],
                    'status': site_data['status'],
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created site: {site.name}'))
        
        # Create dashboard data for White Bliss project
        dashboard_data, created = ProjectDashboardData.objects.get_or_create(
            project=project,
            defaults={
                # Financial Metrics
                'planned_value': Decimal('320000000.00'),
                'earned_value': Decimal('310000000.00'),
                'bcwp': Decimal('310000000.00'),
                'ac': Decimal('295000000.00'),
                'actual_billed': Decimal('300000000.00'),
                
                # Contract Values
                'original_contract_value': Decimal('450000000.00'),
                'approved_vo': Decimal('25000000.00'),
                'revised_contract_value': Decimal('475000000.00'),
                'pending_vo': Decimal('15000000.00'),
                
                # Invoicing
                'gross_billed': Decimal('320000000.00'),
                'net_billed': Decimal('310000000.00'),
                'net_collected': Decimal('295000000.00'),
                'net_due': Decimal('15000000.00'),
                
                # Project Dates
                'project_start_date': date(2024, 1, 15),
                'contract_finish_date': date(2026, 1, 15),
                'forecast_finish_date': date(2026, 3, 15),
                'delay_days': 59,
                
                # Safety Metrics
                'fatalities': 0,
                'significant': 1,
                'major': 3,
                'minor': 12,
                'near_miss': 25,
                'total_manhours': 1250000,
                'loss_of_manhours': 4500,
                
                # Additional Data
                'additional_data': {
                    'project_phase': 'Construction',
                    'completion_percentage': 65.5,
                    'quality_score': 92.5,
                    'safety_score': 95.0,
                    'environmental_compliance': 'Compliant',
                    'key_milestones': [
                        {'name': 'Foundation Complete', 'date': '2024-06-15', 'status': 'Completed'},
                        {'name': 'Structure Complete', 'date': '2025-03-15', 'status': 'In Progress'},
                        {'name': 'MEP Installation', 'date': '2025-09-15', 'status': 'Pending'},
                        {'name': 'Finishing Works', 'date': '2025-12-15', 'status': 'Pending'},
                        {'name': 'Handover', 'date': '2026-01-15', 'status': 'Pending'},
                    ],
                    'team_size': {
                        'engineers': 15,
                        'technicians': 45,
                        'laborers': 120,
                        'safety_staff': 5,
                        'quality_staff': 4,
                    },
                    'equipment_on_site': {
                        'tower_cranes': 3,
                        'excavators': 2,
                        'concrete_mixers': 4,
                        'loaders': 3,
                        'trucks': 8,
                    }
                }
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS('Created dashboard data for White Bliss project'))
        else:
            self.stdout.write(self.style.WARNING('Dashboard data for White Bliss project already exists'))
        
        # Insert Cost Performance data for White Bliss
        cost_performance_data = [
            {'month_year': '2024-01', 'bcws': 15000000, 'bcwp': 14500000, 'acwp': 14000000, 'fcst': 460000000, 'bac': 480000000},
            {'month_year': '2024-02', 'bcws': 30000000, 'bcwp': 29000000, 'acwp': 28000000, 'fcst': 450000000, 'bac': 480000000},
            {'month_year': '2024-03', 'bcws': 50000000, 'bcwp': 48000000, 'acwp': 46000000, 'fcst': 440000000, 'bac': 480000000},
            {'month_year': '2024-04', 'bcws': 75000000, 'bcwp': 72000000, 'acwp': 69000000, 'fcst': 430000000, 'bac': 480000000},
            {'month_year': '2024-05', 'bcws': 100000000, 'bcwp': 96000000, 'acwp': 92000000, 'fcst': 420000000, 'bac': 480000000},
            {'month_year': '2024-06', 'bcws': 130000000, 'bcwp': 125000000, 'acwp': 120000000, 'fcst': 410000000, 'bac': 480000000},
            {'month_year': '2024-07', 'bcws': 160000000, 'bcwp': 155000000, 'acwp': 148000000, 'fcst': 400000000, 'bac': 480000000},
            {'month_year': '2024-08', 'bcws': 195000000, 'bcwp': 188000000, 'acwp': 180000000, 'fcst': 390000000, 'bac': 480000000},
            {'month_year': '2024-09', 'bcws': 230000000, 'bcwp': 222000000, 'acwp': 212000000, 'fcst': 380000000, 'bac': 480000000},
            {'month_year': '2024-10', 'bcws': 265000000, 'bcwp': 256000000, 'acwp': 245000000, 'fcst': 370000000, 'bac': 480000000},
            {'month_year': '2024-11', 'bcws': 295000000, 'bcwp': 285000000, 'acwp': 273000000, 'fcst': 360000000, 'bac': 480000000},
            {'month_year': '2024-12', 'bcws': 320000000, 'bcwp': 310000000, 'acwp': 295000000, 'fcst': 350000000, 'bac': 480000000},
        ]
        
        for cp_data in cost_performance_data:
            cp, created = ProjectCostPerformance.objects.get_or_create(
                project_name='White Bliss',
                month_year=cp_data['month_year'],
                defaults=cp_data
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created cost performance data for {cp.month_year}'))
        
        # Insert Health & Safety data for White Bliss
        safety_data = [
            {'report_date': date(2024, 1, 31), 'total_manhours': 25000, 'fatalities': 0, 'significant': 0, 'major': 0, 'minor': 1, 'near_miss': 2},
            {'report_date': date(2024, 2, 29), 'total_manhours': 50000, 'fatalities': 0, 'significant': 0, 'major': 0, 'minor': 2, 'near_miss': 3},
            {'report_date': date(2024, 3, 31), 'total_manhours': 80000, 'fatalities': 0, 'significant': 0, 'major': 1, 'minor': 2, 'near_miss': 4},
            {'report_date': date(2024, 4, 30), 'total_manhours': 115000, 'fatalities': 0, 'significant': 0, 'major': 1, 'minor': 3, 'near_miss': 5},
            {'report_date': date(2024, 5, 31), 'total_manhours': 155000, 'fatalities': 0, 'significant': 0, 'major': 1, 'minor': 4, 'near_miss': 6},
            {'report_date': date(2024, 6, 30), 'total_manhours': 200000, 'fatalities': 0, 'significant': 0, 'major': 1, 'minor': 5, 'near_miss': 7},
            {'report_date': date(2024, 7, 31), 'total_manhours': 250000, 'fatalities': 0, 'significant': 0, 'major': 2, 'minor': 6, 'near_miss': 8},
            {'report_date': date(2024, 8, 31), 'total_manhours': 305000, 'fatalities': 0, 'significant': 0, 'major': 2, 'minor': 7, 'near_miss': 9},
            {'report_date': date(2024, 9, 30), 'total_manhours': 365000, 'fatalities': 0, 'significant': 1, 'major': 2, 'minor': 8, 'near_miss': 10},
            {'report_date': date(2024, 10, 31), 'total_manhours': 430000, 'fatalities': 0, 'significant': 1, 'major': 2, 'minor': 9, 'near_miss': 11},
            {'report_date': date(2024, 11, 30), 'total_manhours': 500000, 'fatalities': 0, 'significant': 1, 'major': 3, 'minor': 10, 'near_miss': 12},
            {'report_date': date(2024, 12, 31), 'total_manhours': 580000, 'fatalities': 0, 'significant': 1, 'major': 3, 'minor': 12, 'near_miss': 25},
        ]
        
        for safety in safety_data:
            hs, created = HealthSafetyReport.objects.get_or_create(
                project_name='White Bliss',
                report_date=safety['report_date'],
                defaults=safety
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created safety report for {hs.report_date}'))
        
        # Insert Daily Progress Reports for White Bliss
        dpr_data = [
            {'report_date': date(2024, 12, 1), 'work_done': 'Foundation work completed for Tower A. Started excavation for Tower B.', 'manpower_count': 85, 'labor_log': {'skilled': 35, 'unskilled': 50}, 'machinery_log': [{'name': 'Excavator', 'count': 2}, {'name': 'Concrete Mixer', 'count': 3}], 'activity_progress': [{'activity': 'Foundation', 'progress': 100}, {'activity': 'Excavation', 'progress': 60}], 'critical_issues': 'None', 'billing_status': 'Approved'},
            {'report_date': date(2024, 12, 2), 'work_done': 'Continued excavation for Tower B. Started reinforcement work for Tower A.', 'manpower_count': 90, 'labor_log': {'skilled': 40, 'unskilled': 50}, 'machinery_log': [{'name': 'Excavator', 'count': 2}, {'name': 'Crane', 'count': 1}], 'activity_progress': [{'activity': 'Excavation', 'progress': 75}, {'activity': 'Reinforcement', 'progress': 20}], 'critical_issues': 'Minor delay due to weather', 'billing_status': 'Approved'},
            {'report_date': date(2024, 12, 3), 'work_done': 'Completed excavation for Tower B. Continued reinforcement for Tower A.', 'manpower_count': 95, 'labor_log': {'skilled': 45, 'unskilled': 50}, 'machinery_log': [{'name': 'Crane', 'count': 2}, {'name': 'Concrete Mixer', 'count': 2}], 'activity_progress': [{'activity': 'Excavation', 'progress': 100}, {'activity': 'Reinforcement', 'progress': 40}], 'critical_issues': 'None', 'billing_status': 'Pending'},
        ]
        
        for dpr in dpr_data:
            dpr_obj, created = DailyProgressReport.objects.get_or_create(
                project=project,
                report_date=dpr['report_date'],
                defaults={
                    'submitted_by': test_user,
                    'site': project.sites.first(),
                    'work_done': dpr['work_done'],
                    'manpower_count': dpr['manpower_count'],
                    'labor_log': dpr['labor_log'],
                    'machinery_log': dpr['machinery_log'],
                    'activity_progress': dpr['activity_progress'],
                    'critical_issues': dpr['critical_issues'],
                    'billing_status': dpr['billing_status'],
                    'status': 'APPROVED',
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created DPR for {dpr_obj.report_date}'))
        
        # Insert Project Progress Status data for White Bliss
        progress_data = [
            {'progress_month': date(2024, 1, 1), 'monthly_plan': 2.5, 'cumulative_plan': 2.5, 'monthly_actual': 2.3, 'cumulative_actual': 2.3},
            {'progress_month': date(2024, 2, 1), 'monthly_plan': 3.0, 'cumulative_plan': 5.5, 'monthly_actual': 2.8, 'cumulative_actual': 5.1},
            {'progress_month': date(2024, 3, 1), 'monthly_plan': 4.0, 'cumulative_plan': 9.5, 'monthly_actual': 3.7, 'cumulative_actual': 8.8},
            {'progress_month': date(2024, 4, 1), 'monthly_plan': 5.0, 'cumulative_plan': 14.5, 'monthly_actual': 4.6, 'cumulative_actual': 13.4},
            {'progress_month': date(2024, 5, 1), 'monthly_plan': 6.0, 'cumulative_plan': 20.5, 'monthly_actual': 5.5, 'cumulative_actual': 18.9},
            {'progress_month': date(2024, 6, 1), 'monthly_plan': 7.0, 'cumulative_plan': 27.5, 'monthly_actual': 6.4, 'cumulative_actual': 25.3},
            {'progress_month': date(2024, 7, 1), 'monthly_plan': 8.0, 'cumulative_plan': 35.5, 'monthly_actual': 7.2, 'cumulative_actual': 32.5},
            {'progress_month': date(2024, 8, 1), 'monthly_plan': 9.0, 'cumulative_plan': 44.5, 'monthly_actual': 8.1, 'cumulative_actual': 40.6},
            {'progress_month': date(2024, 9, 1), 'monthly_plan': 10.0, 'cumulative_plan': 54.5, 'monthly_actual': 9.0, 'cumulative_actual': 49.6},
            {'progress_month': date(2024, 10, 1), 'monthly_plan': 11.0, 'cumulative_plan': 65.5, 'monthly_actual': 9.8, 'cumulative_actual': 59.4},
            {'progress_month': date(2024, 11, 1), 'monthly_plan': 12.0, 'cumulative_plan': 77.5, 'monthly_actual': 10.5, 'cumulative_actual': 69.9},
            {'progress_month': date(2024, 12, 1), 'monthly_plan': 12.5, 'cumulative_plan': 90.0, 'monthly_actual': 11.2, 'cumulative_actual': 81.1},
        ]
        
        for progress in progress_data:
            prog, created = ProjectProgressStatus.objects.get_or_create(
                project_name='White Bliss',
                progress_month=progress['progress_month'],
                defaults={
                    'monthly_plan': progress['monthly_plan'],
                    'cumulative_plan': progress['cumulative_plan'],
                    'monthly_actual': progress['monthly_actual'],
                    'cumulative_actual': progress['cumulative_actual'],
                    'created_by': 'test_admin',
                    'updated_by': 'test_admin',
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created progress status for {prog.progress_month.strftime("%b-%y")}'))
        
        # Insert Cash Flow data for White Bliss
        cashflow_data = [
            {'month_year': 'Jan-2024', 'cash_in_monthly_plan': 15000000, 'cash_in_monthly_actual': 14500000, 'cash_out_monthly_plan': 12000000, 'cash_out_monthly_actual': 11500000, 'actual_cost_monthly': 11000000},
            {'month_year': 'Feb-2024', 'cash_in_monthly_plan': 18000000, 'cash_in_monthly_actual': 17500000, 'cash_out_monthly_plan': 14000000, 'cash_out_monthly_actual': 13500000, 'actual_cost_monthly': 13000000},
            {'month_year': 'Mar-2024', 'cash_in_monthly_plan': 22000000, 'cash_in_monthly_actual': 21000000, 'cash_out_monthly_plan': 17000000, 'cash_out_monthly_actual': 16500000, 'actual_cost_monthly': 16000000},
            {'month_year': 'Apr-2024', 'cash_in_monthly_plan': 25000000, 'cash_in_monthly_actual': 24000000, 'cash_out_monthly_plan': 19000000, 'cash_out_monthly_actual': 18500000, 'actual_cost_monthly': 18000000},
            {'month_year': 'May-2024', 'cash_in_monthly_plan': 28000000, 'cash_in_monthly_actual': 27000000, 'cash_out_monthly_plan': 21000000, 'cash_out_monthly_actual': 20500000, 'actual_cost_monthly': 20000000},
            {'month_year': 'Jun-2024', 'cash_in_monthly_plan': 32000000, 'cash_in_monthly_actual': 31000000, 'cash_out_monthly_plan': 24000000, 'cash_out_monthly_actual': 23500000, 'actual_cost_monthly': 23000000},
            {'month_year': 'Jul-2024', 'cash_in_monthly_plan': 35000000, 'cash_in_monthly_actual': 34000000, 'cash_out_monthly_plan': 26000000, 'cash_out_monthly_actual': 25500000, 'actual_cost_monthly': 25000000},
            {'month_year': 'Aug-2024', 'cash_in_monthly_plan': 38000000, 'cash_in_monthly_actual': 37000000, 'cash_out_monthly_plan': 28000000, 'cash_out_monthly_actual': 27500000, 'actual_cost_monthly': 27000000},
            {'month_year': 'Sep-2024', 'cash_in_monthly_plan': 42000000, 'cash_in_monthly_actual': 41000000, 'cash_out_monthly_plan': 31000000, 'cash_out_monthly_actual': 30500000, 'actual_cost_monthly': 30000000},
            {'month_year': 'Oct-2024', 'cash_in_monthly_plan': 45000000, 'cash_in_monthly_actual': 44000000, 'cash_out_monthly_plan': 33000000, 'cash_out_monthly_actual': 32500000, 'actual_cost_monthly': 32000000},
            {'month_year': 'Nov-2024', 'cash_in_monthly_plan': 48000000, 'cash_in_monthly_actual': 47000000, 'cash_out_monthly_plan': 35000000, 'cash_out_monthly_actual': 34500000, 'actual_cost_monthly': 34000000},
            {'month_year': 'Dec-2024', 'cash_in_monthly_plan': 52000000, 'cash_in_monthly_actual': 51000000, 'cash_out_monthly_plan': 38000000, 'cash_out_monthly_actual': 37500000, 'actual_cost_monthly': 37000000},
        ]
        
        for cf_data in cashflow_data:
            cf, created = CashFlow.objects.get_or_create(
                project_name='White Bliss',
                month_year=cf_data['month_year'],
                defaults=cf_data
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created cash flow data for {cf.month_year}'))
        
        # Recalculate cash flow cumulatives
        CashFlow.recalculate_cumulatives('White Bliss')
        self.stdout.write(self.style.SUCCESS('Recalculated cash flow cumulatives'))
        
        # Insert Budget Cost Performance data for White Bliss
        bac = Decimal('480000000.00')
        bcwp = Decimal('310000000.00')
        acwp = Decimal('295000000.00')
        
        # Calculate derived EVM metrics
        cpi = (bcwp / acwp).quantize(Decimal('0.000001'))
        eac = (bac / cpi).quantize(Decimal('0.0001'))
        etg = (eac - acwp).quantize(Decimal('0.0001'))
        vac = (bac - eac).quantize(Decimal('0.0001'))
        cv = (bcwp - acwp).quantize(Decimal('0.0001'))
        
        bc, created = BudgetCostPerformance.objects.get_or_create(
            project_name='White Bliss',
            defaults={
                'bac': bac,
                'bcwp': bcwp,
                'acwp': acwp,
                'cpi': cpi,
                'eac': eac,
                'etg': etg,
                'vac': vac,
                'cv': cv,
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created budget cost performance data'))
        
        # Insert Project Equipment data for White Bliss
        equipment_data = [
            {'month': date(2024, 1, 1), 'planned_equipment': 5, 'actual_equipment': 4},
            {'month': date(2024, 2, 1), 'planned_equipment': 6, 'actual_equipment': 5},
            {'month': date(2024, 3, 1), 'planned_equipment': 8, 'actual_equipment': 7},
            {'month': date(2024, 4, 1), 'planned_equipment': 10, 'actual_equipment': 9},
            {'month': date(2024, 5, 1), 'planned_equipment': 12, 'actual_equipment': 11},
            {'month': date(2024, 6, 1), 'planned_equipment': 15, 'actual_equipment': 14},
            {'month': date(2024, 7, 1), 'planned_equipment': 18, 'actual_equipment': 17},
            {'month': date(2024, 8, 1), 'planned_equipment': 20, 'actual_equipment': 19},
            {'month': date(2024, 9, 1), 'planned_equipment': 22, 'actual_equipment': 21},
            {'month': date(2024, 10, 1), 'planned_equipment': 25, 'actual_equipment': 24},
            {'month': date(2024, 11, 1), 'planned_equipment': 28, 'actual_equipment': 27},
            {'month': date(2024, 12, 1), 'planned_equipment': 30, 'actual_equipment': 29},
        ]
        
        for eq_data in equipment_data:
            eq, created = ProjectEquipment.objects.get_or_create(
                project_name='White Bliss',
                month=eq_data['month'],
                defaults=eq_data
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created equipment data for {eq.month.strftime("%b-%Y")}'))
        
        # Recalculate equipment cumulatives
        ProjectEquipment.recalculate_cumulatives('White Bliss')
        self.stdout.write(self.style.SUCCESS('Recalculated equipment cumulatives'))
        
        # Assign test user to the project
        project.site_engineers.add(test_user)
        project.coordinators.add(test_user)
        project.assigned_users.add(test_user)
        
        self.stdout.write(self.style.SUCCESS('\n' + '='*60))
        self.stdout.write(self.style.SUCCESS('White Bliss test data insertion completed successfully!'))
        self.stdout.write(self.style.SUCCESS('='*60))
        self.stdout.write(self.style.SUCCESS(f'Project: {project.name}'))
        self.stdout.write(self.style.SUCCESS(f'Client: {project.client_name}'))
        self.stdout.write(self.style.SUCCESS(f'Location: {project.location}'))
        self.stdout.write(self.style.SUCCESS(f'Budget: {project.budget}'))
        self.stdout.write(self.style.SUCCESS(f'Status: {project.status}'))
        self.stdout.write(self.style.SUCCESS(f'Sites: {project.sites.count()}'))
        self.stdout.write(self.style.SUCCESS('='*60))
