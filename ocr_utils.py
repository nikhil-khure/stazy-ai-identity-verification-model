# import pytesseract
# import cv2
# import numpy as np
# import re
# from difflib import SequenceMatcher

# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# # ─────────────────────────────────────────────────────────────────────────────
# #  IMAGE PRE-PROCESSING HELPERS
# # ─────────────────────────────────────────────────────────────────────────────

# def _upscale_if_small(img, min_dim=1000):
#     """
#     Upscale images whose shortest dimension is below `min_dim` pixels.
#     Tesseract accuracy drops sharply below ~300 DPI; most phone photos of cards
#     are fine, but scanned thumbnails or web-fetched images can be too small.
#     min_dim raised to 1000 from previous 900 for better digit recognition.
#     """
#     h, w = img.shape[:2]
#     if min(h, w) < min_dim:
#         scale = min_dim / min(h, w)
#         img = cv2.resize(img, None, fx=scale, fy=scale,
#                          interpolation=cv2.INTER_CUBIC)
#     return img


# def _deskew(gray):
#     """
#     Correct small card rotation using Hough-line angle estimation.
#     Only corrects angles within ±15° to avoid over-rotating clearly upright cards.
#     """
#     edges = cv2.Canny(gray, 50, 150, apertureSize=3)
#     lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
#     if lines is None:
#         return gray
#     angles = []
#     for line in lines[:20]:
#         rho, theta = line[0]
#         angle = np.degrees(theta) - 90
#         if abs(angle) < 15:
#             angles.append(angle)
#     if not angles:
#         return gray
#     median_angle = float(np.median(angles))
#     if abs(median_angle) < 0.5:
#         return gray
#     h, w = gray.shape
#     M = cv2.getRotationMatrix2D((w / 2, h / 2), median_angle, 1.0)
#     return cv2.warpAffine(gray, M, (w, h),
#                           flags=cv2.INTER_CUBIC,
#                           borderMode=cv2.BORDER_REPLICATE)


# def _crop_barcode_zone(img_bgr):
#     """
#     Return a cropped region covering the bottom 40% of the card — the area
#     where barcodes and the PRN/ID number printed beneath them typically live.
#     Used as an extra OCR pass specifically aimed at recovering barcode-adjacent text.
#     """
#     h = img_bgr.shape[0]
#     return img_bgr[int(h * 0.60):, :]


# def _preprocess_for_ocr(img_bgr, doc_type="generic"):
#     """
#     Build a list of preprocessed image candidates for multi-pass OCR.

#     Each candidate targets a different failure mode:
#       1. Adaptive threshold  — uneven lighting / shadows
#       2. Otsu binarization   — clean uniform backgrounds
#       3. CLAHE gray          — faded / low-contrast prints
#       4. Sharpen + adaptive  — blurry phone captures
#       5. Morphological open  — removes thin speckles that confuse digit OCR
#       6. (pan only) Bilateral filter + Otsu — preserves fine PAN card strokes

#     For college_id we also append a tightly-cropped barcode-zone variant for
#     each of the above so that the PRN digits beneath the barcode get a dedicated
#     high-resolution pass.
#     """
#     candidates = []

#     img_bgr = _upscale_if_small(img_bgr, min_dim=1000)
#     gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
#     gray = _deskew(gray)

#     # ── candidate 1: adaptive threshold ──────────────────────────────────────
#     adaptive = cv2.adaptiveThreshold(
#         gray, 255,
#         cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
#         cv2.THRESH_BINARY, 31, 10)
#     candidates.append(("full", adaptive))

#     # ── candidate 2: Otsu after mild blur ────────────────────────────────────
#     blur = cv2.GaussianBlur(gray, (3, 3), 0)
#     _, otsu = cv2.threshold(blur, 0, 255,
#                             cv2.THRESH_BINARY + cv2.THRESH_OTSU)
#     candidates.append(("full", otsu))

#     # ── candidate 3: CLAHE-enhanced gray ─────────────────────────────────────
#     clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
#     enhanced = clahe.apply(gray)
#     candidates.append(("full", enhanced))

#     # ── candidate 4: sharpen + adaptive ──────────────────────────────────────
#     kernel = np.array([[-1, -1, -1],
#                        [-1,  9, -1],
#                        [-1, -1, -1]])
#     sharpened = cv2.filter2D(gray, -1, kernel)
#     sharp_adapt = cv2.adaptiveThreshold(
#         sharpened, 255,
#         cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
#         cv2.THRESH_BINARY, 31, 8)
#     candidates.append(("full", sharp_adapt))

#     # ── candidate 5: morphological open (removes speckle noise) ─────────────
#     # Opening = erosion then dilation; removes isolated white dots that OCR
#     # mistakes for punctuation, which corrupts number sequences.
#     morph_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
#     opened = cv2.morphologyEx(otsu, cv2.MORPH_OPEN, morph_kernel)
#     candidates.append(("full", opened))

#     # ── candidate 6 (PAN only): bilateral filter + Otsu ──────────────────────
#     if doc_type == "pan":
#         denoised = cv2.bilateralFilter(gray, 9, 75, 75)
#         _, pan_bin = cv2.threshold(denoised, 0, 255,
#                                    cv2.THRESH_BINARY + cv2.THRESH_OTSU)
#         candidates.append(("full", pan_bin))

