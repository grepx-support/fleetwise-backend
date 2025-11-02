"""
Invoice item model
"""

from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict, constr
from datetime import date, time

class InvoiceItem(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    Date: date
    Time: time
    Job: str
    Particulars: str = Field(min_length=1, max_length=200)
    ServiceType: str = constr(strip_whitespace=True, min_length=1) 
    amount: Decimal = Field(gt=0, decimal_places=2)
    cash_collect: Decimal = Field(ge=0, decimal_places=2, default=Decimal("0.00"))


    @property
    def subtotal(self) -> Decimal:
        return self.amount
    
    @property
    def tax_amount(self) -> Decimal:
        return self.amount * 0

    
    @property
    def total(self) -> Decimal:
        return self.subtotal + self.tax_amount 
