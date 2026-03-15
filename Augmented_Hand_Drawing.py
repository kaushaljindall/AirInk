import cv2 as cv
import numpy as np
import time
import os
import HandDetectionModule as htm

try:
    import pytesseract
    from PIL import Image
    pytesseract.pytesseract.tesseract_cmd = r'E:\Programs\Tesseract-OCR\tesseract.exe'
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("pytesseract/Pillow not found. Run: pip install pytesseract pillow")

##################
BrushThickness = 18
EraserThickness = 100
##################

# ── OCR helper ──────────────────────────────────────────────────────────────
def recognize_letter(canvas):
    """Returns a single uppercase letter string, or '' if nothing detected."""
    if not OCR_AVAILABLE:
        return "?"
    try:
        gray = cv.cvtColor(canvas, cv.COLOR_BGR2GRAY)
        pts  = cv.findNonZero(gray)
        if pts is None:
            return ""

        bx, by, bw, bh = cv.boundingRect(pts)
        pad = 40
        x1 = max(0, bx - pad);  y1 = max(0, by - pad)
        x2 = min(canvas.shape[1], bx + bw + pad)
        y2 = min(canvas.shape[0], by + bh + pad)
        roi = gray[y1:y2, x1:x2]

        scale = max(1.0, 280.0 / max(roi.shape))
        roi = cv.resize(roi, None, fx=scale, fy=scale, interpolation=cv.INTER_CUBIC)
        _, roi = cv.threshold(roi, 30, 255, cv.THRESH_BINARY)
        roi = cv.bitwise_not(roi)
        roi = cv.copyMakeBorder(roi, 30, 30, 30, 30, cv.BORDER_CONSTANT, value=255)

        pil_img = Image.fromarray(roi)
        result = pytesseract.image_to_string(
            pil_img,
            config='--psm 10 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        ).strip()
        return result[0] if result else ""
    except Exception as e:
        print(f"OCR error: {e}")
        return ""

# ── Camera setup ────────────────────────────────────────────────────────────
capture = cv.VideoCapture(0)
capture.set(3, 1280)
capture.set(4, 720)

ret, testFrame = capture.read()
if not ret or testFrame is None:
    print("ERROR: Cannot open camera!")
    capture.release()
    exit()

frameH, frameW = testFrame.shape[:2]
headerH  = 125
wordBoxH = 110   # height of the word display box at bottom
print(f"Camera: {frameW}x{frameH}")

# ── Load header images ───────────────────────────────────────────────────────
folderpath = "Header"
mylist = sorted(os.listdir(folderpath))
overlayList = []
for imgPath in mylist:
    img = cv.imread(os.path.join(folderpath, imgPath))
    if img is not None:
        img = cv.resize(img, (frameW, headerH))
        overlayList.append(img)

if not overlayList:
    print("ERROR: No header images found!")
    capture.release()
    exit()

colors = [
    (156, 118, 237),  # Purple
    (255,   0,   0),  # Blue
    (  0, 255,   0),  # Green
    (  0,   0,   0),  # Eraser
]
sc = frameW / 1280.0
zones = [
    (int(250*sc), int(450*sc)),
    (int(550*sc), int(750*sc)),
    (int(800*sc), int(950*sc)),
    (int(1050*sc), int(1200*sc)),
]

header    = overlayList[0]
drawColor = colors[0]
xp, yp   = 0, 0

detector = htm.handDetector(detectionCon=0.85)
canvas   = np.zeros((frameH, frameW, 3), np.uint8)
preTime  = time.time()

# ── Word builder state ───────────────────────────────────────────────────────
word_buffer          = []    # list of (letter, color) tuples
last_recognized_time = 0
RECOGNIZE_COOLDOWN   = 1.5

# Flash feedback when a letter is recognized
flash_letter  = ""
flash_color   = (255, 255, 255)
flash_timer   = 0
FLASH_DURATION = 0.8

print("\n── AirInk ───────────────────────────────────────")
print("  ☝  Index finger          →  Draw letter")
print("  ✌  Index + Middle        →  Select colour (go to top bar)")
print("  🖐  All 5 fingers         →  Recognize letter & add to word")
print("  SPACE key                →  Add space between words")
print("  BACKSPACE key            →  Delete last letter")
print("  C key                    →  Clear entire word")
print("  Q key                    →  Quit")
print("──────────────────────────────────────────────\n")

# ── Main loop ────────────────────────────────────────────────────────────────
while True:
    ret, frame = capture.read()
    if not ret or frame is None:
        continue

    frame = cv.flip(frame, 1)
    frame = detector.findHands(frame)
    lmList = detector.findPosition(frame, draw=False)

    if len(lmList) != 0:
        x1, y1 = lmList[8][1:]
        x2, y2 = lmList[12][1:]
        fingers = detector.fingersUp()

        # ── 🖐 ALL 5 FINGERS → Recognize ─────────────────────────────────
        if all(f == 1 for f in fingers):
            now = time.time()
            if now - last_recognized_time > RECOGNIZE_COOLDOWN:
                last_recognized_time = now
                letter = recognize_letter(canvas)
                if letter:
                    word_buffer.append((letter, drawColor))
                    flash_letter = letter
                    flash_color  = drawColor
                    flash_timer  = time.time()
                    full_word = "".join(l for l, c in word_buffer)
                    print(f"  + '{letter}' → word so far: \"{full_word}\"")
                canvas[:] = 0   # clear canvas for next letter
                xp, yp = 0, 0

        # ── ✌ TWO FINGERS → Select colour ────────────────────────────────
        elif fingers[1] and fingers[2]:
            if y1 < headerH:
                for i, (zs, ze) in enumerate(zones):
                    if zs < x1 < ze:
                        header    = overlayList[i]
                        drawColor = colors[i]
                        break
            cv.rectangle(frame, (x1, y1 - 20), (x2, y2 + 20), drawColor, -1)
            xp, yp = x1, y1

        # ── ☝ ONE FINGER → Draw ───────────────────────────────────────────
        elif fingers[1] and not fingers[2]:
            cv.circle(frame, (x1, y1), 8, drawColor, cv.FILLED)
            if xp == 0 and yp == 0:
                xp, yp = x1, y1
            thick = EraserThickness if drawColor == (0, 0, 0) else BrushThickness
            cv.line(frame,  (xp, yp), (x1, y1), drawColor, thick)
            cv.line(canvas, (xp, yp), (x1, y1), drawColor, thick)
            xp, yp = x1, y1

        else:
            xp, yp = 0, 0

    # ── Blend drawing canvas ─────────────────────────────────────────────────
    grayCanvas   = cv.cvtColor(canvas, cv.COLOR_BGR2GRAY)
    _, canvasInv = cv.threshold(grayCanvas, 50, 255, cv.THRESH_BINARY_INV)
    canvasInv    = cv.cvtColor(canvasInv, cv.COLOR_GRAY2BGR)
    frame = cv.bitwise_and(frame, canvasInv)
    frame = cv.bitwise_or(frame, canvas)

    # ── Header bar ───────────────────────────────────────────────────────────
    frame[0:headerH, 0:frameW] = header

    # ── Word display box (bottom strip) ─────────────────────────────────────
    # Dark semi-transparent background
    word_y_start = frameH - wordBoxH
    overlay = frame.copy()
    cv.rectangle(overlay, (0, word_y_start), (frameW, frameH), (20, 20, 20), -1)
    cv.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

    # Draw each letter in its own colour side-by side
    if word_buffer:
        # Measure total word width to center it
        font       = cv.FONT_HERSHEY_SIMPLEX
        font_scale = 2.2
        thickness  = 5
        total_w    = 0
        char_sizes = []
        for ltr, col in word_buffer:
            (tw, th), _ = cv.getTextSize(ltr, font, font_scale, thickness)
            char_sizes.append((tw, th))
            total_w += tw + 8   # 8px spacing between letters
        total_w -= 8

        cx = (frameW - total_w) // 2
        cy = word_y_start + wordBoxH // 2 + char_sizes[0][1] // 2

        for (ltr, col), (tw, th) in zip(word_buffer, char_sizes):
            # Shadow
            cv.putText(frame, ltr, (cx + 2, cy + 2), font, font_scale, (0,0,0), thickness + 3)
            # Coloured letter
            cv.putText(frame, ltr, (cx, cy), font, font_scale, col, thickness)
            cx += tw + 8
    else:
        cv.putText(frame, "Draw a letter, then open all 5 fingers",
                   (20, word_y_start + wordBoxH // 2 + 8),
                   cv.FONT_HERSHEY_PLAIN, 1.6, (160, 160, 160), 1)

    # Divider line above word box
    cv.line(frame, (0, word_y_start), (frameW, word_y_start), (80, 80, 80), 2)

    # ── Flash: big letter pop-up when freshly recognized ─────────────────────
    if flash_letter and (time.time() - flash_timer) < FLASH_DURATION:
        alpha = 1.0 - (time.time() - flash_timer) / FLASH_DURATION   # fade out
        fsize = 7
        fthick = 12
        (tw, th), _ = cv.getTextSize(flash_letter, cv.FONT_HERSHEY_SIMPLEX, fsize, fthick)
        fx = (frameW - tw) // 2
        fy = (frameH - wordBoxH + headerH) // 2 + th // 2
        # We approximate fade by darkening color
        col = tuple(int(c * alpha) for c in flash_color)
        cv.putText(frame, flash_letter, (fx + 5, fy + 5),
                   cv.FONT_HERSHEY_SIMPLEX, fsize, (0, 0, 0), fthick + 4)
        cv.putText(frame, flash_letter, (fx, fy),
                   cv.FONT_HERSHEY_SIMPLEX, fsize, col, fthick)

    # ── FPS & shortcut hint ───────────────────────────────────────────────────
    curTime = time.time()
    fps = 1 / max(curTime - preTime, 1e-5)
    preTime = curTime
    cv.putText(frame, f"FPS {int(fps)}", (frameW - 110, headerH + 30),
               cv.FONT_HERSHEY_PLAIN, 1.8, (255, 0, 255), 2)
    cv.putText(frame, "SPACE=space  BKSP=delete  C=clear  Q=quit",
               (10, word_y_start - 8),
               cv.FONT_HERSHEY_PLAIN, 1.2, (200, 200, 200), 1)

    cv.imshow("AirInk", frame)

    # ── Key handling ─────────────────────────────────────────────────────────
    key = cv.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key == ord('c'):
        word_buffer.clear()
        canvas[:] = 0
        print("  → Word cleared")
    elif key == 32:   # SPACE
        word_buffer.append((' ', (255, 255, 255)))
        print("  → Space added")
    elif key == 8:    # BACKSPACE
        if word_buffer:
            removed = word_buffer.pop()
            print(f"  → Removed '{removed[0]}'")

capture.release()
cv.destroyAllWindows()