#     # ── extra barcode-zone crops (college_id only) ───────────────────────────
#     # The PRN / ID number sits directly below the barcode in the lower portion
#     # of the card. Running OCR on a tight crop of that zone — at high res —
#     # dramatically improves digit extraction for the 1-in-6 cards that fail.
#     if doc_type == "college_id":
#         zone_bgr = _crop_barcode_zone(img_bgr)
#         if zone_bgr.shape[0] >= 20 and zone_bgr.shape[1] >= 20:
#             # Further upscale the zone so small digits are large enough
#             zone_bgr = cv2.resize(zone_bgr, None, fx=2.0, fy=2.0,
#                                   interpolation=cv2.INTER_CUBIC)
#             zone_gray = cv2.cvtColor(zone_bgr, cv2.COLOR_BGR2GRAY)

#             zone_adapt = cv2.adaptiveThreshold(
#                 zone_gray, 255,
#                 cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
#                 cv2.THRESH_BINARY, 31, 10)
#             candidates.append(("zone", zone_adapt))

#             _, zone_otsu = cv2.threshold(
#                 cv2.GaussianBlur(zone_gray, (3, 3), 0),
#                 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
#             candidates.append(("zone", zone_otsu))

#             zone_clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
#             candidates.append(("zone", zone_clahe.apply(zone_gray)))

#     return candidates


# # ─────────────────────────────────────────────────────────────────────────────
# #  OCR EXTRACTION
# # ─────────────────────────────────────────────────────────────────────────────

# def _run_tesseract(img, config=""):
#     """Run Tesseract safely; return upper-cased text or empty string on error."""
#     try:
#         return pytesseract.image_to_string(img, config=config).upper()
#     except Exception:
#         return ""


# def _merge_ocr_results(texts):
#     """
#     Union-merge OCR results from all preprocessed passes.
#     Preserves first-encounter order; deduplicates identical lines.
#     This means text recovered by only one preprocessor is still retained.
#     """
#     seen = set()
#     merged = []
#     for text in texts:
#         for line in text.splitlines():
#             norm_line = re.sub(r'\s+', ' ', line).strip()
#             if norm_line and norm_line not in seen:
#                 seen.add(norm_line)
#                 merged.append(norm_line)
#     return "\n".join(merged)


# # PSM modes used per pass type:
# #   PSM 6  – assume single uniform block of text  (best for printed cards)
# #   PSM 11 – sparse text, no particular order     (catches isolated numbers/labels)
# #   PSM 7  – single text line                     (used on barcode-zone crops)
# _FULL_CONFIGS  = ["--psm 6 --oem 3", "--psm 11 --oem 3"]
# _ZONE_CONFIGS  = ["--psm 6 --oem 3", "--psm 7 --oem 3", "--psm 11 --oem 3"]


# def extract_text(img_bytes, doc_type="generic"):
#     """
#     Multi-pass OCR extraction with document-type-aware preprocessing.

#     doc_type: "college_id" | "pan" | "generic"

#     For college_id: runs full-card passes + dedicated barcode-zone passes so
#     the PRN / ID digits printed beneath the barcode are reliably extracted even
#     when the card layout puts them in a small, low-contrast area.

#     For pan: includes bilateral-filter pass to preserve thin PAN card strokes.

#     All results are merged into one string so downstream matchers see everything.
#     """
#     img = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
#     if img is None:
#         return ""

#     candidates = _preprocess_for_ocr(img, doc_type=doc_type)

#     texts = []
#     for (kind, cand) in candidates:
#         configs = _ZONE_CONFIGS if kind == "zone" else _FULL_CONFIGS
#         for cfg in configs:
#             t = _run_tesseract(cand, cfg)
#             if t.strip():
#                 texts.append(t)

#     if not texts:
#         # Absolute last resort — plain grayscale, default Tesseract settings
#         gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
#         texts.append(_run_tesseract(gray, "--psm 6 --oem 3"))

#     return _merge_ocr_results(texts)


# # ─────────────────────────────────────────────────────────────────────────────
# #  PAN CARD TEXT VALIDATION
# # ─────────────────────────────────────────────────────────────────────────────

# # Canonical phrases that must appear on every legitimate PAN card.
# # Presence of these is used as an additional authenticity signal in the
# # owner-verification pipeline (see app.py).
# PAN_REQUIRED_PHRASES = [
#     "INCOME TAX DEPARTMENT",
#     "GOVT OF INDIA",          # "." may be missing in OCR
#     "GOVT. OF INDIA",
#     "GOVERNMENT OF INDIA",
# ]

# # Shorter sub-tokens that are individually sufficient if the full phrase is broken
# # across lines by OCR:
# PAN_PHRASE_TOKENS = [
#     ["INCOME", "TAX", "DEPARTMENT"],
#     ["GOVT", "INDIA"],
#     ["GOVERNMENT", "INDIA"],
# ]


# def check_pan_header(ocr_text):
#     """
#     Validate that the OCR text contains the mandatory PAN card header phrases:
#       "INCOME TAX DEPARTMENT" and "GOVT. OF INDIA"

