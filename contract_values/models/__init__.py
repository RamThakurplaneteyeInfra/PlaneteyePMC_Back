# Export ContractValue so Django's app registry can discover it
# and it can be imported as: from contract_values.models import ContractValue
from .contract_value import ContractValue

__all__ = ["ContractValue"]
