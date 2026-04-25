from dataclasses import dataclass

from app.schemas import DocumentType


@dataclass
class ScanError:
    code: str
    detected_type: DocumentType | None = None
