import sys
import os
from PyQt5.QtGui import QImage
from PyQt5.QtCore import QRect

def main():
    img_path = r"..\..\.gemini\tmp\anki-gs3236208\images\clipboard-1777593268007.png"
    img = QImage(img_path)
    if img.isNull():
        print("Failed to load image")
        return
    
    out_dir = "assets/icons_sliced"
    os.makedirs(out_dir, exist_ok=True)
    
    top_offset = 65
    row_h = (559 - top_offset) / 4
    col_w = 1024 / 7
    
    size = 110 # crop size
    
    for r in range(4):
        for c in range(7):
            cx = c * col_w + col_w / 2
            cy = top_offset + r * row_h + row_h / 2
            
            # create rect
            rect = QRect(int(cx - size/2), int(cy - size/2), size, size)
            cropped = img.copy(rect)
            cropped.save(f"{out_dir}/icon_{r}_{c}.png")

if __name__ == "__main__":
    main()