#     Strategy:
#       1. Try direct substring match for the full phrase (fastest).
#       2. Fall back to token-set match (all tokens present anywhere in text)
#          to handle OCR splitting a phrase across lines or inserting noise chars.

#     Returns:
#       (income_tax_found: bool, govt_india_found: bool)

#     Both booleans being True is a strong signal that the image is a genuine
#     Indian PAN card, not a photo of something else or a tampered document.
#     """
#     upper = re.sub(r'[^A-Z0-9 ]', ' ', ocr_text.upper())
#     upper = re.sub(r'\s+', ' ', upper).strip()

#     def _phrase_found(phrase, tokens):
#         # Direct match first
#         phrase_norm = re.sub(r'[^A-Z0-9 ]', ' ', phrase.upper())
#         phrase_norm = re.sub(r'\s+', ' ', phrase_norm).strip()
#         if phrase_norm in upper:
#             return True
#         # Token-based fallback
#         return all(tok in upper for tok in tokens)

#     income_tax_found = (
#         _phrase_found("INCOME TAX DEPARTMENT", ["INCOME", "TAX", "DEPARTMENT"])
#     )

#     govt_india_found = (
#         _phrase_found("GOVT OF INDIA",   ["GOVT", "INDIA"]) or
#         _phrase_found("GOVT. OF INDIA",  ["GOVT", "INDIA"]) or
#         _phrase_found("GOVERNMENT OF INDIA", ["GOVERNMENT", "INDIA"])
#     )

#     return income_tax_found, govt_india_found


# # ─────────────────────────────────────────────────────────────────────────────
# #  TEXT NORMALIZATION & MATCHING
# # ─────────────────────────────────────────────────────────────────────────────

# def normalize(text):
#     """Remove non-alphanumeric chars, collapse whitespace, uppercase."""
#     cleaned = re.sub(r'[^A-Z0-9 ]', ' ', text.upper())
#     return re.sub(r'\s+', ' ', cleaned).strip()


# def _token_similarity(a_norm, b_norm):
#     """
#     Hybrid similarity: maximum of three independent metrics.

#     1. Character-level SequenceMatcher ratio
#        Good at catching single-character OCR substitutions (e.g. 0 vs O).

#     2. Jaccard similarity on word tokens
#        Good when OCR produces the same words but in a slightly different order
#        or with extra noise words inserted.

#     3. Token overlap ratio (intersection / shorter set)
#        Good when the OCR line contains only a subset of the full college name
#        (e.g. OCR reads "AMRAVATI UNIVERSITY" for "SHRI SANT GADGE BABA AMRAVATI
#        UNIVERSITY") — the overlap ratio rewards partial matches proportionally.
#        Multiplied by 0.9 to slightly penalise pure-subset matches vs full matches.

#     Taking the maximum means whichever metric is most favourable for a given
#     pair of strings wins — no single metric can eliminate a true match.
#     """
#     char_ratio = SequenceMatcher(None, a_norm, b_norm).ratio()

#     a_tokens = set(a_norm.split())
#     b_tokens = set(b_norm.split())
#     if not a_tokens or not b_tokens:
#         return char_ratio

#     intersection = a_tokens & b_tokens
#     union = a_tokens | b_tokens
#     jaccard = len(intersection) / len(union)

#     shorter = min(len(a_tokens), len(b_tokens))
#     overlap_ratio = (len(intersection) / shorter) if shorter > 0 else 0.0

#     return max(char_ratio, jaccard, overlap_ratio * 0.9)


# def _sliding_window_match(ocr_text, input_norm, window=3):
#     """
#     Evaluate similarity over sliding windows of 1-to-`window` consecutive OCR lines.

#     College names frequently wrap across multiple lines in OCR output because:
#       • The card prints the name in a tall, narrow text box
#       • Tesseract PSM 6 treats each visual line as a separate OCR line
#     Example: "SHRI SANT\nGADGE BABA\nAMRAVATI UNIVERSITY" → best window = 3

#     We concatenate adjacent lines and score the combined string, keeping the
#     combination + score that beats single-line comparison.
#     """
#     lines = [normalize(l) for l in ocr_text.splitlines() if len(normalize(l)) >= 3]
#     best_score = 0.0
#     best_combined = ""
#     for i in range(len(lines)):
#         for w in range(1, window + 1):
#             combined = " ".join(lines[i:i + w])
#             if not combined:
#                 continue
#             score = _token_similarity(combined, input_norm)
#             if score > best_score:
#                 best_score = score
#                 best_combined = combined
#     return best_combined, best_score


# def best_text_match(ocr_text, input_text):
#     """
#     Find the OCR text (single line or multi-line combination) that best matches
#     `input_text`, using hybrid token + character similarity with sliding window.

#     Returns: (best_matching_line: str, confidence: float 0–1)
#     """
#     input_norm = normalize(input_text)
#     if not input_norm:
#         return "", 0.0
#     best_line, best_score = _sliding_window_match(ocr_text, input_norm, window=3)
#     return best_line.strip(), round(best_score, 3)


# # ─────────────────────────────────────────────────────────────────────────────
# #  EXACT NUMBER / PRN / PAN MATCHING
# # ─────────────────────────────────────────────────────────────────────────────

