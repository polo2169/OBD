from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import logging
import shutil

import cv2
import numpy as np
import pymupdf


MIN_DOCUMENT_AREA_RATIO = 0.20


@dataclass(frozen=True)
class NormalizedDocument:
    page_count: int
    crop_methods: list[str]
    rotations: list[int]


def _read_image(path: Path) -> np.ndarray:
    encoded = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Impossible de décoder l’image {path.name}.")
    return image


def _order_points(points: np.ndarray) -> np.ndarray:
    rectangle = np.zeros((4, 2), dtype="float32")
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1)
    rectangle[0] = points[np.argmin(sums)]
    rectangle[1] = points[np.argmin(differences)]
    rectangle[2] = points[np.argmax(sums)]
    rectangle[3] = points[np.argmax(differences)]
    return rectangle


def _document_quad(image: np.ndarray) -> np.ndarray | None:
    height, width = image.shape[:2]
    scale = min(1.0, 1000.0 / max(height, width))
    small = cv2.resize(image, (int(width * scale), int(height * scale)))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 140)
    edges = cv2.morphologyEx(
        edges,
        cv2.MORPH_CLOSE,
        np.ones((7, 7), np.uint8),
        iterations=1,
    )
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    image_area = small.shape[0] * small.shape[1]
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:12]:
        perimeter = cv2.arcLength(contour, True)
        approximation = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if (
            len(approximation) == 4
            and cv2.isContourConvex(approximation)
            and cv2.contourArea(approximation) > MIN_DOCUMENT_AREA_RATIO * image_area
        ):
            return approximation.reshape(4, 2).astype("float32") / scale
    return None


def _binary_runs(values: np.ndarray) -> list[tuple[int, int]]:
    """Return the half-open runs of true pixels in a one-dimensional mask."""

    padded = np.concatenate((np.array([False]), values.astype(bool), np.array([False])))
    changes = np.diff(padded.astype(np.int8))
    return list(zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)))


def _robust_line(points: list[tuple[int, int]]) -> np.ndarray | None:
    """Fit ``value = slope * position + intercept`` while rejecting outliers."""

    values = np.asarray(points, dtype=float)
    if len(values) < 10:
        return None
    kept = np.ones(len(values), dtype=bool)
    coefficients: np.ndarray | None = None
    for _ in range(5):
        if np.unique(values[kept, 0]).size < 2:
            return None
        coefficients = np.polyfit(values[kept, 0], values[kept, 1], 1)
        residuals = np.abs(values[:, 1] - np.polyval(coefficients, values[:, 0]))
        median = float(np.median(residuals[kept]))
        deviation = float(np.median(np.abs(residuals[kept] - median)))
        updated = residuals < max(4.0, median + 2.5 * max(1.0, deviation))
        if np.array_equal(updated, kept):
            break
        kept = updated
    return coefficients if coefficients is not None and kept.sum() >= 10 else None


