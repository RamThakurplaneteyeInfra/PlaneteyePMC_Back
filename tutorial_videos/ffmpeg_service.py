"""
FFmpeg-based tutorial video analysis + H.264/AAC web optimization.

Does not run inside HTTP request handlers — invoked by video_executor workers.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("pmc.tutorial_videos.ffmpeg")


class VideoProcessingError(Exception):
    """Safe, user-facing processing failure (no FFmpeg dump)."""


@dataclass
class SourceProbe:
    width: int
    height: int
    duration: float
    video_bitrate: int | None
    has_audio: bool


@dataclass
class OptimizeResult:
    output_path: Path
    width: int
    height: int
    duration: float
    output_size: int
    processing_ms: int


def _ffmpeg_bin() -> str:
    return str(getattr(settings, "TUTORIAL_VIDEO_FFMPEG_PATH", "ffmpeg") or "ffmpeg")


def _ffprobe_bin() -> str:
    return str(getattr(settings, "TUTORIAL_VIDEO_FFPROBE_PATH", "ffprobe") or "ffprobe")


def ffmpeg_available() -> bool:
    return bool(shutil.which(_ffmpeg_bin()) and shutil.which(_ffprobe_bin()))


def _setting_int(name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def _setting_str(name: str, default: str) -> str:
    val = getattr(settings, name, default)
    return str(val) if val is not None else default


def probe_source(path: Path) -> SourceProbe:
    cmd = [
        _ffprobe_bin(),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_setting_int("TUTORIAL_VIDEO_FFPROBE_TIMEOUT_SEC", 60),
            check=False,
        )
    except FileNotFoundError as exc:
        raise VideoProcessingError("ffmpeg not available on worker") from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoProcessingError("Video analysis timed out.") from exc

    if proc.returncode != 0:
        raise VideoProcessingError("Invalid or corrupt video file")

    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise VideoProcessingError("Invalid or corrupt video file") from exc

    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video:
        raise VideoProcessingError("Invalid or corrupt video file")

    try:
        width = int(video.get("width") or 0)
        height = int(video.get("height") or 0)
    except (TypeError, ValueError):
        width = height = 0
    if width <= 0 or height <= 0:
        raise VideoProcessingError("Invalid or corrupt video file")

    duration = 0.0
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        try:
            duration = float(video.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0

    vbr = None
    try:
        raw = video.get("bit_rate") or (data.get("format") or {}).get("bit_rate")
        if raw:
            vbr = int(raw)
    except (TypeError, ValueError):
        vbr = None

    return SourceProbe(
        width=width,
        height=height,
        duration=duration,
        video_bitrate=vbr,
        has_audio=audio is not None,
    )


def _target_scale(src: SourceProbe) -> tuple[int, int]:
    max_w = _setting_int("VIDEO_MAX_WIDTH", 1920)
    max_h = _setting_int("VIDEO_MAX_HEIGHT", 1080)
    # Never upscale.
    tw = min(src.width, max_w)
    th = min(src.height, max_h)
    # Preserve aspect: fit inside box.
    scale = min(tw / src.width, th / src.height, 1.0)
    out_w = max(2, int(src.width * scale) // 2 * 2)
    out_h = max(2, int(src.height * scale) // 2 * 2)
    return out_w, out_h


def _video_bitrate_k(src: SourceProbe, out_w: int, out_h: int) -> int:
    """Pick a sensible target bitrate (kbps) from settings + source."""
    configured = _setting_int("VIDEO_TARGET_BITRATE", 0)  # bits or kbps? use kbps
    # Settings store kbps for clarity.
    if configured > 0:
        target = configured
    else:
        pixels = out_w * out_h
        if pixels >= 1920 * 1080:
            target = 4500
        elif pixels >= 1280 * 720:
            target = 2500
        else:
            target = 1200

    if src.video_bitrate and src.video_bitrate > 0:
        src_kbps = max(1, src.video_bitrate // 1000)
        # Do not inflate bitrate above source.
        target = min(target, src_kbps)

    return max(300, target)


def optimize_video(source_path: Path, output_path: Path) -> OptimizeResult:
    if not source_path.is_file():
        raise VideoProcessingError("Source video file is missing.")

    src = probe_source(source_path)
    out_w, out_h = _target_scale(src)
    v_bitrate = _video_bitrate_k(src, out_w, out_h)
    a_bitrate = _setting_int("VIDEO_AUDIO_BITRATE", 128)
    crf = _setting_int("VIDEO_CRF", 23)
    preset = _setting_str("VIDEO_PRESET", "medium")
    timeout = _setting_int("TUTORIAL_VIDEO_FFMPEG_TIMEOUT_SEC", 1800)

    # CRF + optional maxrate cap for streaming predictability.
    vf = f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2"
    cmd = [
        _ffmpeg_bin(),
        "-y",
        "-i",
        str(source_path),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-maxrate",
        f"{v_bitrate}k",
        "-bufsize",
        f"{v_bitrate * 2}k",
        "-pix_fmt",
        "yuv420p",
        "-threads",
        "1",
        "-movflags",
        "+faststart",
    ]
    if src.has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", f"{a_bitrate}k", "-ac", "2"])
    else:
        cmd.append("-an")
    cmd.append(str(output_path))

    logger.info(
        "FFmpeg start in=%sx%s out=%sx%s crf=%s preset=%s maxrate=%sk",
        src.width,
        src.height,
        out_w,
        out_h,
        crf,
        preset,
        v_bitrate,
    )
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise VideoProcessingError("ffmpeg not available on worker") from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoProcessingError("Processing timed out after 10 minutes.") from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if proc.returncode != 0 or not output_path.is_file() or output_path.stat().st_size <= 0:
        # Log truncated stderr for ops; never return it to clients.
        err_tail = (proc.stderr or "")[-800:]
        logger.error("FFmpeg failed code=%s stderr_tail=%s", proc.returncode, err_tail)
        raise VideoProcessingError("Invalid or corrupt video file")

    out_size = output_path.stat().st_size
    logger.info(
        "FFmpeg ok out_size=%s processing_ms=%s",
        out_size,
        elapsed_ms,
    )
    return OptimizeResult(
        output_path=output_path,
        width=out_w,
        height=out_h,
        duration=src.duration,
        output_size=out_size,
        processing_ms=elapsed_ms,
    )
