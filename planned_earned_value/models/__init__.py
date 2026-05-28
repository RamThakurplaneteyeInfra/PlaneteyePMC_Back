# Export PlannedEarnedValue so Django's app registry discovers it
# and it can be imported as: from planned_earned_value.models import PlannedEarnedValue
from .planned_earned_value import PlannedEarnedValue

__all__ = ["PlannedEarnedValue"]
