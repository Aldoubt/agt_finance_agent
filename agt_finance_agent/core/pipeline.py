from pathlib import Path


class FinanceAgent:
    """Main orchestration entry.

    Real processing modules will be injected here:
    scanner -> classifier -> parser -> relation graph -> exporters
    """

    def process(self, input_path: str):
        path = Path(input_path)
        if not path.exists():
            raise FileNotFoundError(input_path)

        return {
            "input": str(path),
            "status": "pipeline initialized",
            "next": [
                "document_scan",
                "classification",
                "invoice_parse",
                "multimodal_matching",
                "archive_generation",
            ],
        }