# def _clean_number(text):
#     """Strip everything except letters and digits (removes OCR noise chars)."""
#     return re.sub(r'[^A-Z0-9]', '', text.upper())


# def exact_number(ocr_text, value):
#     """
#     Check whether `value` appears in `ocr_text`.

#     Three-tier tolerance:
#       1. Exact substring match on raw (uppercase) text.
#       2. Alphanumeric-stripped substring match (ignores spaces/dashes/dots).
#       3. Single-character mismatch tolerance for codes ≥ 8 alphanumeric chars
#          (handles one OCR substitution, e.g. 0→O or 1→I in a PAN number).
#     """
#     if not value:
#         return False

#     value_clean = _clean_number(value)
#     ocr_clean   = _clean_number(ocr_text)

#     if value.upper() in ocr_text.upper():
#         return True

#     if value_clean and value_clean in ocr_clean:
#         return True

#     if len(value_clean) >= 8:
#         vlen = len(value_clean)
#         for i in range(len(ocr_clean) - vlen + 1):
#             window = ocr_clean[i:i + vlen]
#             mismatches = sum(a != b for a, b in zip(window, value_clean))
#             if mismatches <= 1:
#                 return True

#     return False


# # ─────────────────────────────────────────────────────────────────────────────
# #  STUDENT CODE / BARCODE OCR EXTRACTION
# # ─────────────────────────────────────────────────────────────────────────────

# def _normalize_barcode_str(s):
#     """
#     Normalize for OCR-confusion-tolerant barcode comparison.
#     Maps characters that Tesseract commonly confuses with each other:
#       O → 0,  I → 1,  S → 5,  B → 8,  Z → 2
#     """
#     s = re.sub(r'[^A-Z0-9]', '', s.upper())
#     return s.translate(str.maketrans({'O': '0', 'I': '1',
#                                       'S': '5', 'B': '8', 'Z': '2'}))


# def extract_student_code(ocr_text):
#     """
#     Extract the numeric student ID code from OCR text of a College ID card.

#     The code is the number printed directly below (or beside) the barcode.
#     Multiple pattern strategies are tried in order of specificity:

#       P1 – Explicit prefix "S", "ST", or "SC" followed by 5-9 digits.
#            Most reliable: the barcode payload typically starts with one of
#            these prefixes and the same value is printed on the card.

#       P2 – Bare "S" prefix immediately followed by 5-9 digits.
#            Covers cards that print just "S123456" without the extra letter.

#       P3 – Any standalone 6-9 digit number.
#            Last resort for cards that print the raw number without any prefix.
#            6-digit minimum avoids matching short noise numbers; 9-digit maximum
#            avoids matching phone numbers or other long numeric fields.

#     The digit portion only is returned (prefix stripped) so it can be compared
#     directly against the barcode-decoded payload via barcode_matches_ocr().
#     """
#     cleaned = re.sub(r'[^A-Z0-9]', ' ', ocr_text.upper())
#     cleaned = re.sub(r'\s+', ' ', cleaned).strip()

#     # P1 – S/ST/SC + optional space + 5-9 digits
#     m = re.search(r'\bS[TC]?\s*(\d{5,9})\b', cleaned)
#     if m:
#         return m.group(1)

#     # P2 – bare S then digits
#     m = re.search(r'\bS(\d{5,9})\b', cleaned)
#     if m:
#         return m.group(1)

#     # P3 – standalone 6-9 digit number
#     nums = re.findall(r'\b(\d{6,9})\b', cleaned)
#     return nums[0] if nums else None


# def barcode_matches_ocr(barcode_value, student_code_from_ocr):
#     """
#     Compare the decoded barcode payload against the OCR-extracted student code.

#     Match strategies (tried in order):
#       1. Exact match after stripping common leading prefixes (S, ST, SC).
#          This is the primary path; avoids the original bug of stripping every
#          occurrence of the letter S anywhere in the barcode string.

#       2. OCR-confusion-normalised match (O↔0, I↔1, S↔5, B↔8, Z↔2 on both
#          sides). Handles the case where one digit was misread by OCR or by
#          the barcode scanner on a worn/dirty card.

#       3. Suffix match: the OCR code appears at the trailing end of a longer
#          barcode payload. Some cards encode a year-prefix (e.g. "2024123456")
#          but only print the bare ID ("123456") beneath the barcode.

#     Returns True only when at least one strategy succeeds.
#     """
#     if barcode_value is None or student_code_from_ocr is None:
#         return False

#     # Strip only the leading student-code prefix from the barcode payload
#     barcode_stripped = re.sub(r'^(SC|ST|S)', '',
#                                barcode_value.upper().strip())
#     barcode_stripped = re.sub(r'[^A-Z0-9]', '', barcode_stripped)

#     ocr_stripped = re.sub(r'[^A-Z0-9]', '',
#                            student_code_from_ocr.upper().strip())

#     # Strategy 1: exact
#     if barcode_stripped == ocr_stripped:
#         return True

#     # Strategy 2: confusion-normalised exact
#     if _normalize_barcode_str(barcode_stripped) == _normalize_barcode_str(ocr_stripped):
#         return True

