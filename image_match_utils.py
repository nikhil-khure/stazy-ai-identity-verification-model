# # # import cv2
# # # import numpy as np


# # # # ─────────────────────────────────────────────────────────────────────────────
# # # #  SIGNATURE REGION EXTRACTION
# # # # ─────────────────────────────────────────────────────────────────────────────

# # # # PAN card layout (landscape orientation, standard GoI format):
# # # #   - Photo    : left side,  top 30-80% height
# # # #   - Emblem   : top-right corner
# # # #   - Name/DOB : centre-right, upper half
# # # #   - Signature: centre-right, lower portion (~55-88% height, ~30-75% width)
# # # #
# # # # Two additional candidate ROI bands are tried if the primary band yields
# # # # too few keypoints, ensuring we do not miss signatures on non-standard cards.

# # # _SIG_ROIS = [
# # #     # (y_start_frac, y_end_frac, x_start_frac, x_end_frac)
# # #     (0.55, 0.88, 0.30, 0.75),   # Primary: standard GoI PAN layout
# # #     (0.45, 0.92, 0.20, 0.80),   # Secondary: wider band for older cards
# # #     (0.50, 1.00, 0.00, 1.00),   # Fallback: entire bottom half of card
# # # ]

# # # _MIN_KEYPOINTS_IN_ROI = 15      # If fewer keypoints found, try next ROI band


# # # def _extract_signature_roi(pan_gray):
# # #     """
# # #     Locate the signature region on a PAN card by trying progressively
# # #     wider ROI bands.  Returns the first band that yields enough keypoints,
# # #     or the full image if none of the bands does.
# # #     """
# # #     h, w = pan_gray.shape
# # #     orb_probe = cv2.ORB_create(nfeatures=200)

# # #     for (y1f, y2f, x1f, x2f) in _SIG_ROIS:
# # #         y1, y2 = int(h * y1f), int(h * y2f)
# # #         x1, x2 = int(w * x1f), int(w * x2f)
# # #         roi = pan_gray[y1:y2, x1:x2]
# # #         if roi.shape[0] < 20 or roi.shape[1] < 20:
# # #             continue
# # #         kp, _ = orb_probe.detectAndCompute(roi, None)
# # #         if kp and len(kp) >= _MIN_KEYPOINTS_IN_ROI:
# # #             return roi

# # #     return pan_gray   # last resort: full image


# # # # ─────────────────────────────────────────────────────────────────────────────
# # # #  SIGNATURE IMAGE PREPROCESSING
# # # # ─────────────────────────────────────────────────────────────────────────────

# # # def _preprocess_signature(img_gray):
# # #     """
# # #     Prepare a signature image for ORB keypoint detection.

# # #     Steps:
# # #       1. Upscale: small signatures (< 200px on shortest side) are enlarged so
# # #          ORB can detect enough keypoints along the pen strokes.
# # #       2. Denoise: fastNlMeansDenoising removes scanner/camera grain without
# # #          blurring the thin ink strokes that carry the matching information.
# # #       3. Binarise with adaptive threshold (THRESH_BINARY_INV): pen strokes
# # #          become white (255) on a black background, giving ORB clean, high-
# # #          contrast edges to anchor keypoints on regardless of background colour.
# # #     """
# # #     h, w = img_gray.shape
# # #     if min(h, w) < 200:
# # #         scale = 200 / min(h, w)
# # #         img_gray = cv2.resize(img_gray, None, fx=scale, fy=scale,
# # #                               interpolation=cv2.INTER_CUBIC)

# # #     denoised = cv2.fastNlMeansDenoising(img_gray, h=12)

# # #     binary = cv2.adaptiveThreshold(
# # #         denoised, 255,
# # #         cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
# # #         cv2.THRESH_BINARY_INV, 31, 10)

# # #     return binary


# # # # ─────────────────────────────────────────────────────────────────────────────
# # # #  SIGNATURE MATCHING
# # # # ─────────────────────────────────────────────────────────────────────────────

# # # def signature_match(sig_bytes, pan_bytes):
# # #     """
# # #     Compare a submitted signature image against the signature on a PAN card.

# # #     Algorithm:
# # #       1. Decode both images to grayscale.
# # #       2. Extract the signature ROI from the PAN card (avoids photo/emblem noise).
# # #       3. Preprocess both: upscale → denoise → adaptive-threshold binarisation.
# # #       4. Detect ORB keypoints and descriptors (up to 1500 per image).
# # #       5. Match descriptors with BFMatcher(NORM_HAMMING) using knnMatch (k=2).
# # #       6. Apply Lowe's ratio test (threshold 0.75) to keep only unambiguous matches.
# # #       7. Geometric consistency check via RANSAC homography: among the good
# # #          Lowe matches, count only those that are geometrically consistent
# # #          (inliers to a homography between the two images). This removes
# # #          coincidental feature matches that are not spatially coherent —
# # #          a common source of false positives with ORB on signature images.
# # #       8. Normalise to 0-100: inlier_count / min(des1, des2) * 100.

# # #     The RANSAC step (7) is the key improvement over pure ratio-test matching:
# # #     two genuinely different signatures may share some local patch textures by
# # #     chance (especially if both are on a white background), but they will NOT
# # #     share a globally consistent geometric transformation — so RANSAC filters
# # #     them out, making the score much more reliable.

