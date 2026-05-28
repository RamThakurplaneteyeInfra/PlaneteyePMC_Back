# Export ContractPerformance so Django's app registry discovers it
# and it can be imported as: from contract_performance.models import ContractPerformance
from .contract_performance import ContractPerformance

__all__ = ["ContractPerformance"]
