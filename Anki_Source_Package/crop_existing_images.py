import os
import sys
from PIL import Image

# Add current workspace directory to sys.path to import local modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import storage_paths

def is_background_pixel(pixel):
    if len(pixel) == 4:
        r, g, b, a = pixel
        if a < 15: # transparent
            return True
    else:
        r, g, b = pixel[:3]
    # Check if pixel is dark grey/black (matching typical dark backgrounds)
    return r < 35 and g < 35 and b < 35

def crop_image(img_path):
    try:
        img = Image.open(img_path)
        w, h = img.size
        if w <= 10 or h <= 10:
            return None
            
        pixels = img.load()
        
        def row_is_bg(y):
            non_bg = sum(not is_background_pixel(pixels[x, y]) for x in range(w))
            return non_bg == 0

        def col_is_bg(x, y_start, y_end):
            non_bg = sum(not is_background_pixel(pixels[x, y]) for y in range(y_start, y_end + 1))
            return non_bg == 0

        # Check top-to-bottom borders
        top = 0
        while top < h:
            if not row_is_bg(top):
                break
            top += 1
            
        bottom = h - 1
        while bottom >= top:
            if not row_is_bg(bottom):
                break
            bottom -= 1
            
        # Check left-to-right borders
        left = 0
        while left < w:
            if not col_is_bg(left, top, bottom):
                break
            left += 1
            
        right = w - 1
        while right >= left:
            if not col_is_bg(right, top, bottom):
                break
            right -= 1
            
        if left > right or top > bottom:
            return None # entirely background
            
        # Add 10px padding gap around content
        pad = 10
        left_padded = max(0, left - pad)
        top_padded = max(0, top - pad)
        right_padded = min(w - 1, right + pad)
        bottom_padded = min(h - 1, bottom + pad)

        # If no borders are cropped, skip
        if left_padded == 0 and right_padded == w - 1 and top_padded == 0 and bottom_padded == h - 1:
            return None
            
        cropped_img = img.crop((left_padded, top_padded, right_padded + 1, bottom_padded + 1))
        cropped_img.save(img_path, "PNG")
        return (w, h), cropped_img.size
    except Exception as e:
        print(f"Error cropping {img_path}: {e}")
        return None

def main():
    # Resolve the active images directory using storage paths
    from storage_paths import resolve_asset_path
    
    # Try resolving 'images/' or check F:/Anki occulation/images directly
    images_dir = resolve_asset_path("images")
    if not os.path.isdir(images_dir):
        images_dir = r"F:\Anki occulation\images"
        
    print(f"Target images directory: {images_dir}")
    if not os.path.exists(images_dir):
        print(f"Directory {images_dir} does not exist!")
        return
        
    files = [f for f in os.listdir(images_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    print(f"Found {len(files)} images to scan.\n")
    
    cropped_count = 0
    for idx, filename in enumerate(files, 1):
        filepath = os.path.join(images_dir, filename)
        res = crop_image(filepath)
        if res:
            orig_sz, new_sz = res
            print(f"[{idx}/{len(files)}] Cropped {filename}: {orig_sz[0]}x{orig_sz[1]} -> {new_sz[0]}x{new_sz[1]}")
            cropped_count += 1
            
    print(f"\nScan complete! Cropped {cropped_count} out of {len(files)} images.")

if __name__ == "__main__":
    main()