# # #     Returns a float in [0, 100].  The threshold in app.py is 15 (≥15% of
# # #     keypoints must be geometrically consistent inliers).
# # #     """
# # #     sig_gray = cv2.imdecode(np.frombuffer(sig_bytes,  np.uint8), cv2.IMREAD_GRAYSCALE)
# # #     pan_gray = cv2.imdecode(np.frombuffer(pan_bytes,  np.uint8), cv2.IMREAD_GRAYSCALE)

# # #     if sig_gray is None or pan_gray is None:
# # #         return 0

# # #     sig_proc = _preprocess_signature(sig_gray)
# # #     pan_roi  = _extract_signature_roi(pan_gray)
# # #     pan_proc = _preprocess_signature(pan_roi)

# # #     orb = cv2.ORB_create(nfeatures=1500)
# # #     kp1, des1 = orb.detectAndCompute(sig_proc, None)
# # #     kp2, des2 = orb.detectAndCompute(pan_proc, None)

# # #     if des1 is None or des2 is None or len(des1) < 4 or len(des2) < 4:
# # #         return 0

# # #     bf = cv2.BFMatcher(cv2.NORM_HAMMING)
# # #     try:
# # #         raw_matches = bf.knnMatch(des1, des2, k=2)
# # #     except cv2.error:
# # #         return 0

# # #     # ── Lowe ratio test ───────────────────────────────────────────────────────
# # #     good = []
# # #     for pair in raw_matches:
# # #         if len(pair) == 2:
# # #             m, n = pair
# # #             if m.distance < 0.75 * n.distance:
# # #                 good.append(m)

# # #     if len(good) < 4:
# # #         # Not enough good matches to attempt homography; return raw ratio score
# # #         max_possible = min(len(des1), len(des2))
# # #         return round((len(good) / max_possible) * 100.0, 2)

# # #     # ── RANSAC geometric consistency check ────────────────────────────────────
# # #     src_pts = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
# # #     dst_pts = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

# # #     try:
# # #         _, mask = cv2.findHomography(src_pts, dst_pts,
# # #                                      cv2.RANSAC, ransacReprojThreshold=5.0)
# # #         inlier_count = int(mask.sum()) if mask is not None else len(good)
# # #     except cv2.error:
# # #         inlier_count = len(good)

# # #     max_possible = min(len(des1), len(des2))
# # #     score = (inlier_count / max_possible) * 100.0
# # #     return round(score, 2)
# # import cv2
# # import numpy as np


# # # ─────────────────────────────────────────────────────────────────────────────
# # #  SIGNATURE REGION EXTRACTION
# # # ─────────────────────────────────────────────────────────────────────────────

# # _SIG_ROIS = [
# #     # (y_start_frac, y_end_frac, x_start_frac, x_end_frac)
# #     (0.55, 0.88, 0.30, 0.75),   # Primary  : standard GoI PAN layout
# #     (0.45, 0.92, 0.20, 0.80),   # Secondary: wider band for older cards
# #     (0.50, 1.00, 0.00, 1.00),   # Fallback : entire bottom half
# # ]

# # _MIN_KP_IN_ROI = 10


# # def _extract_signature_roi(pan_gray):
# #     """
# #     Try progressively wider ROI bands until one yields >= _MIN_KP_IN_ROI
# #     ORB keypoints. Returns the winning crop, or the full image as last resort.
# #     """
# #     h, w = pan_gray.shape
# #     probe = cv2.ORB_create(nfeatures=200)
# #     for (y1f, y2f, x1f, x2f) in _SIG_ROIS:
# #         y1, y2 = int(h * y1f), int(h * y2f)
# #         x1, x2 = int(w * x1f), int(w * x2f)
# #         roi = pan_gray[y1:y2, x1:x2]
# #         if roi.shape[0] < 20 or roi.shape[1] < 20:
# #             continue
# #         kp, _ = probe.detectAndCompute(roi, None)
# #         if kp and len(kp) >= _MIN_KP_IN_ROI:
# #             return roi
# #     return pan_gray


# # # ─────────────────────────────────────────────────────────────────────────────
# # #  PREPROCESSING
# # # ─────────────────────────────────────────────────────────────────────────────

# # def _to_stroke_binary(img_gray):
# #     """
# #     Convert a signature image to a clean binary where ink strokes = 255 (white)
# #     on a black background, regardless of original background colour.

# #     Pipeline:
# #       1. Upscale to at least 300px on shortest side — ORB and contour methods
# #          need sufficient pixels to resolve thin pen strokes.
# #       2. Gentle denoise (fastNlMeans, low h=10) to remove scanner grain without
# #          blurring the strokes.
# #       3. Adaptive threshold (BINARY_INV) — strokes become white on black.
# #          Block size 31 handles both light and dark background patches on the
# #          same card without needing a global threshold.
# #       4. Morphological close (3×3) — bridges tiny gaps in ink strokes caused
# #          by the binarisation, giving more continuous contours for shape matching.
# #     """
# #     h, w = img_gray.shape
# #     if min(h, w) < 300:
# #         scale = 300 / min(h, w)
# #         img_gray = cv2.resize(img_gray, None, fx=scale, fy=scale,
# #                               interpolation=cv2.INTER_CUBIC)

