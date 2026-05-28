# Export Correspondence model so Django's app registry can discover it
# and so it can be imported as: from correspondence.models import Correspondence
from .correspondence import Correspondence

__all__ = ["Correspondence"]
