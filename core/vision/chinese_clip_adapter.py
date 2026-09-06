"""Optional Chinese-CLIP semantic image-to-item ranking adapter.

The adapter is intentionally lazy: importing this module does not import or
download PyTorch/Transformers.  A model is only loaded when ``rank`` is called.
Results are advisory candidates for human review and are never persisted as
financial relations automatically.
"""

from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class SemanticVisualCandidate:
    item_key: str
    label: str
    probability: float
    logit: float

    def to_dict(self) -> dict:
        return asdict(self)


class ChineseClipAdapter:
    DEFAULT_MODEL = "OFA-Sys/chinese-clip-vit-base-patch16"

    def __init__(self, model_id: str | None = None, device: str | None = None) -> None:
        self.model_id = model_id or self.DEFAULT_MODEL
        self.device = device
        self._torch = None
        self._model = None
        self._processor = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import ChineseCLIPModel, ChineseCLIPProcessor
        except ImportError as exc:
            raise RuntimeError(
                "Chinese-CLIP is optional. Install the vision dependencies before generating semantic suggestions."
            ) from exc

        selected_device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._torch = torch
        self._processor = ChineseCLIPProcessor.from_pretrained(self.model_id)
        self._model = ChineseCLIPModel.from_pretrained(self.model_id).to(selected_device)
        self._model.eval()
        self.device = selected_device

    @staticmethod
    def _prompt(label: str) -> str:
        return f"一张{label}的实物照片"

    def rank(
        self,
        photo_file: str | Path,
        candidates: list[tuple[str, str]],
        top_k: int = 3,
    ) -> list[SemanticVisualCandidate]:
        if not candidates:
            return []
        self._load()
        torch = self._torch
        assert torch is not None and self._processor is not None and self._model is not None

        with Image.open(photo_file) as image:
            rgb = image.convert("RGB")
            texts = [self._prompt(label) for _, label in candidates]
            inputs = self._processor(
                text=texts,
                images=rgb,
                return_tensors="pt",
                padding=True,
            )

        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with torch.no_grad():
            output = self._model(**inputs)
            logits = output.logits_per_image[0]
            probabilities = torch.softmax(logits, dim=-1)

        rows = []
        for index, (item_key, label) in enumerate(candidates):
            rows.append(
                SemanticVisualCandidate(
                    item_key=item_key,
                    label=label,
                    probability=float(probabilities[index].detach().cpu()),
                    logit=float(logits[index].detach().cpu()),
                )
            )
        rows.sort(key=lambda row: row.probability, reverse=True)
        return rows[: max(1, top_k)]

