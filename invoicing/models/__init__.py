# Export InvoicingInformation so Django's app registry discovers it
# and it can be imported as: from invoicing.models import InvoicingInformation
from .invoicing_information import InvoicingInformation

__all__ = ["InvoicingInformation"]
