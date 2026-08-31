import fitz
import storage_paths
import os

storage_paths.apply_mission_archive()
pdf_path = storage_paths.resolve_asset_path("pdfs/Number_System_Type-_11.pdf")
print("PDF Path:", pdf_path)

doc = fitz.open(pdf_path)
for page_num in range(min(len(doc), 3)):
    page = doc[page_num]
    pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
    out_path = f"c:\\Users\\Digvijay\\Desktop\\Anki gs3236208\\page_{page_num}.png"
    pix.save(out_path)
    print(f"Saved Page {page_num} to {out_path}")
doc.close()