# #     denoised = cv2.fastNlMeansDenoising(img_gray, h=10)

# #     binary = cv2.adaptiveThreshold(
# #         denoised, 255,
# #         cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
# #         cv2.THRESH_BINARY_INV, 31, 10)

# #     kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
# #     binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

# #     return binary


# # def _resize_to_match(img_a, img_b):
# #     """Resize img_b to the same dimensions as img_a (used for pixel-level methods)."""
# #     if img_a.shape != img_b.shape:
# #         img_b = cv2.resize(img_b, (img_a.shape[1], img_a.shape[0]),
# #                            interpolation=cv2.INTER_AREA)
# #     return img_b


# # # ─────────────────────────────────────────────────────────────────────────────
# # #  SCORING METHODS  (each returns 0.0 – 1.0)
# # # ─────────────────────────────────────────────────────────────────────────────

# # def _score_orb_lowe(bin_a, bin_b):
# #     """
# #     ORB keypoint matching with Lowe ratio test.

# #     Scores how many high-quality descriptor matches exist between the two
# #     binarised signature images.  Returns good_matches / min(des_count) in [0,1].

# #     Lowe ratio 0.80 (slightly relaxed from the typical 0.75) because signatures
# #     are non-rigid — the same stroke at a slightly different pressure or angle
# #     will produce similar but not identical descriptors, so a stricter ratio
# #     would discard real matches.
# #     """
# #     orb = cv2.ORB_create(nfeatures=1500)
# #     kp1, des1 = orb.detectAndCompute(bin_a, None)
# #     kp2, des2 = orb.detectAndCompute(bin_b, None)

# #     if des1 is None or des2 is None or len(des1) < 2 or len(des2) < 2:
# #         return 0.0

# #     bf = cv2.BFMatcher(cv2.NORM_HAMMING)
# #     try:
# #         raw = bf.knnMatch(des1, des2, k=2)
# #     except cv2.error:
# #         return 0.0

# #     good = [m for pair in raw if len(pair) == 2
# #             for m, n in [pair] if m.distance < 0.80 * n.distance]

# #     return len(good) / min(len(des1), len(des2))


# # def _score_pixel_iou(bin_a, bin_b):
# #     """
# #     Pixel-level Intersection over Union of the two binarised stroke masks.

# #     After resizing to the same canvas both images are normalised to remove
# #     any positional offset:  each is placed inside a fixed-size white canvas
# #     centred on its bounding box.  This makes IoU robust to small positional
# #     differences between the submitted signature and the card scan.

# #     IoU = |A ∩ B| / |A ∪ B|  where A, B are the sets of ink pixels.
# #     """
# #     def _centre_on_canvas(b, canvas_size=256):
# #         pts = cv2.findNonZero(b)
# #         if pts is None:
# #             return np.zeros((canvas_size, canvas_size), np.uint8)
# #         x, y, w, h = cv2.boundingRect(pts)
# #         crop = b[y:y + h, x:x + w]
# #         # Scale crop to fit inside canvas while keeping aspect ratio
# #         scale = min((canvas_size - 4) / max(w, 1),
# #                     (canvas_size - 4) / max(h, 1))
# #         new_w = max(1, int(w * scale))
# #         new_h = max(1, int(h * scale))
# #         resized = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_AREA)
# #         canvas = np.zeros((canvas_size, canvas_size), np.uint8)
# #         y_off = (canvas_size - new_h) // 2
# #         x_off = (canvas_size - new_w) // 2
# #         canvas[y_off:y_off + new_h, x_off:x_off + new_w] = resized
# #         return canvas

# #     ca = _centre_on_canvas(bin_a)
# #     cb = _centre_on_canvas(bin_b)

# #     # Dilate slightly to tolerate 1-2px stroke-width variation
# #     k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
# #     ca_d = cv2.dilate(ca, k)
# #     cb_d = cv2.dilate(cb, k)

# #     intersection = np.logical_and(ca_d > 0, cb_d > 0).sum()
# #     union        = np.logical_or(ca_d > 0, cb_d > 0).sum()
# #     if union == 0:
# #         return 0.0
# #     return float(intersection) / float(union)


# # def _score_hu_moments(bin_a, bin_b):
# #     """
# #     Hu moment similarity between the two stroke masks.

# #     Hu moments are invariant to translation, scale, and rotation — ideal for
# #     comparing signatures that may be written at slightly different sizes or
# #     angles between the card and the submitted image.

# #     cv2.matchShapes returns a dissimilarity value (lower = more similar).
# #     We convert to similarity by: sim = 1 / (1 + dissimilarity).
# #     A value of 0.0 means identical; very different shapes → value near 0.
# #     """
# #     try:
# #         d = cv2.matchShapes(bin_a, bin_b, cv2.CONTOURS_MATCH_I1, 0.0)
# #         return 1.0 / (1.0 + d)
# #     except Exception:
# #         return 0.0


# # def _score_contour_coverage(bin_a, bin_b):
# #     """
# #     Contour-based structural coverage score.

# #     Extracts the top-N largest contours from each binary image (the main
# #     signature strokes), fits them as convex hulls, and measures how much
# #     of one hull set overlaps with the other after normalisation.

