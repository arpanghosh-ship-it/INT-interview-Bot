#!/usr/bin/env python3
"""
vision_diff.py — Frame change detection using perceptual (average) hashing.

Compares two PNG frames and decides whether the screen changed enough to
warrant sending it to the vision model. This is the cost-control layer —
identical or near-identical frames (static Meet grid, no screen share) are
silently dropped without making any API call.

Algorithm: Average Hash (aHash)
  1. Resize image to 8x8 grayscale (64 pixels total)
  2. Compare each pixel to the mean — produces a 64-bit binary string
  3. Hamming distance between two hashes = number of bits that differ
  4. diff_score = hamming_distance / 64
  5. If diff_score > CHANGED_THRESHOLD → changed

Requires: Pillow (pip install Pillow)
Fallback: If Pillow is not installed, falls back to MD5 of raw bytes
          (binary diff only — any pixel change triggers analysis).

Tuning via .env:
  VISION_DIFF_THRESHOLD=0.08  (default: 8% of bits = ~5 bits out of 64)
  Lower = more sensitive (more API calls)
  Higher = less sensitive (only major changes trigger analysis)
"""

import hashlib
import io
import os
from typing import Optional, Tuple

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False
    print(
        "[VISION_DIFF] ⚠️  Pillow not installed — using MD5 fallback for diff detection. "
        "Install with: pip install Pillow",
        flush=True,
    )

# Fraction of the 64-bit hash that must differ to count as "changed"
CHANGED_THRESHOLD = float(os.getenv("VISION_DIFF_THRESHOLD", "0.08"))


def _avg_hash(image_bytes: bytes, size: int = 8) -> Optional[str]:
    """
    Compute an average hash of the image.

    Returns a binary string of length size*size (e.g. "01101101...") on success,
    or an MD5 hex string as fallback if Pillow is unavailable or fails.
    Returns None only on total failure.
    """
    if not _PIL_AVAILABLE:
        return hashlib.md5(image_bytes).hexdigest()

    try:
        img = (
            Image.open(io.BytesIO(image_bytes))
            .convert("L")                                 # Grayscale
            .resize((size, size), Image.LANCZOS)         # 8x8
        )
        pixels = list(img.getdata())
        avg = sum(pixels) / len(pixels)
        return "".join("1" if p >= avg else "0" for p in pixels)

    except Exception as e:
        # Pillow available but this specific image failed — fall back to MD5
        print(f"[VISION_DIFF] ⚠️  Hash error: {e}", flush=True)
        return hashlib.md5(image_bytes).hexdigest()


def frames_are_different(
    frame_a: Optional[bytes],
    frame_b: Optional[bytes],
) -> Tuple[bool, float]:
    """
    Compare two PNG frames.

    Args:
        frame_a: Previous frame bytes (None if this is the first frame).
        frame_b: Current frame bytes.

    Returns:
        (changed: bool, diff_score: float)
        diff_score: 0.0 = identical, 1.0 = completely different.

    Special cases:
        - frame_a is None (first capture): always returns (True, 1.0)
        - Either frame is empty: returns (True, 1.0)
    """
    if not frame_a or not frame_b:
        return True, 1.0

    hash_a = _avg_hash(frame_a)
    hash_b = _avg_hash(frame_b)

    if hash_a is None or hash_b is None:
        return True, 1.0

    # MD5 fallback path (Pillow unavailable): binary same/different
    if not _PIL_AVAILABLE:
        changed = hash_a != hash_b
        return changed, 1.0 if changed else 0.0

    # Both hashes are bit strings — compute Hamming distance
    if len(hash_a) != len(hash_b):
        return True, 1.0

    diff_bits = sum(a != b for a, b in zip(hash_a, hash_b))
    diff_score = round(diff_bits / len(hash_a), 4)
    changed = diff_score > CHANGED_THRESHOLD

    return changed, diff_score