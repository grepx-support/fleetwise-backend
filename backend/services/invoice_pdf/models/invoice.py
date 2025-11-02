"""
Invoice model
"""

from datetime import date as Date
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from pydantic import EmailStr, constr

from .invoice_item import InvoiceItem


class Invoice(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    logo_path: Optional[str] = None
    number: str = Field(min_length=1)
    date: Date = Field(default_factory=Date.today)
    due_date: Optional[Date] = None
    
    from_company: str
    from_email: EmailStr
    from_mobile: constr(pattern=r'^\+?[0-9\s\-]{7,15}$')
    to_company: str
    to_address: str
    
    items: List[InvoiceItem] = Field(min_length=1)
    notes: Optional[str] = None
    currency: str = Field(default="USD")
    sub_total: Decimal
    gst_amount: Decimal
    cash_collect_total: Decimal = Field(ge=0, decimal_places=2)
    total_amount: Decimal = Field(gt=0, decimal_places=2)

    email: EmailStr
    company_address: str 
    contact_number: constr(pattern=r'^\+?[0-9\s\-]{7,15}$')
    
    payment_info: str
    qr_code: str

    @property
    def total(self) -> Decimal:
        if any(item.cash_collect > 0 for item in self.items):
           return self.total_amount - self.cash_collect_total
        return self.total_amount - self.cash_collect_total

    