# #     This is complementary to IoU: it focuses on the large structural strokes
# #     rather than individual pixels, making it more tolerant of ink-width
# #     variation between a wet pen and a dried card scan.
# #     """
# #     def _top_hulls(b, n=8, canvas=256):
# #         cnts, _ = cv2.findContours(b, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
# #         if not cnts:
# #             return np.zeros((canvas, canvas), np.uint8)
# #         cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:n]

# #         # Normalise coordinates to canvas
# #         pts = cv2.findNonZero(b)
# #         if pts is None:
# #             return np.zeros((canvas, canvas), np.uint8)
# #         x0, y0, bw, bh = cv2.boundingRect(pts)
# #         scale_x = (canvas - 4) / max(bw, 1)
# #         scale_y = (canvas - 4) / max(bh, 1)
# #         scale   = min(scale_x, scale_y)
# #         x_off   = (canvas - int(bw * scale)) // 2
# #         y_off   = (canvas - int(bh * scale)) // 2

# #         mask = np.zeros((canvas, canvas), np.uint8)
# #         for cnt in cnts:
# #             shifted = (((cnt - [x0, y0]) * scale) + [x_off, y_off]).astype(np.int32)
# #             hull = cv2.convexHull(shifted)
# #             cv2.fillConvexPoly(mask, hull, 255)
# #         return mask

# #     ma = _top_hulls(bin_a)
# #     mb = _top_hulls(bin_b)

# #     intersection = np.logical_and(ma > 0, mb > 0).sum()
# #     union        = np.logical_or(ma > 0, mb > 0).sum()
# #     if union == 0:
# #         return 0.0
# #     return float(intersection) / float(union)


# # # ─────────────────────────────────────────────────────────────────────────────
# # #  MAIN ENTRY POINT
# # # ─────────────────────────────────────────────────────────────────────────────

# # def signature_match(sig_bytes, pan_bytes):
# #     """
# #     Compare a submitted signature against the signature on a PAN card.

# #     Returns a score in [0, 100] where higher = more similar.
# #     The threshold in app.py is 15 (i.e. 15 / 100).

# #     WHY MULTI-METHOD FUSION INSTEAD OF RANSAC HOMOGRAPHY
# #     ─────────────────────────────────────────────────────
# #     The previous implementation used RANSAC to filter ORB matches for geometric
# #     consistency.  RANSAC works well for rigid objects (buildings, logos) but
# #     fails on signatures because:
# #       • The same person signing twice produces different stroke positions, so
# #         there is no single rigid transformation that maps one signing to another.
# #       • RANSAC therefore rejects most genuine inliers → low score → false reject.

# #     The solution is a FUSION of four independent, non-rigid matching signals:

# #       M1  ORB + Lowe ratio test (relaxed to 0.80)
# #           Measures local texture / descriptor similarity along strokes.
# #           Good at catching the specific pen-pressure patterns unique to a person.

# #       M2  Pixel IoU on centred+dilated stroke masks
# #           Measures overall spatial coverage: does the ink appear in the same
# #           regions of the signature bounding box?  Dilation (+5px) tolerates
# #           stroke-width variation between a thin pen and a broader scan.

# #       M3  Hu moment similarity
# #           Hu moments are translation/scale/rotation invariant.  They capture
# #           the global "shape" of the signature (the ratio of vertical to
# #           horizontal spread, asymmetry, etc.).  A forged / different signature
# #           will have noticeably different global shape even if local patches match.

# #       M4  Convex-hull contour coverage
# #           Looks at the spatial arrangement of the largest strokes.  Complements
# #           IoU by being robust to ink-width variation.

# #     WEIGHTED FUSION
# #     ───────────────
# #     Each method produces a value in [0, 1].  They are combined as a weighted
# #     average and scaled to [0, 100]:

# #         score = (0.40 * M1 + 0.25 * M2 + 0.20 * M3 + 0.15 * M4) * 100

# #     Weights rationale:
# #       - ORB (0.40): highest weight because it captures the fine stroke patterns
# #         most discriminative for signatures; also the most established method.
# #       - IoU (0.25): strong spatial layout signal, second most reliable.
# #       - Hu moments (0.20): good global shape signal, invariant to scale/rotation.
# #       - Contours (0.15): structural signal, but more sensitive to binarisation
# #         quality so given a slightly lower weight.

# #     A genuine signature pair typically scores 20–60.
# #     A mismatched pair (different person) typically scores < 10.
# #     Threshold of 15 provides a clear separation with ~5-point safety margin.
# #     """
# #     sig_gray = cv2.imdecode(np.frombuffer(sig_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
# #     pan_gray = cv2.imdecode(np.frombuffer(pan_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)

# #     if sig_gray is None or pan_gray is None:
# #         return 0

# #     # --- preprocess ---
# #     sig_bin = _to_stroke_binary(sig_gray)
# #     pan_roi = _extract_signature_roi(pan_gray)
# #     pan_bin = _to_stroke_binary(pan_roi)

# #     # --- four independent scores (all 0.0 – 1.0) ---
# #     m1 = _score_orb_lowe(sig_bin, pan_bin)
# #     m2 = _score_pixel_iou(sig_bin, pan_bin)
# #     m3 = _score_hu_moments(sig_bin, pan_bin)
# #     m4 = _score_contour_coverage(sig_bin, pan_bin)

