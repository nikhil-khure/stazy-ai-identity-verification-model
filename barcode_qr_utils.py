import cv2
import numpy as np
from pyzbar.pyzbar import decode


def _try_decode(img):
    """Attempt to decode barcodes/QR codes from a single image variant."""
    try:
        codes = decode(img)
        if codes:
            return codes[0].data.decode("utf-8", errors="replace").strip()
    except Exception:
        pass
    return None


def decode_barcode(img_bytes):
    """
    Decode a barcode or QR code from the given image bytes.

    Multi-pass strategy to handle low-contrast, blurry, or small barcodes
    that a single decode call on the raw image would miss:

      Pass 1 - original colour image
      Pass 2 - grayscale
      Pass 3 - upscaled (2x) grayscale
      Pass 4 - adaptive-thresholded binary
      Pass 5 - inverted binary (handles dark-background barcodes)
      Pass 6 - sharpened grayscale
    """
    img = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Pass 1: original colour
    result = _try_decode(img)
    if result:
        return result

    # Pass 2: grayscale
    result = _try_decode(gray)
    if result:
        return result

    # Pass 3: upscaled grayscale (helps small barcodes)
    upscaled = cv2.resize(gray, None, fx=2.0, fy=2.0,
                          interpolation=cv2.INTER_CUBIC)
    result = _try_decode(upscaled)
    if result:
        return result

    # Pass 4: adaptive threshold (handles uneven lighting)
    adaptive = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 10
    )
    result = _try_decode(adaptive)
    if result:
        return result

    # Pass 5: inverted binary (dark background barcodes)
    result = _try_decode(cv2.bitwise_not(adaptive))
    if result:
        return result

    # Pass 6: sharpened grayscale (helps slightly blurry prints)
    kernel = np.array([[-1, -1, -1],
                       [-1,  9, -1],
                       [-1, -1, -1]])
    sharpened = cv2.filter2D(gray, -1, kernel)
    result = _try_decode(sharpened)
    if result:
        return result

    return None
