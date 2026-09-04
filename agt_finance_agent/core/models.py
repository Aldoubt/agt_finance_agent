from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Document:
    path: str
    document_type: str = "unknown"
    confidence: float = 0.0


@dataclass
class Invoice:
    file: str
    invoice_no: Optional[str] = None
    supplier: Optional[str] = None
    amount: float = 0.0
    items: List[str] = field(default_factory=list)


@dataclass
class PurchaseItem:
    name: str
    amount: float = 0.0
    invoice_files: List[str] = field(default_factory=list)
    photo_files: List[str] = field(default_factory=list)
    purchase_proofs: List[str] = field(default_factory=list)
    payment_proofs: List[str] = field(default_factory=list)


@dataclass
class PurchaseOrder:
    order_id: str
    amount: float = 0.0
    items: List[PurchaseItem] = field(default_factory=list)