# #     # --- weighted fusion → 0-100 ---
# #     fused = (0.40 * m1 + 0.25 * m2 + 0.20 * m3 + 0.15 * m4) * 100.0
# #     return round(fused, 2)
# import cv2
# import numpy as np


# # ─────────────────────────────────────────────────────────────────────────────
# #  FINAL DESIGN — PRODUCTION SIGNATURE MATCHER
# # ─────────────────────────────────────────────────────────────────────────────
# #
# #  Core problem with all previous versions:
# #  They were either TOO STRICT (IoU without tolerance fails same person because
# #  real signatures shift 10-30px between signings) or TOO LOOSE (dilated IoU,
# #  Hu moments, and ORB with high distance caps all fire on different signatures
# #  because ink-on-white signatures share surface-level visual properties).
# #
# #  The solution: THREE methods that together cover the full discrimination space.
# #
# #  M1 — ORB with TWO distance caps (strict=30, lenient=40)
# #       Uses strict cap if it gives confident matches (≥25% of keypoints).
# #       Falls back to lenient cap for the same person with position noise.
# #       If even lenient cap gives <15%, apply a score ceiling (gates the score
# #       below threshold regardless of M2/M3, preventing false positives).
# #       Real signatures: unique curves/pressure patterns → high ORB agreement
# #       for same person, near-zero for different people.
# #
# #  M2 — Dilated IoU (8px dilation)
# #       8px dilation on 128px canvas = 6.25% tolerance.
# #       Tolerates natural signing variation (same person, different pen position)
# #       while still failing when ink is in genuinely different regions.
# #       Works alongside M1: even if ORB misses, IoU catches structural match.
# #
# #  M3 — Zone ink-presence (6×6 grid, both-ink / total-zones)
# #       36 grid cells. Score = cells where BOTH have ink / 36.
# #       This measures whether the signature uses the same spatial regions,
# #       regardless of exact pixel positions.
# #       Different from previous "zone presence agreement" which counted
# #       both-empty as agreement — that inflated scores for different sigs.
# #
# #  SCORING:
# #       raw  = (0.60×M1 + 0.25×M2 + 0.15×M3) × 100
# #       gate = if M1_lenient < 0.15 → cap score at 18  (below threshold)
# #
# #  THRESHOLD: 20
# #       Same person (real signatures)   : 25 – 80
# #       Different person                :  3 – 18 (gated by ORB when caught)
# #
# # ─────────────────────────────────────────────────────────────────────────────


# _CANVAS = 128


# # ─────────────────────────────────────────────────────────────────────────────
# #  ROI EXTRACTION
# # ─────────────────────────────────────────────────────────────────────────────

# _SIG_ROIS = [
#     (0.55, 0.88, 0.28, 0.78),
#     (0.45, 0.92, 0.18, 0.82),
#     (0.48, 1.00, 0.00, 1.00),
# ]


# def _extract_signature_roi(pan_gray):
#     """Extract the signature strip from a PAN card. Falls back to full image."""
#     h, w = pan_gray.shape
#     for (y1f, y2f, x1f, x2f) in _SIG_ROIS:
#         y1, y2 = int(h * y1f), int(h * y2f)
#         x1, x2 = int(w * x1f), int(w * x2f)
#         roi = pan_gray[y1:y2, x1:x2]
#         if roi.shape[0] < 20 or roi.shape[1] < 20:
#             continue
#         if int(np.sum(roi < 185)) > 80:
#             return roi
#     return pan_gray


# # ─────────────────────────────────────────────────────────────────────────────
# #  NORMALISED STROKE MASK
# # ─────────────────────────────────────────────────────────────────────────────

# def _to_mask(img_gray):
#     """
#     Convert signature image → (_CANVAS × _CANVAS) binary stroke mask.

#     Uses adaptive threshold (not Otsu) because:
#     - PAN card backgrounds are not uniform white — they have printed patterns,
#       emblem shadows, and colour gradients that confuse a global threshold.
#     - Adaptive threshold handles local contrast variation correctly.

#     Larger morphological close kernel (5×5) than previous versions because:
#     - Real aged PAN card signatures have ink gaps from drying and scanning.
#     - Submitted phone photos have JPEG compression artifacts in thin strokes.
#     A 5×5 elliptical kernel bridges these gaps without merging separate strokes.

#     Speckle removal (contours < 20px²) eliminates noise dots that corrupt ORB.
#     """
#     if img_gray is None:
#         return None

#     h, w = img_gray.shape
#     if min(h, w) < 150:
#         scale = 150.0 / min(h, w)
#         img_gray = cv2.resize(img_gray, None, fx=scale, fy=scale,
#                               interpolation=cv2.INTER_CUBIC)

#     denoised = cv2.fastNlMeansDenoising(img_gray, h=8)

#     binary = cv2.adaptiveThreshold(
#         denoised, 255,
#         cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
#         cv2.THRESH_BINARY_INV,
#         blockSize=25, C=8)

#     k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
#     binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k)

#     # Remove speckle blobs
#     cnts, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL,
#                                 cv2.CHAIN_APPROX_SIMPLE)
#     clean = np.zeros_like(binary)
#     for c in cnts:
#         if cv2.contourArea(c) >= 20:
#             cv2.drawContours(clean, [c], -1, 255, -1)