#     # Strategy 3: suffix / subset match (barcode longer than OCR code)
#     if len(barcode_stripped) > len(ocr_stripped) >= 5:
#         if barcode_stripped.endswith(ocr_stripped):
#             return True
#         if _normalize_barcode_str(barcode_stripped).endswith(
#                 _normalize_barcode_str(ocr_stripped)):
#             return True

#     return False


# def dynamic_threshold(text):
#     return 0.55  # tuned for student IDs
import pytesseract
import cv2
import numpy as np
import re
from difflib import SequenceMatcher

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# ─────────────────────────────────────────────────────────────────────────────
#  IMAGE PRE-PROCESSING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _upscale_if_small(img, min_dim=1000):
    """
    Upscale images whose shortest dimension is below `min_dim` pixels.
    Tesseract accuracy drops sharply below ~300 DPI; most phone photos of cards
    are fine, but scanned thumbnails or web-fetched images can be too small.
    min_dim raised to 1000 from previous 900 for better digit recognition.
    """
    h, w = img.shape[:2]
    if min(h, w) < min_dim:
        scale = min_dim / min(h, w)
        img = cv2.resize(img, None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_CUBIC)
    return img


def _deskew(gray):
    """
    Correct small card rotation using Hough-line angle estimation.
    Only corrects angles within ±15° to avoid over-rotating clearly upright cards.
    """
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
    if lines is None:
        return gray
    angles = []
    for line in lines[:20]:
        rho, theta = line[0]
        angle = np.degrees(theta) - 90
        if abs(angle) < 15:
            angles.append(angle)
    if not angles:
        return gray
    median_angle = float(np.median(angles))
    if abs(median_angle) < 0.5:
        return gray
    h, w = gray.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), median_angle, 1.0)
    return cv2.warpAffine(gray, M, (w, h),
                          flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def _crop_barcode_zone(img_bgr):
    """
    Return a cropped region covering the bottom 40% of the card — the area
    where barcodes and the PRN/ID number printed beneath them typically live.
    Used as an extra OCR pass specifically aimed at recovering barcode-adjacent text.
    """
    h = img_bgr.shape[0]
    return img_bgr[int(h * 0.60):, :]


def _preprocess_for_ocr(img_bgr, doc_type="generic"):
    """
    Build a list of preprocessed image candidates for multi-pass OCR.

    Each candidate targets a different failure mode:
      1. Adaptive threshold  — uneven lighting / shadows
      2. Otsu binarization   — clean uniform backgrounds
      3. CLAHE gray          — faded / low-contrast prints
      4. Sharpen + adaptive  — blurry phone captures
      5. Morphological open  — removes thin speckles that confuse digit OCR
      6. (pan only) Bilateral filter + Otsu — preserves fine PAN card strokes

    For college_id we also append a tightly-cropped barcode-zone variant for
    each of the above so that the PRN digits beneath the barcode get a dedicated
    high-resolution pass.
    """
    candidates = []

    img_bgr = _upscale_if_small(img_bgr, min_dim=1000)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = _deskew(gray)

    # ── candidate 1: adaptive threshold ──────────────────────────────────────
    adaptive = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 10)
    candidates.append(("full", adaptive))

    # ── candidate 2: Otsu after mild blur ────────────────────────────────────
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, otsu = cv2.threshold(blur, 0, 255,
                            cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    candidates.append(("full", otsu))

    # ── candidate 3: CLAHE-enhanced gray ─────────────────────────────────────
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    candidates.append(("full", enhanced))

    # ── candidate 4: sharpen + adaptive ──────────────────────────────────────
    kernel = np.array([[-1, -1, -1],
                       [-1,  9, -1],
                       [-1, -1, -1]])
    sharpened = cv2.filter2D(gray, -1, kernel)
    sharp_adapt = cv2.adaptiveThreshold(
        sharpened, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 8)
    candidates.append(("full", sharp_adapt))

    # ── candidate 5: morphological open (removes speckle noise) ─────────────
    # Opening = erosion then dilation; removes isolated white dots that OCR
    # mistakes for punctuation, which corrupts number sequences.
    morph_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    opened = cv2.morphologyEx(otsu, cv2.MORPH_OPEN, morph_kernel)
    candidates.append(("full", opened))

    # ── candidate 6 (PAN only): bilateral filter + Otsu ──────────────────────
    if doc_type == "pan":
        denoised = cv2.bilateralFilter(gray, 9, 75, 75)
        _, pan_bin = cv2.threshold(denoised, 0, 255,
                                   cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        candidates.append(("full", pan_bin))

    # ── extra barcode-zone crops (college_id only) ───────────────────────────
    # The PRN / ID number sits directly below the barcode in the lower portion
    # of the card. Running OCR on a tight crop of that zone — at high res —
    # dramatically improves digit extraction for the 1-in-6 cards that fail.
    if doc_type == "college_id":
        zone_bgr = _crop_barcode_zone(img_bgr)
        if zone_bgr.shape[0] >= 20 and zone_bgr.shape[1] >= 20:
            # Further upscale the zone so small digits are large enough
            zone_bgr = cv2.resize(zone_bgr, None, fx=2.0, fy=2.0,
                                  interpolation=cv2.INTER_CUBIC)
            zone_gray = cv2.cvtColor(zone_bgr, cv2.COLOR_BGR2GRAY)

            zone_adapt = cv2.adaptiveThreshold(
                zone_gray, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 31, 10)
            candidates.append(("zone", zone_adapt))

            _, zone_otsu = cv2.threshold(
                cv2.GaussianBlur(zone_gray, (3, 3), 0),
                0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            candidates.append(("zone", zone_otsu))

            zone_clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
            candidates.append(("zone", zone_clahe.apply(zone_gray)))

    return candidates


# ─────────────────────────────────────────────────────────────────────────────
#  OCR EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def _run_tesseract(img, config=""):
    """Run Tesseract safely; return upper-cased text or empty string on error."""
    try:
        return pytesseract.image_to_string(img, config=config).upper()
    except Exception:
        return ""


def _merge_ocr_results(texts):
    """
    Union-merge OCR results from all preprocessed passes.
    Preserves first-encounter order; deduplicates identical lines.
    This means text recovered by only one preprocessor is still retained.
    """
    seen = set()
    merged = []
    for text in texts:
        for line in text.splitlines():
            norm_line = re.sub(r'\s+', ' ', line).strip()
            if norm_line and norm_line not in seen:
                seen.add(norm_line)
                merged.append(norm_line)
    return "\n".join(merged)


# PSM modes used per pass type:
#   PSM 6  – assume single uniform block of text  (best for printed cards)
#   PSM 11 – sparse text, no particular order     (catches isolated numbers/labels)
#   PSM 7  – single text line                     (used on barcode-zone crops)
_FULL_CONFIGS  = ["--psm 6 --oem 3", "--psm 11 --oem 3"]
_ZONE_CONFIGS  = ["--psm 6 --oem 3", "--psm 7 --oem 3", "--psm 11 --oem 3"]


def extract_text(img_bytes, doc_type="generic"):
    """
    Multi-pass OCR extraction with document-type-aware preprocessing.

    doc_type: "college_id" | "pan" | "generic"

    For college_id: runs full-card passes + dedicated barcode-zone passes so
    the PRN / ID digits printed beneath the barcode are reliably extracted even
    when the card layout puts them in a small, low-contrast area.

    For pan: includes bilateral-filter pass to preserve thin PAN card strokes.

    All results are merged into one string so downstream matchers see everything.
    """
    img = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return ""

    candidates = _preprocess_for_ocr(img, doc_type=doc_type)

    texts = []
    for (kind, cand) in candidates:
        configs = _ZONE_CONFIGS if kind == "zone" else _FULL_CONFIGS
        for cfg in configs:
            t = _run_tesseract(cand, cfg)
            if t.strip():
                texts.append(t)

    if not texts:
        # Absolute last resort — plain grayscale, default Tesseract settings
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        texts.append(_run_tesseract(gray, "--psm 6 --oem 3"))

    return _merge_ocr_results(texts)


# ─────────────────────────────────────────────────────────────────────────────
#  PAN CARD TEXT VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

# Canonical phrases that must appear on every legitimate PAN card.
# Presence of these is used as an additional authenticity signal in the
# owner-verification pipeline (see app.py).
PAN_REQUIRED_PHRASES = [
    "INCOME TAX DEPARTMENT",
    "GOVT OF INDIA",          # "." may be missing in OCR
    "GOVT. OF INDIA",
    "GOVERNMENT OF INDIA",
]

# Shorter sub-tokens that are individually sufficient if the full phrase is broken
# across lines by OCR:
PAN_PHRASE_TOKENS = [
    ["INCOME", "TAX", "DEPARTMENT"],
    ["GOVT", "INDIA"],
    ["GOVERNMENT", "INDIA"],
]


def check_pan_header(ocr_text):
    """
    Validate that the OCR text contains the mandatory PAN card header phrases:
      "INCOME TAX DEPARTMENT" and "GOVT. OF INDIA"

    Strategy:
      1. Try direct substring match for the full phrase (fastest).
      2. Fall back to token-set match (all tokens present anywhere in text)
         to handle OCR splitting a phrase across lines or inserting noise chars.

    Returns:
      (income_tax_found: bool, govt_india_found: bool)

    Both booleans being True is a strong signal that the image is a genuine
    Indian PAN card, not a photo of something else or a tampered document.
    """
    upper = re.sub(r'[^A-Z0-9 ]', ' ', ocr_text.upper())
    upper = re.sub(r'\s+', ' ', upper).strip()

    def _phrase_found(phrase, tokens):
        # Direct match first
        phrase_norm = re.sub(r'[^A-Z0-9 ]', ' ', phrase.upper())
        phrase_norm = re.sub(r'\s+', ' ', phrase_norm).strip()
        if phrase_norm in upper:
            return True
        # Token-based fallback
        return all(tok in upper for tok in tokens)

    income_tax_found = (
        _phrase_found("INCOME TAX DEPARTMENT", ["INCOME", "TAX", "DEPARTMENT"])
    )

    govt_india_found = (
        _phrase_found("GOVT OF INDIA",   ["GOVT", "INDIA"]) or
        _phrase_found("GOVT. OF INDIA",  ["GOVT", "INDIA"]) or
        _phrase_found("GOVERNMENT OF INDIA", ["GOVERNMENT", "INDIA"])
    )

    return income_tax_found, govt_india_found


# ─────────────────────────────────────────────────────────────────────────────
#  TEXT NORMALIZATION & MATCHING
# ─────────────────────────────────────────────────────────────────────────────

def normalize(text):
    """Remove non-alphanumeric chars, collapse whitespace, uppercase."""
    cleaned = re.sub(r'[^A-Z0-9 ]', ' ', text.upper())
    return re.sub(r'\s+', ' ', cleaned).strip()


def _token_similarity(a_norm, b_norm):
    """
    Hybrid similarity: WEIGHTED AVERAGE of char-level and token-level scores.

    WHY weighted average instead of max():
    The previous max() implementation had a critical flaw: SequenceMatcher
    char_ratio finds long common *substrings* at character level and can score
    high (0.72+) even when every word token is completely different.
    Example: OCR="MIRGTSBEG SANA YSING CHALIDMARS" vs actual="MOHITSING
    SANJAYSING CHAUDHARI" — char_ratio=0.721 because SANA/YSING/CHALIDMARS
    are substrings of SANJAYSING/CHAUDHARI, but token intersection = 0 (zero
    shared words).  max() blindly picks 0.721 → false positive.

    Fix: weight the score 40% char + 60% token so zero token overlap
    pulls the final score well below any reasonable threshold even when
    char_ratio is misleadingly high.

    Metrics:
      char_ratio   : SequenceMatcher character-level ratio (handles single-char
                     OCR substitutions like 0→O within a word).
      token_score  : max(jaccard, overlap*0.9) — rewards shared whole words.
                     Jaccard handles extra noise words; overlap handles subset
                     matches (OCR reads part of a multi-word college name).

    Weights: 40% char, 60% token.
      Real match with minor OCR noise → both scores high → final high.
      OCR garbage with lucky substrings → char high, token 0 → final ~0.28.
      College name subset match → token overlap fires → final acceptable.
    """
    char_ratio = SequenceMatcher(None, a_norm, b_norm).ratio()

    a_tokens = set(a_norm.split())
    b_tokens = set(b_norm.split())
    if not a_tokens or not b_tokens:
        return char_ratio

    intersection = a_tokens & b_tokens
    union        = a_tokens | b_tokens
    jaccard      = len(intersection) / len(union)

    shorter      = min(len(a_tokens), len(b_tokens))
    overlap_ratio = (len(intersection) / shorter) if shorter > 0 else 0.0
    token_score  = max(jaccard, overlap_ratio * 0.9)

    # Weighted fusion:
    #   Case A — char_ratio is very high (>= 0.85): the two strings are nearly
    #     identical character-for-character.  This happens when OCR correctly
    #     reads the name but splits a compound Indian name with a spurious space
    #     (e.g. "SANJAYSING" → "SANJAY SING").  In this case tokens differ but
    #     the strings are genuinely the same name, so we trust char_ratio more
    #     heavily (70%) and let token_score play a smaller role (30%).
    #
    #   Case B — char_ratio < 0.85: strings differ enough that we need both
    #     signals.  Token overlap (60%) is the primary gate — zero shared words
    #     pulls the score well below any threshold even when char_ratio is
    #     misleadingly high due to common substrings (e.g. "SANA" inside
    #     "SANJAYSING").  char_ratio (40%) handles intra-word OCR noise.
    if char_ratio >= 0.85:
        return 0.70 * char_ratio + 0.30 * token_score
    return 0.40 * char_ratio + 0.60 * token_score


def _sliding_window_match(ocr_text, input_norm, window=3):
    """
    Evaluate similarity over sliding windows of 1-to-`window` consecutive OCR lines.

    College names frequently wrap across multiple lines in OCR output because:
      • The card prints the name in a tall, narrow text box
      • Tesseract PSM 6 treats each visual line as a separate OCR line
    Example: "SHRI SANT\nGADGE BABA\nAMRAVATI UNIVERSITY" → best window = 3

    We concatenate adjacent lines and score the combined string, keeping the
    combination + score that beats single-line comparison.
    """
    lines = [normalize(l) for l in ocr_text.splitlines() if len(normalize(l)) >= 3]
    best_score = 0.0
    best_combined = ""
    for i in range(len(lines)):
        for w in range(1, window + 1):
            combined = " ".join(lines[i:i + w])
            if not combined:
                continue
            score = _token_similarity(combined, input_norm)
            if score > best_score:
                best_score = score
                best_combined = combined
    return best_combined, best_score


def best_text_match(ocr_text, input_text):
    """
    Find the OCR text (single line or multi-line combination) that best matches
    `input_text`, using hybrid token + character similarity with sliding window.

    Returns: (best_matching_line: str, confidence: float 0–1)
    """
    input_norm = normalize(input_text)
    if not input_norm:
        return "", 0.0
    best_line, best_score = _sliding_window_match(ocr_text, input_norm, window=3)
    return best_line.strip(), round(best_score, 3)


# ─────────────────────────────────────────────────────────────────────────────
#  EXACT NUMBER / PRN / PAN MATCHING
# ─────────────────────────────────────────────────────────────────────────────

def _clean_number(text):
    """Strip everything except letters and digits (removes OCR noise chars)."""
    return re.sub(r'[^A-Z0-9]', '', text.upper())


def exact_number(ocr_text, value):
    """
    Check whether `value` appears in `ocr_text`.

    Three-tier tolerance:
      1. Exact substring match on raw (uppercase) text.
      2. Alphanumeric-stripped substring match (ignores spaces/dashes/dots).
      3. Single-character mismatch tolerance for codes ≥ 8 alphanumeric chars
         (handles one OCR substitution, e.g. 0→O or 1→I in a PAN number).
    """
    if not value:
        return False

    value_clean = _clean_number(value)
    ocr_clean   = _clean_number(ocr_text)

    if value.upper() in ocr_text.upper():
        return True

    if value_clean and value_clean in ocr_clean:
        return True

    if len(value_clean) >= 8:
        vlen = len(value_clean)
        for i in range(len(ocr_clean) - vlen + 1):
            window = ocr_clean[i:i + vlen]
            mismatches = sum(a != b for a, b in zip(window, value_clean))
            if mismatches <= 1:
                return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
#  STUDENT CODE / BARCODE OCR EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_barcode_str(s):
    """
    Normalize for OCR-confusion-tolerant barcode comparison.
    Maps characters that Tesseract commonly confuses with each other:
      O → 0,  I → 1,  S → 5,  B → 8,  Z → 2
    """
    s = re.sub(r'[^A-Z0-9]', '', s.upper())
    return s.translate(str.maketrans({'O': '0', 'I': '1',
                                      'S': '5', 'B': '8', 'Z': '2'}))


def extract_student_code(ocr_text):
    """
    Extract the numeric student ID code from OCR text of a College ID card.

    The code is the number printed directly below (or beside) the barcode.
    Multiple pattern strategies are tried in order of specificity:

      P1 – Explicit prefix "S", "ST", or "SC" followed by 5-9 digits.
           Most reliable: the barcode payload typically starts with one of
           these prefixes and the same value is printed on the card.

      P2 – Bare "S" prefix immediately followed by 5-9 digits.
           Covers cards that print just "S123456" without the extra letter.

      P3 – Any standalone 6-9 digit number.
           Last resort for cards that print the raw number without any prefix.
           6-digit minimum avoids matching short noise numbers; 9-digit maximum
           avoids matching phone numbers or other long numeric fields.

    The digit portion only is returned (prefix stripped) so it can be compared
    directly against the barcode-decoded payload via barcode_matches_ocr().
    """
    cleaned = re.sub(r'[^A-Z0-9]', ' ', ocr_text.upper())
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # P1 – S/ST/SC + optional space + 5-9 digits
    m = re.search(r'\bS[TC]?\s*(\d{5,9})\b', cleaned)
    if m:
        return m.group(1)

    # P2 – bare S then digits
    m = re.search(r'\bS(\d{5,9})\b', cleaned)
    if m:
        return m.group(1)

    # P3 – standalone 6-9 digit number
    nums = re.findall(r'\b(\d{6,9})\b', cleaned)
    return nums[0] if nums else None


def barcode_matches_ocr(barcode_value, student_code_from_ocr):
    """
    Compare the decoded barcode payload against the OCR-extracted student code.

    Match strategies (tried in order):
      1. Exact match after stripping common leading prefixes (S, ST, SC).
         This is the primary path; avoids the original bug of stripping every
         occurrence of the letter S anywhere in the barcode string.

      2. OCR-confusion-normalised match (O↔0, I↔1, S↔5, B↔8, Z↔2 on both
         sides). Handles the case where one digit was misread by OCR or by
         the barcode scanner on a worn/dirty card.

      3. Suffix match: the OCR code appears at the trailing end of a longer
         barcode payload. Some cards encode a year-prefix (e.g. "2024123456")
         but only print the bare ID ("123456") beneath the barcode.

    Returns True only when at least one strategy succeeds.
    """
    if barcode_value is None or student_code_from_ocr is None:
        return False

    # Strip only the leading student-code prefix from the barcode payload
    barcode_stripped = re.sub(r'^(SC|ST|S)', '',
                               barcode_value.upper().strip())
    barcode_stripped = re.sub(r'[^A-Z0-9]', '', barcode_stripped)

    ocr_stripped = re.sub(r'[^A-Z0-9]', '',
                           student_code_from_ocr.upper().strip())

    # Strategy 1: exact
    if barcode_stripped == ocr_stripped:
        return True

    # Strategy 2: confusion-normalised exact
    if _normalize_barcode_str(barcode_stripped) == _normalize_barcode_str(ocr_stripped):
        return True

    # Strategy 3: suffix / subset match (barcode longer than OCR code)
    if len(barcode_stripped) > len(ocr_stripped) >= 5:
        if barcode_stripped.endswith(ocr_stripped):
            return True
        if _normalize_barcode_str(barcode_stripped).endswith(
                _normalize_barcode_str(ocr_stripped)):
            return True

    return False


def dynamic_threshold(text):
    return 0.55  # tuned for student IDs