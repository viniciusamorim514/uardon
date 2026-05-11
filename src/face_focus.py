from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class FocusSegment:
    start: float
    end: float
    x: float
    y: float = 0.42


@dataclass
class FocusAnalysis:
    segments: list[FocusSegment]
    coverage: float
    avg_face_area: float
    quality_score: int
    reason: str


def clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def face_center(face, frame_width: float, frame_height: float) -> tuple[float, float]:
    x, y, w, h = face
    return (
        clamp((x + w / 2) / max(frame_width, 1), 0.14, 0.86),
        clamp((y + h / 2) / max(frame_height, 1), 0.20, 0.72),
    )


def mouth_motion_score(gray, previous_gray, face) -> float:
    if previous_gray is None:
        return 0.0
    try:
        import cv2
    except Exception:
        return 0.0

    x, y, w, h = [int(value) for value in face]
    height, width = gray.shape[:2]
    x1 = max(0, x + int(w * 0.18))
    x2 = min(width, x + int(w * 0.82))
    y1 = max(0, y + int(h * 0.56))
    y2 = min(height, y + int(h * 0.90))
    if x2 <= x1 or y2 <= y1:
        return 0.0

    current = gray[y1:y2, x1:x2]
    previous = previous_gray[y1:y2, x1:x2]
    if current.size == 0 or previous.size == 0:
        return 0.0

    current = cv2.resize(current, (48, 24))
    previous = cv2.resize(previous, (48, 24))
    diff = cv2.absdiff(current, previous)
    return float(diff.mean()) / 255.0


def choose_active_face(faces, gray, previous_gray, frame_width: float, frame_height: float, previous_x: float | None):
    if len(faces) == 1:
        return faces[0]

    best_face = None
    best_score = -1.0
    frame_area = max(frame_width * frame_height, 1)
    for face in faces:
        x, y, w, h = face
        center_x, _ = face_center(face, frame_width, frame_height)
        area_score = (w * h) / frame_area
        motion_score = mouth_motion_score(gray, previous_gray, face)
        continuity_score = 0.0 if previous_x is None else max(0.0, 1.0 - abs(center_x - previous_x) * 2.8) * 0.075
        jump_penalty = 0.0 if previous_x is None else abs(center_x - previous_x) * 0.055
        center_penalty = abs(center_x - 0.5) * 0.006
        score = motion_score * 0.72 + area_score * 0.16 + continuity_score - center_penalty - jump_penalty
        if score > best_score:
            best_score = score
            best_face = face
    return best_face if best_face is not None else max(faces, key=lambda item: item[2] * item[3])


def face_score(gray, previous_gray, face, frame_width: float, frame_height: float, active_x: float | None) -> tuple[float, float, float, float]:
    x, y, w, h = face
    center_x, center_y = face_center(face, frame_width, frame_height)
    frame_area = max(frame_width * frame_height, 1)
    area_score = (w * h) / frame_area
    motion_score = mouth_motion_score(gray, previous_gray, face)
    continuity = 0.0 if active_x is None else max(0.0, 1.0 - abs(center_x - active_x) * 3.0) * 0.10
    jump_penalty = 0.0 if active_x is None else abs(center_x - active_x) * 0.08
    score = motion_score * 0.78 + area_score * 0.18 + continuity - jump_penalty
    return score, center_x, center_y, area_score


def closest_face_to_x(faces, frame_width: float, frame_height: float, target_x: float):
    return min(faces, key=lambda face: abs(face_center(face, frame_width, frame_height)[0] - target_x))


def detect_face_focus(video_path: Path, start_seconds: float, duration: float, samples: int = 12) -> str:
    try:
        import cv2
    except Exception:
        return "center"

    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(cascade_path))
    if detector.empty():
        return "center"

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return "center"

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    width = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1
    centers: list[float] = []

    for index in range(max(1, samples)):
        t = start_seconds + (duration * (index + 0.5) / samples)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4, minSize=(48, 48))
        if len(faces) == 0:
            continue
        x, y, w, h = max(faces, key=lambda item: item[2] * item[3])
        centers.append((x + w / 2) / width)

    cap.release()

    if not centers:
        return "center"

    avg = sum(centers) / len(centers)
    if avg < 0.42:
        return "left"
    if avg > 0.58:
        return "right"
    return "center"


def detect_face_focus_timeline(
    video_path: Path,
    start_seconds: float,
    duration: float,
    samples_per_second: float = 1.2,
) -> list[FocusSegment]:
    return analyze_face_focus(video_path, start_seconds, duration, samples_per_second).segments


