from typing import Literal
from pydantic import BaseModel

BreakType = Literal["tea", "lunch", "evening"]

class StartBreakRequest(BaseModel):
    break_type: BreakType
