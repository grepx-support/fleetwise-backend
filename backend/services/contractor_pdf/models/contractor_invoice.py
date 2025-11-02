from datetime import date as Date
from typing import List, Optional
from pydantic import BaseModel, Field
from .contractor_invoice_item import ContractorInvoiceItem
from decimal import Decimal

class ContractorInvoice(BaseModel):
    company_name: str
    entity_label: str
    contractor_name: str
    bill_no: str
    bill_date: Date
    cash_collect_total: Optional[float] = Field(default=None)
    total_amount: Optional[float] = Field(default=None)
    items: List[ContractorInvoiceItem]

    @property
    def cash_collect_total(self) -> float:
        return round(sum(item.cash_to_collect for item in self.items), 2)
    
    @property
    def total(self) -> float:
        return round(sum(i.final_cost for i in self.items), 2)
