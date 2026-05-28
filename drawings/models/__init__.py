# Export Drawing model so Django's app registry can discover it
# and so it can be imported as: from drawings.models import Drawing
from .drawing import Drawing

__all__ = ["Drawing"]
