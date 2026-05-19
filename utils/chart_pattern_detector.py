import logging
import os
import tempfile
from typing import Any, Optional

logger = logging.getLogger("ChartPatternDetector")


class ChartPatternDetector:
    def __init__(self, model_name: str = "foduucom/stockmarket-pattern-detection-yolov8"):
        self.model_name = model_name
        self._model: Any = None
        self._supported_labels = [
            "Head and shoulders bottom", "Head and shoulders top",
            "M_Head", "StockLine", "Triangle", "W_Bottom",
        ]

    def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from ultralytics import YOLO
            self._model = YOLO(self.model_name)
            logger.info("YOLOv8 model loaded: %s", self.model_name)
        except ImportError:
            logger.warning("ultralytics not installed. Try: pip install ultralytics")
        except Exception as e:
            logger.warning("Failed to load YOLO model: %s", e)

    def detect_from_array(
        self,
        ohlcv: list[dict],
        conf_threshold: float = 0.5,
    ) -> list[dict]:
        if self._model is None:
            self._load_model()
        if self._model is None:
            return [{"error": "YOLO model not available"}]

        try:
            import mplfinance as mpf
            import pandas as pd

            df = pd.DataFrame(ohlcv)
            if not all(c in df.columns for c in ["Open", "High", "Low", "Close"]):
                df = df.rename(columns={
                    "open": "Open", "high": "High", "low": "Low", "close": "Close",
                    "volume": "Volume",
                })
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                chart_path = tmp.name

            mpf.plot(
                df.tail(180),
                type="candle",
                style="charles",
                savefig=dict(fname=chart_path, dpi=150, bbox_inches="tight"),
                volume=True,
                axisoff=True,
            )

            results = self._model(chart_path, conf=conf_threshold)
            os.unlink(chart_path)

            detections = []
            for r in results:
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    label = self._model.names.get(cls_id, f"class_{cls_id}")
                    conf = float(box.conf[0])
                    detections.append({
                        "label": label,
                        "confidence": round(conf, 4),
                        "bbox": box.xyxy[0].tolist() if hasattr(box, "xyxy") else [],
                    })
            return detections

        except ImportError as e:
            logger.warning("Missing dependency: %s", e)
            return [{"error": f"Missing dependency: {e}"}]
        except Exception as e:
            logger.warning("Chart detection error: %s", e)
            return [{"error": str(e)}]

    def detect_from_url(self, image_url: str, conf_threshold: float = 0.5) -> list[dict]:
        if self._model is None:
            self._load_model()
        if self._model is None:
            return [{"error": "YOLO model not available"}]
        try:
            results = self._model(image_url, conf=conf_threshold)
            detections = []
            for r in results:
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    label = self._model.names.get(cls_id, f"class_{cls_id}")
                    conf = float(box.conf[0])
                    detections.append({
                        "label": label,
                        "confidence": round(conf, 4),
                        "bbox": box.xyxy[0].tolist() if hasattr(box, "xyxy") else [],
                    })
            return detections
        except Exception as e:
            logger.warning("Chart detection error: %s", e)
            return [{"error": str(e)}]

    def get_supported_patterns(self) -> list[str]:
        return list(self._supported_labels)

    def get_status(self) -> dict:
        return {
            "model_loaded": self._model is not None,
            "model_name": self.model_name,
            "supported_patterns": self._supported_labels,
        }