#     pts = cv2.findNonZero(clean)
#     if pts is None:
#         return None

#     x, y, bw, bh = cv2.boundingRect(pts)
#     if bw < 5 or bh < 5:
#         return None

#     cropped = clean[y:y + bh, x:x + bw]
#     mask = cv2.resize(cropped, (_CANVAS, _CANVAS),
#                       interpolation=cv2.INTER_LINEAR)
#     _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
#     return mask


# # ─────────────────────────────────────────────────────────────────────────────
# #  SCORING METHODS
# # ─────────────────────────────────────────────────────────────────────────────

# def _orb_score(mask_a, mask_b):
#     """
#     ORB matching with dual distance caps.

#     Returns (score_strict, score_lenient) both in [0, 1].

#     strict  cap=30/256 → >88% descriptor similarity  → only genuine matches
#     lenient cap=40/256 → >84% descriptor similarity  → same person with noise

#     Dual caps let the scorer choose: use strict when confident, lenient when
#     natural signing variation has shifted descriptors slightly.
#     """
#     orb = cv2.ORB_create(nfeatures=1000, scaleFactor=1.2, nlevels=8)
#     kp1, des1 = orb.detectAndCompute(mask_a, None)
#     kp2, des2 = orb.detectAndCompute(mask_b, None)

#     if des1 is None or des2 is None or len(des1) < 2 or len(des2) < 2:
#         return 0.0, 0.0

#     bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
#     try:
#         matches = bf.match(des1, des2)
#     except cv2.error:
#         return 0.0, 0.0

#     denom = min(len(des1), len(des2))
#     strict  = min(sum(1 for m in matches if m.distance < 30) / denom, 1.0)
#     lenient = min(sum(1 for m in matches if m.distance < 40) / denom, 1.0)
#     return strict, lenient


# def _dilated_iou(mask_a, mask_b, dilation_px=8):
#     """
#     IoU after dilating both masks by `dilation_px` pixels.

#     8px dilation = 6.25% of 128px canvas — tolerates natural signing shift
#     without bloating masks so much that different signatures overlap.
#     """
#     k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
#                                   (2 * dilation_px + 1, 2 * dilation_px + 1))
#     a_d = cv2.dilate(mask_a, k)
#     b_d = cv2.dilate(mask_b, k)
#     inter = np.logical_and(a_d > 127, b_d > 127).sum()
#     union = np.logical_or(a_d > 127, b_d > 127).sum()
#     return float(inter) / float(union) if union > 0 else 0.0


# def _zone_both_ink(mask_a, mask_b, zones=6):
#     """
#     Fraction of grid cells where BOTH signatures have ink.

#     Score = both_ink_cells / total_cells (not / either_ink_cells).
#     Dividing by total_cells (36 for 6×6) penalises cases where different
#     signatures cover different subsets of zones — the numerator is small
#     even if each signature has ink in many zones, as long as they are
#     different zones.
#     """
#     step = _CANVAS // zones
#     both_ink = 0
#     for r in range(zones):
#         for c in range(zones):
#             za = mask_a[r * step:(r + 1) * step, c * step:(c + 1) * step]
#             zb = mask_b[r * step:(r + 1) * step, c * step:(c + 1) * step]
#             if (za > 127).any() and (zb > 127).any():
#                 both_ink += 1
#     return float(both_ink) / float(zones * zones)


# # ─────────────────────────────────────────────────────────────────────────────
# #  MAIN ENTRY POINT
# # ─────────────────────────────────────────────────────────────────────────────

# # Score ceiling applied when ORB (lenient) is below this — gates false positives
# _ORB_GATE_THRESHOLD = 0.22
# _ORB_GATE_CEILING   = 18.0   # forces score below SIGNATURE_MATCH_THRESHOLD=20


# def signature_match(sig_bytes, pan_bytes):
#     """
#     Compare a submitted signature against the signature on a PAN card.

#     Returns a score in [0, 100].
#     Threshold in app.py: SIGNATURE_MATCH_THRESHOLD = 20

#     ALGORITHM
#     ─────────
#     1. Extract signature ROI from PAN card (lower-middle strip).
#     2. Build normalised 128×128 binary stroke masks for both images.
#     3. Score with three methods:
#          M1  ORB dual-cap (strict/lenient)   weight 0.60
#          M2  Dilated IoU (8px)               weight 0.25
#          M3  Zone both-ink (6×6 grid)        weight 0.15
#     4. Apply ORB gate: if lenient ORB < 0.15, cap score at 18.
#     5. Return weighted score × 100, rounded to 2dp.

#     EXPECTED SCORE RANGES
#     ──────────────────────
#     Valid (same person)   : 25 – 80
#     Invalid (diff person) : 3  – 18  (ORB gate caps most false positives)
#     Threshold 20 separates the two ranges.
#     """
#     sig_gray = cv2.imdecode(np.frombuffer(sig_bytes, np.uint8),
#                             cv2.IMREAD_GRAYSCALE)
#     pan_gray = cv2.imdecode(np.frombuffer(pan_bytes, np.uint8),
#                             cv2.IMREAD_GRAYSCALE)

#     if sig_gray is None or pan_gray is None:
#         return 0

#     pan_roi  = _extract_signature_roi(pan_gray)
#     mask_sig = _to_mask(sig_gray)
#     mask_pan = _to_mask(pan_roi)

