"""Compare local glyph geometry before spending time on OCR.

No page warping is applied to the source raster or to protected field OCR.
"""

from __future__ import annotations


def compare_patch(old, new, *, dpi: int = 200, ncc_threshold: float = 0.985) -> tuple[float, bool]:
    """Return full-overlap NCC and conservative rendering-noise equivalence.

    OpenCV locates a translation with one compiled template search instead of
    centering/copying 121 large numpy patches. The complete overlapping patches
    are then checked, including their borders (where a digit can have changed).
    """
    import cv2
    import numpy as np
    from scipy import ndimage

    h, w = old.shape
    if min(h, w) < 12 or old.shape != new.shape:
        return -1.0, False
    a = ndimage.gaussian_filter(old.astype(np.float32), 1.0)
    b = ndimage.gaussian_filter(new.astype(np.float32), 1.0)
    k = min(5, (h - 5) // 2, (w - 5) // 2)
    template = a[k:h-k, k:w-k]
    if float(template.std()) < 1.0:
        return -1.0, False
    scores = cv2.matchTemplate(b, template, cv2.TM_CCOEFF_NORMED)
    _, _, _, (x, y) = cv2.minMaxLoc(scores)
    dx, dy = x - k, y - k
    ao = a[max(0, -dy):min(h, h-dy), max(0, -dx):min(w, w-dx)]
    bn = b[max(0, dy):min(h, h+dy), max(0, dx):min(w, w+dx)]
    sa, sb = float(ao.std()), float(bn.std())
    if min(sa, sb) < 1.0:
        return -1.0, False
    score = float(((ao - ao.mean()) * (bn - bn.mean())).mean() / (sa * sb))
    if score > ncc_threshold or score < 0.965:
        return score, False

    # A high correlation alone can hide 24 -> 28. Require near-identical glyph
    # contours as a second, independent check for the borderline candidates.
    # Smooth re-encoding halos; tolerate only a sub-point contour displacement.
    sigma = max(0.8, 1.5 * dpi / 200)
    a8 = old[max(0, -dy):min(h, h-dy), max(0, -dx):min(w, w-dx)]
    b8 = new[max(0, dy):min(h, h+dy), max(0, dx):min(w, w+dx)]
    eo = cv2.Canny(cv2.GaussianBlur(a8, (0, 0), sigma), 35, 100) > 0
    en = cv2.Canny(cv2.GaussianBlur(b8, (0, 0), sigma), 35, 100) > 0
    total = int(eo.sum() + en.sum())
    # A sparse/single-glyph crop must reach OCR. A contour displacement that
    # is harmless for a multi-glyph re-encoded block can erase 未 -> 末 or
    # 日 -> 曰. Do not use this shortcut without enough contour evidence.
    if total < 1000:
        return score, False
    tolerance = max(1.0, 2.0 * dpi / 200)
    missing = (eo & (ndimage.distance_transform_edt(~en) > tolerance)) | (
        en & (ndimage.distance_transform_edt(~eo) > tolerance)
    )
    return score, int(missing.sum()) / total < 0.02