def _scanline_document_quad(image: np.ndarray) -> np.ndarray | None:
    """Recover a photographed page whose outline is partly hidden.

    A stack of invoices often prevents the Canny contour from closing: another
    sheet hides one corner and a light table touches the bottom edge.  The main
    page still creates a broad, bright run through most rows and columns.  Fit
    its four boundaries from those runs and reject the paper/table outliers.
    """

    original_height, original_width = image.shape[:2]
    scale = min(1.0, 1000.0 / max(original_height, original_width))
    small = image if scale == 1.0 else cv2.resize(
        image,
        (int(original_width * scale), int(original_height * scale)),
        interpolation=cv2.INTER_AREA,
    )
    height, width = small.shape[:2]
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (15, 15), 0)
    otsu, _ = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = (blurred > max(90.0, float(otsu))).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)) > 0

    left_points: list[tuple[int, int]] = []
    right_points: list[tuple[int, int]] = []
    for y in range(int(0.05 * height), int(0.98 * height), 2):
        candidates = [
            (start, end)
            for start, end in _binary_runs(mask[y])
            if end - start > 0.28 * width and start < 0.58 * width and end > 0.42 * width
        ]
        if not candidates:
            continue
        start, end = min(
            candidates,
            key=lambda run: abs((run[0] + run[1]) / 2 - width / 2) - 0.15 * (run[1] - run[0]),
        )
        if 0.01 * width < start < 0.42 * width:
            left_points.append((y, start))
        if 0.58 * width < end < 0.99 * width:
            right_points.append((y, end))

    left = _robust_line(left_points)
    right = _robust_line(right_points)
    if left is None or right is None:
        return None

    middle_y = 0.55 * height
    middle_left = float(np.polyval(left, middle_y))
    middle_right = float(np.polyval(right, middle_y))
    page_width = middle_right - middle_left
    if page_width < 0.25 * width:
        return None

    top_points: list[tuple[int, int]] = []
    bottom_points: list[tuple[int, int]] = []
    for x in range(int(0.12 * width), int(0.88 * width), 3):
        if not middle_left + 10 < x < middle_right - 10:
            continue
        candidates = [
            (start, end)
            for start, end in _binary_runs(mask[:, x])
            if end - start > 0.40 * height and start < 0.55 * height and end > 0.55 * height
        ]
        if not candidates:
            continue
        start, end = max(candidates, key=lambda run: run[1] - run[0])
        if 0.01 * height < start < 0.40 * height:
            top_points.append((x, start))
        if 0.72 * height < end < 0.99 * height:
            bottom_points.append((x, end))

    top = _robust_line(top_points)
    bottom = _robust_line(bottom_points)
    if top is None:
        top = np.array([0.0, max(0.02 * height, middle_y - 0.72 * page_width)])
    if bottom is None:
        inferred_bottom = min(0.99 * height, float(np.polyval(top, width / 2)) + 1.45 * page_width)
        bottom = np.array([0.0, inferred_bottom])

    def intersection(vertical: np.ndarray, horizontal: np.ndarray) -> list[float]:
        # vertical: x = a*y+b; horizontal: y = c*x+d
        a, b = vertical
        c, d = horizontal
        denominator = 1.0 - c * a
        if abs(denominator) < 1e-6:
            return [float("nan"), float("nan")]
        y = (c * b + d) / denominator
        return [a * y + b, y]

    points = np.asarray(
        [
            intersection(left, top),
            intersection(right, top),
            intersection(right, bottom),
            intersection(left, bottom),
        ],
        dtype="float32",
    )
    if not np.isfinite(points).all():
        return None

    # Stay just inside the fitted paper boundary.  That removes the thin desk
    # wedges caused by curled edges without sacrificing the document margins.
    center = points.mean(axis=0)
    points = center + (points - center) * 0.98
    points[:, 0] = np.clip(points[:, 0], 0, width - 1)
    points[:, 1] = np.clip(points[:, 1], 0, height - 1)
    if not cv2.isContourConvex(points.astype(np.int32)):
        return None
    if cv2.contourArea(points) < MIN_DOCUMENT_AREA_RATIO * width * height:
        return None
    return points / scale


def _content_bbox(image: np.ndarray) -> tuple[int, int, int, int] | None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    image_area = image.shape[0] * image.shape[1]
    candidates: list[tuple[int, int, int, int, int]] = []
    for index in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[index])
        if area >= 0.10 * image_area and width * height >= 0.15 * image_area:
            candidates.append((area, x, y, width, height))
    if not candidates:
        return None
    _, x, y, width, height = max(candidates)
    margin = max(4, int(0.01 * max(width, height)))
    return (
        max(0, x - margin),
        max(0, y - margin),
        min(image.shape[1], x + width + margin),
        min(image.shape[0], y + height + margin),
    )


def _warp(image: np.ndarray, points: np.ndarray) -> np.ndarray:
    top_left, top_right, bottom_right, bottom_left = _order_points(points)
    width = max(
        int(np.linalg.norm(bottom_right - bottom_left)),
        int(np.linalg.norm(top_right - top_left)),
    )
    height = max(
        int(np.linalg.norm(top_right - bottom_right)),
        int(np.linalg.norm(top_left - bottom_left)),
    )
    if width < 2 or height < 2:
        return image
    destination = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(
        np.array([top_left, top_right, bottom_right, bottom_left], dtype="float32"),
        destination,
    )
    return cv2.warpPerspective(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def crop_document(image: np.ndarray) -> tuple[np.ndarray, str]:
    points = _document_quad(image)
    if points is not None:
        return _warp(image, points), "perspective"
    points = _scanline_document_quad(image)
    if points is not None:
        return _warp(image, points), "scanline-perspective"
    box = _content_bbox(image)
    if box is not None:
        x0, y0, x1, y1 = box
        return image[y0:y1, x0:x1], "content"
    return image, "original"


def _rotate(image: np.ndarray, degrees: int) -> np.ndarray:
    return {
        0: lambda: image.copy(),
        90: lambda: cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE),
        180: lambda: cv2.rotate(image, cv2.ROTATE_180),
        270: lambda: cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE),
    }[degrees]()