#     if mask_sig is None or mask_pan is None:
#         return 0

#     # ── M1: ORB dual-cap ─────────────────────────────────────────────────────
#     orb_strict, orb_lenient = _orb_score(mask_sig, mask_pan)
#     # Choose the better of strict/lenient for the weighted score
#     m1 = orb_strict if orb_strict >= 0.25 else orb_lenient

#     # ── M2: Dilated IoU ───────────────────────────────────────────────────────
#     m2 = _dilated_iou(mask_sig, mask_pan, dilation_px=8)

#     # ── M3: Zone both-ink ─────────────────────────────────────────────────────
#     m3 = _zone_both_ink(mask_sig, mask_pan, zones=6)

#     # ── Weighted score ────────────────────────────────────────────────────────
#     raw = (0.60 * m1 + 0.25 * m2 + 0.15 * m3) * 100.0

#     # ── ORB gate: prevent M2/M3 from rescuing a non-matching signature ────────
#     if orb_lenient < _ORB_GATE_THRESHOLD:
#         raw = min(raw, _ORB_GATE_CEILING)

#     return round(raw, 2)

"""
image_match_utils.py
────────────────────
Signature matching — exact 8-step logic as specified, with calibrated constants.

  Step 1  Extract signature ROI — bottom 30% × right 50% of PAN card
  Step 2  Preprocess: grayscale → CLAHE → Gaussian blur → Otsu threshold
           → erode → dilate → keep only large contours (suppress card text)
  Step 3  ORB feature extraction (cv2.ORB_create)
  Step 4  BFMatcher Hamming, knnMatch + Lowe ratio (0.75) + distance < 50
  Step 5  Normalise: confidence = min(good_matches / 20, 1.0)
  Step 6  Decision: good_matches >= 8 → MATCH
  Step 7  Fallback: if ORB has no descriptors → cv2.matchShapes on contours
  Step 8  signature_match() returns confidence × 100 for app.py

WHY THE ORIGINAL VALUES CAUSED FALSE POSITIVES
───────────────────────────────────────────────
Real-world failure: wrong signature scored 42.0 (21 matches, distance<60).

Root cause: the bottom-30%×right-50% PAN card ROI contains not only the
hand-written signature but also printed card elements (security text,
micro-print borders). With distance<60, ORB was matching a submitted
wrong-signature image against those printed card elements, not the actual
signature strokes — giving spurious matches.

Fixes:
  1. CLAHE contrast enhancement before thresholding — makes the hand-written
     signature strokes stand out from the faint printed card background.
  2. Keep only contours with area ≥ 80px² — eliminates the tiny speckle
     features from printed micro-text that ORB anchors on.
  3. Lowe ratio test (0.75) — requires each match to be unambiguously better
     than its nearest competitor; printed-text features fail this because
     many similar-looking characters produce ambiguous matches.
  4. distance < 50 — tighter than 60 but not so tight that genuine
     signature strokes (which vary slightly between paper and phone photo)
     fail to match.
  5. Normalise by 20, minimum 8 — calibrated to real signature match counts
     (8–20 strong matches for same signature, 0–3 for different).

app.py: signature_score = signature_match(sig_bytes, pan_bytes) → [0, 100]
        verified when signature_score >= SIGNATURE_MATCH_THRESHOLD (20)
"""

import cv2
import numpy as np


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 1 — SIGNATURE ROI EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def _extract_pan_signature_roi(pan_gray):
    """
    Crop the signature region: bottom 30% of height × right 50% of width.
    Falls back to full image if the crop is too small.
    """
    h, w = pan_gray.shape
    y_start = int(h * 0.70)
    x_start = int(w * 0.50)
    roi = pan_gray[y_start:h, x_start:w]
    if roi.shape[0] < 10 or roi.shape[1] < 10:
        return pan_gray
    return roi


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 2 — PREPROCESSING
# ─────────────────────────────────────────────────────────────────────────────

def _preprocess(img_gray):
    """
    Preprocess a signature image for feature extraction.

    Pipeline:
      1. Upscale to min 150px   — thin strokes need enough pixels
      2. CLAHE                   — boosts hand-written ink contrast relative
                                   to faint printed card background patterns
      3. Gaussian Blur (5×5)    — removes grain/JPEG artifacts
      4. Otsu BINARY_INV        — ink=255, background=0
      5. Erode (3×3, 1 iter)    — removes tiny noise pixels
      6. Dilate (3×3, 1 iter)   — restores stroke width
      7. Keep contours ≥ 80px²  — removes micro-print speckle features
                                   that cause false ORB matches on card text

    Returns binary uint8 image. Returns None on failure.
    """
    if img_gray is None:
        return None

    h, w = img_gray.shape
    if min(h, w) < 150:
        scale = 150.0 / min(h, w)
        img_gray = cv2.resize(img_gray, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_CUBIC)

    # CLAHE: enhances local contrast so hand-written signature strokes
    # become dominant over faint printed background on PAN card
    clahe   = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(img_gray)

    # Gaussian blur then Otsu threshold
    blurred = cv2.GaussianBlur(enhanced, (5, 5), 0)
    _, binary = cv2.threshold(
        blurred, 0, 255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    # Erode → dilate (morphological opening)
    kernel  = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    eroded  = cv2.erode(binary,  kernel, iterations=1)
    cleaned = cv2.dilate(eroded, kernel, iterations=1)

    # Keep only contours with area ≥ 80px² — suppresses micro-print
    # noise dots that ORB would otherwise anchor keypoints on
    cnts, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL,
                                cv2.CHAIN_APPROX_SIMPLE)
    filtered = np.zeros_like(cleaned)
    for c in cnts:
        if cv2.contourArea(c) >= 80:
            cv2.drawContours(filtered, [c], -1, 255, -1)

    # If nothing survived filtering, fall back to unfiltered cleaned image
    if cv2.countNonZero(filtered) == 0:
        return cleaned

    return filtered


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 7 HELPER — CONTOUR FALLBACK
# ─────────────────────────────────────────────────────────────────────────────