def analyze_face_focus(
    video_path: Path,
    start_seconds: float,
    duration: float,
    samples_per_second: float = 0.80,
) -> FocusAnalysis:
    try:
        import cv2
    except Exception:
        return FocusAnalysis([], 0.0, 0.0, 0, "OpenCV indisponivel")

    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(cascade_path))
    if detector.empty():
        return FocusAnalysis([], 0.0, 0.0, 0, "detector de rosto indisponivel")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return FocusAnalysis([], 0.0, 0.0, 0, "nao abriu video")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    width = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1
    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1
    sample_count = max(6, int(duration * samples_per_second))
    points: list[tuple[float, float, float]] = []
    previous_gray = None
    active_x: float | None = None
    active_y: float | None = None
    pending_x: float | None = None
    pending_since: float | None = None
    switch_count = 0
    detected_samples = 0
    face_areas: list[float] = []
    mouth_scores: list[float] = []

    for index in range(sample_count):
        relative = duration * index / max(sample_count - 1, 1)
        t = start_seconds + relative
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4, minSize=(48, 48))
        if len(faces) == 0:
            previous_gray = gray
            continue

        scored = [face_score(gray, previous_gray, face, width, height, active_x) + (face,) for face in faces]
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best_x, best_y, best_area, best_face = scored[0]

        if active_x is None:
            active_face = best_face
            active_x = best_x
            active_y = best_y
            pending_x = None
            pending_since = None
        else:
            active_candidate = closest_face_to_x(faces, width, height, active_x)
            active_candidate_score, active_candidate_x, active_candidate_y, _ = face_score(
                gray,
                previous_gray,
                active_candidate,
                width,
                height,
                active_x,
            )
            wants_switch = abs(best_x - active_x) >= 0.16 and best_score >= active_candidate_score + 0.006
            if wants_switch:
                if pending_x is None or abs(best_x - pending_x) >= 0.10:
                    pending_x = best_x
                    pending_since = relative
                pending_time = relative - (pending_since if pending_since is not None else relative)
                if pending_time >= 3.2:
                    active_face = best_face
                    active_x = best_x
                    active_y = best_y
                    pending_x = None
                    pending_since = None
                    switch_count += 1
                else:
                    active_face = active_candidate
                    active_x = active_x * 0.94 + active_candidate_x * 0.06
                    active_y = (active_y or active_candidate_y) * 0.94 + active_candidate_y * 0.06
            else:
                active_face = active_candidate
                active_x = active_x * 0.88 + active_candidate_x * 0.12
                active_y = (active_y or active_candidate_y) * 0.90 + active_candidate_y * 0.10
                pending_x = None
                pending_since = None

        detected_samples += 1
        _, _, face_w, face_h = active_face
        face_areas.append(float(face_w * face_h) / max(float(width * height), 1.0))
        center_x, center_y = face_center(active_face, width, height)
        mouth_scores.append(mouth_motion_score(gray, previous_gray, active_face))
        previous_gray = gray
        points.append((relative, active_x if active_x is not None else center_x, active_y if active_y is not None else center_y))

    cap.release()

    if len(points) < 2:
        coverage = detected_samples / max(sample_count, 1)
        avg_area = sum(face_areas) / max(len(face_areas), 1)
        return FocusAnalysis([], coverage, avg_area, 0, "poucos rostos detectados")

    smoothed: list[tuple[float, float, float]] = []
    last_x = points[0][1]
    last_y = points[0][2]
    for t, x, y in points:
        last_x = last_x * 0.86 + x * 0.14
        last_y = last_y * 0.88 + y * 0.12
        smoothed.append((t, last_x, last_y))

    segments: list[FocusSegment] = []
    bucket_start = 0.0
    bucket_x = smoothed[0][1]
    bucket_y = smoothed[0][2]
    bucket_size = 0.20
    min_segment_seconds = 4.8
    last_bucket = round(bucket_x / bucket_size) * bucket_size

    for t, x, y in smoothed[1:]:
        bucket = round(x / bucket_size) * bucket_size
        if abs(bucket - last_bucket) >= bucket_size and t - bucket_start >= min_segment_seconds:
            segments.append(
                FocusSegment(
                    float(bucket_start),
                    float(t),
                    float(min(0.86, max(0.14, bucket_x))),
                    float(min(0.72, max(0.20, bucket_y))),
                )
            )
            bucket_start = t
            bucket_x = x
            bucket_y = y
            last_bucket = bucket
        else:
            bucket_x = bucket_x * 0.88 + x * 0.12
            bucket_y = bucket_y * 0.90 + y * 0.10

    segments.append(
        FocusSegment(
            float(bucket_start),
            float(duration),
            float(min(0.86, max(0.14, bucket_x))),
            float(min(0.72, max(0.20, bucket_y))),
        )
    )
    final_segments = merge_short_focus_segments(segments, min_duration=4.5)
    coverage = detected_samples / max(sample_count, 1)
    avg_area = sum(face_areas) / max(len(face_areas), 1)
    score = 100
    reasons: list[str] = []
    if coverage < 0.35:
        score -= 50
        reasons.append("rosto aparece pouco")
    elif coverage < 0.6:
        score -= 24
        reasons.append("rosto intermitente")
    else:
        reasons.append("rosto detectado com boa frequencia")

    if avg_area < 0.010:
        score -= 36
        reasons.append("rosto pequeno demais")
    elif avg_area < 0.018:
        score -= 18
        reasons.append("rosto pequeno")
    else:
        reasons.append("tamanho de rosto aceitavel")

    if not final_segments:
        score -= 30
        reasons.append("sem linha de foco confiavel")
    if switch_count:
        reasons.append(f"falante ativo com {switch_count} troca(s) suavizadas")
    else:
        reasons.append("falante ativo estavel")
    if mouth_scores and sum(mouth_scores) / len(mouth_scores) > 0.010:
        reasons.append("movimento de boca usado no foco")

    return FocusAnalysis(final_segments, coverage, avg_area, max(0, min(100, score)), ", ".join(reasons))


def merge_short_focus_segments(segments: list[FocusSegment], min_duration: float) -> list[FocusSegment]:
    if not segments:
        return []
    merged: list[FocusSegment] = []
    for segment in segments:
        if segment.end - segment.start >= min_duration or not merged:
            merged.append(segment)
            continue
        previous = merged[-1]
        total = max(segment.end - previous.start, 0.01)
        previous_weight = max(previous.end - previous.start, 0.01) / total
        current_weight = max(segment.end - segment.start, 0.01) / total
        merged[-1] = FocusSegment(
            previous.start,
            segment.end,
            clamp(previous.x * previous_weight + segment.x * current_weight, 0.14, 0.86),
            clamp(previous.y * previous_weight + segment.y * current_weight, 0.20, 0.72),
        )
    return merged