@lru_cache(maxsize=1)
def _ocr_engine():
    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
    from rapidocr import ModelType, OCRVersion, RapidOCR

    return RapidOCR(params={
        "Det.model_type": ModelType.SMALL,
        "Det.ocr_version": OCRVersion.PPOCRV6,
        "Rec.model_type": ModelType.SMALL,
        "Rec.ocr_version": OCRVersion.PPOCRV6,
        "Global.text_score": 0.45,
    })


def _orientation_score(result) -> float:
    boxes_value = getattr(result, "boxes", None)
    texts_value = getattr(result, "txts", None)
    scores_value = getattr(result, "scores", None)
    boxes = [] if boxes_value is None else list(boxes_value)
    texts = [] if texts_value is None else list(texts_value)
    scores = [] if scores_value is None else list(scores_value)
    horizontal = 0.0
    vertical = 0.0
    for box, text, score in zip(boxes, texts, scores):
        points = np.asarray(box, dtype=float)
        width = (np.linalg.norm(points[1] - points[0]) + np.linalg.norm(points[2] - points[3])) / 2
        height = (np.linalg.norm(points[3] - points[0]) + np.linalg.norm(points[2] - points[1])) / 2
        weight = max(1, sum(character.isalnum() for character in str(text))) * float(score) ** 2
        if width >= height:
            horizontal += weight
        else:
            vertical += weight
    return horizontal - 1.5 * vertical


def detect_orientation(image: np.ndarray) -> int:
    scale = min(1.0, 800 / max(image.shape[:2]))
    small = image if scale == 1 else cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    candidates = [
        (_orientation_score(_ocr_engine()(_rotate(small, degrees))), degrees)
        for degrees in (0, 90, 180, 270)
    ]
    return max(candidates)[1]


def _append_image_page(document: pymupdf.Document, image: np.ndarray) -> None:
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise ValueError("Impossible d’encoder la page recadrée.")
    height, width = image.shape[:2]
    scale = min(1.0, 842 / max(width, height))
    page = document.new_page(width=max(1, width * scale), height=max(1, height * scale))
    page.insert_image(page.rect, stream=encoded.tobytes())


def normalize_sources_to_pdf(
    sources: list[Path],
    destination: Path,
    *,
    rotations_by_name: dict[str, int] | None = None,
) -> NormalizedDocument:
    if not sources:
        raise ValueError("Aucune page source à convertir en PDF.")
    if len(sources) == 1 and sources[0].suffix.casefold() == ".pdf":
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sources[0], destination)
        try:
            with pymupdf.open(sources[0]) as original:
                page_count = max(1, original.page_count)
        except Exception:
            page_count = 1
        return NormalizedDocument(page_count, ["pdf"] * page_count, [0] * page_count)
    output = pymupdf.open()
    crop_methods: list[str] = []
    rotations: list[int] = []
    try:
        for source in sources:
            if source.suffix.casefold() == ".pdf":
                with pymupdf.open(source) as original:
                    if original.page_count < 1:
                        raise ValueError(f"Le PDF {source.name} est vide.")
                    output.insert_pdf(original)
                    crop_methods.extend(["pdf"] * original.page_count)
                    rotations.extend([0] * original.page_count)
                continue
            cropped, method = crop_document(_read_image(source))
            configured_rotation = (rotations_by_name or {}).get(source.name)
            rotation = configured_rotation if configured_rotation in {0, 90, 180, 270} else detect_orientation(cropped)
            _append_image_page(output, _rotate(cropped, rotation))
            crop_methods.append(method)
            rotations.append(rotation)
        if output.page_count < 1:
            raise ValueError("Le document normalisé ne contient aucune page.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".pdf.tmp")
        output.save(temporary, garbage=4, deflate=True)
        temporary.replace(destination)
        return NormalizedDocument(output.page_count, crop_methods, rotations)
    finally:
        output.close()