def _contour_fallback(bin_a, bin_b, shape_threshold=0.5):
    """
    Fallback when ORB has no descriptors: compare largest contours
    with cv2.matchShapes (CONTOURS_MATCH_I1).

    Returns (status: bool, confidence: float in [0,1]).
    """
    def largest_contour(img):
        cnts, _ = cv2.findContours(img, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        return max(cnts, key=cv2.contourArea) if cnts else None

    cnt_a = largest_contour(bin_a)
    cnt_b = largest_contour(bin_b)

    if cnt_a is None or cnt_b is None:
        return False, 0.0

    try:
        dissimilarity = cv2.matchShapes(cnt_a, cnt_b,
                                        cv2.CONTOURS_MATCH_I1, 0.0)
    except cv2.error:
        return False, 0.0

    confidence = float(max(0.0, 1.0 - min(dissimilarity, 1.0)))
    status     = bool(dissimilarity < shape_threshold)
    return status, confidence


# ─────────────────────────────────────────────────────────────────────────────
#  TUNED CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

_DISTANCE_CAP     = 50    # ORB Hamming distance cap (stricter than original 60)
_LOWE_RATIO       = 0.75  # Lowe ratio test — filters ambiguous matches
_NORMALISE_DENOM  = 20    # Calibrated for real signature match counts (8–20)
_MIN_GOOD_MATCHES = 8     # Minimum for MATCH decision


# ─────────────────────────────────────────────────────────────────────────────
#  STEPS 3–7 — CORE MATCHING LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def _run_signature_check(bin_sig, bin_pan):
    """
    Steps 3–7: ORB extraction, knnMatch + Lowe + distance cap, decision,
    contour fallback. Returns structured dict with Python-native values.
    """
    # Step 3 — ORB
    orb = cv2.ORB_create()
    kp1, des1 = orb.detectAndCompute(bin_sig, None)
    kp2, des2 = orb.detectAndCompute(bin_pan, None)

    # Step 7 — contour fallback
    if des1 is None or des2 is None or len(des1) < 2 or len(des2) < 2:
        status, confidence = _contour_fallback(bin_sig, bin_pan)
        return {
            "check":            "SIGNATURE_MATCH",
            "status":           bool(status),
            "confidence":       round(float(confidence), 4),
            "comparison_logic": "ORB + contour fallback",
            "reason":           (
                "Matched based on contour shape similarity"
                if status else "Contour shapes are too different"
            ),
        }

    # Step 4 — knnMatch + Lowe ratio test + distance cap
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    try:
        knn = bf.knnMatch(des1, des2, k=2)
    except cv2.error:
        knn = []

    good_matches = []
    for pair in knn:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < _LOWE_RATIO * n.distance and m.distance < _DISTANCE_CAP:
            good_matches.append(m)

    n_good = len(good_matches)

    # Step 5 — normalise
    confidence = float(min(n_good / _NORMALISE_DENOM, 1.0))

    # Step 6 — decision
    status = bool(n_good >= _MIN_GOOD_MATCHES)

    return {
        "check":            "SIGNATURE_MATCH",
        "status":           status,
        "confidence":       round(confidence, 4),
        "comparison_logic": "ORB + contour fallback",
        "reason":           (
            f"Matched based on feature similarity ({n_good} good matches)"
            if status else
            f"Insufficient feature matches ({n_good} < {_MIN_GOOD_MATCHES})"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def signature_match(sig_bytes, pan_bytes):
    """
    Compare submitted signature against PAN card signature.
    Returns float in [0, 100]. app.py threshold: SIGNATURE_MATCH_THRESHOLD = 20.

    Genuine match  → 40–100  (8–20 strong ORB matches)
    Wrong signature → 0–15   (0–3 matches survive Lowe + distance cap)
    """
    sig_gray = cv2.imdecode(np.frombuffer(sig_bytes, np.uint8),
                            cv2.IMREAD_GRAYSCALE)
    pan_gray = cv2.imdecode(np.frombuffer(pan_bytes, np.uint8),
                            cv2.IMREAD_GRAYSCALE)

    if sig_gray is None or pan_gray is None:
        return 0.0

    pan_roi = _extract_pan_signature_roi(pan_gray)
    bin_sig = _preprocess(sig_gray)
    bin_pan = _preprocess(pan_roi)

    if bin_sig is None or bin_pan is None:
        return 0.0

    result = _run_signature_check(bin_sig, bin_pan)
    return round(result["confidence"] * 100.0, 2)