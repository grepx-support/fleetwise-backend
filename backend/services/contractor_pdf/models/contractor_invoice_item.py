from pydantic import BaseModel, Field
from datetime import date as Date

class ContractorInvoiceItem(BaseModel):
    job_date: Date
    job_id: str
    driver_name: str
    job_cost: float
    cash_to_collect: float = Field(default=0.0)

    @property
    def final_cost(self) -> float:
        return self.job_cost - self.cash_to_collect if self.cash_to_collect > 0 else self.job_cost
