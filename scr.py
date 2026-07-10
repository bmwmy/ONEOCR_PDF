import io
import os
import re
import sys
import argparse
import fitz  # PyMuPDF (Option 2)
from PIL import Image
import oneocr
import unicodedata
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# قاموس تحويل الأرقام الشرقية (الهندية) إلى الأرقام القياسية (العربية)
EASTERN_TO_WESTERN = {
    '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
    '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9'
}

def convert_digits_to_western(text):
    """تحويل الأرقام الهندية/الشرقية إلى أرقام عربية قياسية."""
    return "".join(EASTERN_TO_WESTERN.get(char, char) for char in text)

def reverse_text_preserving_numbers_and_latin(text):
    """
    تقوم بعكس النص العربي فقط مع الحفاظ على الأرقام والنصوص اللاتينية 
    في اتجاهها الصحيح (من اليسار إلى اليمين) دون عكس أحرفها داخلياً.
    """
    text = convert_digits_to_western(text)
    parts = re.split(r'(\d+|[A-Za-z]+)', text)
    reversed_parts = parts[::-1]
    
    final_parts = []
    for part in reversed_parts:
        if re.match(r'^(\d+|[A-Za-z]+)$', part):
            final_parts.append(part)
        else:
            final_parts.append(part[::-1])
            
    return "".join(final_parts)

def clean_normalize_and_strip_diacritics(text):
    """
    1. Normalizes text to compatibility form (NFKC).
    2. Replaces non-standard Persian/Urdu Yeh (\u06cc) with standard Arabic Yeh (\u064a).
    3. Strips all Arabic diacritics (Harakat, Tashkeel, Shadda).
    4. Cleans control characters.
    """
    normalized = unicodedata.normalize('NFKC', text)
    
    # استبدال الياء غير القياسية (ی) بالياء العربية القياسية (ي) بنظام اليونيكود مباشرة
    normalized = normalized.replace('ی', 'ي').replace('ک','ك').replace(" فى "," في ")
    
    arabic_diacritics_pattern = re.compile(r'[\u064b-\u065f\u0670]')
    no_diacritics = arabic_diacritics_pattern.sub('', normalized)
    
    cleaned = "".join(
        c for c in no_diacritics 
        if unicodedata.category(c) != 'Cc'
    )
    return cleaned

def register_arabic_font():
    """تحديد وتسجيل خط يدعم اللغة العربية مثبت برمجياً في نظام ويندوز."""
    font_paths = [
        r"C:\Windows\Fonts\arial.ttf",      # Standard Arial
        r"C:\Windows\Fonts\tahoma.ttf",     # Standard Tahoma
        r"C:\Windows\Fonts\times.ttf"       # Times New Roman
    ]
    
    selected_font_path = None
    for path in font_paths:
        if os.path.exists(path):
            selected_font_path = path
            break
            
    if selected_font_path:
        pdfmetrics.registerFont(TTFont('ArialArabic', selected_font_path))
        print(f"[+] Successfully registered Arabic font from: {selected_font_path}")
    else:
        raise FileNotFoundError("[-] Could not find standard Arabic system fonts in Windows/Fonts.")

def render_word_group(words, can, text_obj, scale_x, scale_y, height_px):
    """تنظيف وعكس ورسم مجموعة كلمات كسطر واحد منسق أفقياً."""
    # ترتيب الكلمات من اليمين إلى اليسار (الاتجاه المنطقي للعربية)
    sorted_words = sorted(words, key=lambda w: w['bounding_rect']['x1'], reverse=True)

    logical_words = []
    for w in sorted_words:
        cleaned_w = clean_normalize_and_strip_diacritics(w['text'])
        if cleaned_w.strip():
            logical_words.append(cleaned_w)

    if not logical_words:
        return

    logical_line_text = " ".join(logical_words)
    reversed_line_text = reverse_text_preserving_numbers_and_latin(logical_line_text)

    x1_coords = [w['bounding_rect']['x1'] for w in sorted_words]
    x2_coords = [w['bounding_rect']['x2'] for w in sorted_words]
    y1_coords = [w['bounding_rect']['y1'] for w in sorted_words]
    y4_coords = [w['bounding_rect']['y4'] for w in sorted_words]

    line_left_x = min(x1_coords)
    line_right_x = max(x2_coords)
    line_bottom_y = max(y4_coords)

    word_heights = [(y4 - y1) * scale_y for y1, y4 in zip(y1_coords, y4_coords)]
    avg_height_pt = sum(word_heights) / len(word_heights)
    font_size = max(1.0, avg_height_pt * 0.9)

    x_pt = line_left_x * scale_x
    y_pt = (height_px - line_bottom_y) * scale_y

    physical_width_pt = (line_right_x - line_left_x) * scale_x
    rendered_width_pt = can.stringWidth(reversed_line_text, "ArialArabic", font_size)

    if rendered_width_pt > 0 and physical_width_pt > 0:
        horizontal_scale = (physical_width_pt / rendered_width_pt) * 100
        horizontal_scale = min(100.0, max(10.0, horizontal_scale))
    else:
        horizontal_scale = 100.0

    text_obj.setTextOrigin(x_pt, y_pt)
    text_obj.setFont("ArialArabic", font_size)
    text_obj.setHorizScale(horizontal_scale)
    text_obj.textOut(reversed_line_text)
    text_obj.setHorizScale(100.0)

def render_column_words(col_words, can, text_obj, scale_x, scale_y, height_px):
    """تجميع الكلمات المتراكمة داخل عمود معين وتجميعها سطراً بسطر بناءً على المحاذاة الرأسية."""
    if not col_words:
        return

    # ترتيب الكلمات داخل العمود من الأعلى لأسفل
    col_words_sorted = sorted(col_words, key=lambda w: (w['bounding_rect']['y1'] + w['bounding_rect']['y4']) / 2)

    lines_in_col = []
    for w in col_words_sorted:
        rect = w['bounding_rect']
        y1, y4 = rect['y1'], rect['y4']
        cy = (y1 + y4) / 2
        h = y4 - y1

        placed = False
        for col_line in lines_in_col:
            line_y1 = col_line['y1']
            line_y4 = col_line['y4']
            line_h = line_y4 - line_y1
            line_cy = (line_y1 + line_y4) / 2

            # إذا كانت المسافة الرأسية بين مركزي الكلمتين أقل من 60% من ارتفاع السطر، فهما في نفس السطر
            allowed_diff = min(h, line_h) * 0.6
            if abs(cy - line_cy) < allowed_diff:
                col_line['words'].append(w)
                col_line['y1'] = min(line_y1, y1)
                col_line['y4'] = max(line_y4, y4)
                placed = True
                break

        if not placed:
            lines_in_col.append({
                'y1': y1,
                'y4': y4,
                'words': [w]
            })

    # ترتيب السطور المستنتجة داخل العمود ورسمها
    sorted_col_lines = sorted(lines_in_col, key=lambda l: l['y1'])
    for col_line in sorted_col_lines:
        render_word_group(col_line['words'], can, text_obj, scale_x, scale_y, height_px)

def pdf_to_searchable_pdf(input_pdf_path, output_pdf_path, mode='visible', dpi=300):
    print(f"[*] Opening input PDF: {input_pdf_path}...")
    doc = fitz.open(input_pdf_path)
    
    register_arabic_font()
    
    print("[*] Initializing Microsoft OneOCR Engine...")
    try:
        ocr_engine = oneocr.OcrEngine()
    except Exception as e:
        print("\n[-] [ERROR] Failed to load OneOCR. Ensure your 3 system files are placed in:")
        print(r"C:\Users\<Your_Username>\.config\oneocr" + "\n")
        raise e

    print(f"[*] Processing {len(doc)} pages in '{mode}' mode...")
    can = canvas.Canvas(output_pdf_path)

    for page_idx in range(len(doc)):
        print(f" -> OCR on Page {page_idx + 1}/{len(doc)}...")
        page = doc[page_idx]
        
        pix = page.get_pixmap(dpi=dpi)
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        
        width_px, height_px = img.size
        width_pts, height_pts = page.rect.width, page.rect.height
        
        scale_x = width_pts / width_px
        scale_y = height_pts / height_px

        can.setPageSize((width_pts, height_pts))

        if mode == 'visible':
            img_reader = ImageReader(img)
            can.drawImage(img_reader, 0, 0, width=width_pts, height=height_pts)

        ocr_result = ocr_engine.recognize_pil(img)

        # 1. تجميع كافة الكلمات المتواجدة بالصفحة لتحليل الإسقاط الرأسي
        all_words = []
        for line in ocr_result.get('lines', []):
            for word in line.get('words', []):
                all_words.append(word)

        # 2. قياس المساحات الرأسية الفارغة لتحديد فواصل الأعمدة (Gutters)
        margin_threshold = int(width_px * 0.05)  # تجاهل الـ 5% من حواف الصفحة كفواصل
        occupancy = [0] * width_px
        for w in all_words:
            rect = w['bounding_rect']
            x1 = int(max(0, min(rect['x1'], rect['x4'])))
            x2 = int(min(width_px - 1, max(rect['x2'], rect['x3'])))
            if x1 < x2:
                for x in range(x1, x2 + 1):
                    occupancy[x] += 1

        total_lines = len(ocr_result.get('lines', []))
        # عتبة الحساسية الديناميكية لتجاوز العناوين الممتدة فوق العمودين (8% من مجموع السطور)
        threshold = max(1, int(total_lines * 0.08))

        gaps = []
        in_gap = False
        gap_start = 0
        for x in range(width_px):
            if occupancy[x] <= threshold:
                if not in_gap:
                    gap_start = x
                    in_gap = True
            else:
                if in_gap:
                    gap_end = x - 1
                    gaps.append((gap_start, gap_end))
                    in_gap = False
        if in_gap:
            gaps.append((gap_start, width_px - 1))

        # الفاصل الرأسي الحقيقي يجب ألا يقل عرضه عن 1.5% من عرض الصفحة
        min_gutter_width = max(15, int(width_px * 0.015))
        valid_gutters = []
        for start, end in gaps:
            width = end - start + 1
            if width >= min_gutter_width:
                if start > margin_threshold and end < (width_px - margin_threshold):
                    valid_gutters.append((start, end))

        text_obj = can.beginText()
        text_obj.setTextRenderMode(3)

        if not valid_gutters:
            # تدفق الصفحة العادي (سطر تلو الآخر) في حال عدم العثور على أعمدة
            for line in ocr_result.get('lines', []):
                words = line.get('words', [])
                if words:
                    render_word_group(words, can, text_obj, scale_x, scale_y, height_px)
        else:
            # تخطيط أعمدة متعددة
            valid_gutters = sorted(valid_gutters, key=lambda g: g[0])
            split_points = [(g_start + g_end) / 2 for g_start, g_end in valid_gutters]
            num_columns = len(split_points) + 1
            
            accumulated_words_by_column = [[] for _ in range(num_columns)]
            
            # ترتيب السطور الأصلية من الأعلى للأسفل لتسهيل المعالجة المرحلية (Banding)
            sorted_ocr_lines = sorted(
                ocr_result.get('lines', []), 
                key=lambda l: sum((w['bounding_rect']['y1'] + w['bounding_rect']['y4'])/2 for w in l.get('words', [])) / len(l.get('words', [])) if l.get('words', []) else 0
            )

            for line in sorted_ocr_lines:
                words_in_line = line.get('words', [])
                if not words_in_line:
                    continue

                # التحقق هل هذا السطر يمر بالكامل من فوق أحد الفواصل الرأسية (Spanning Line)
                is_spanning = False
                for g_start, g_end in valid_gutters:
                    has_left = any(w['bounding_rect']['x2'] < g_start for w in words_in_line)
                    has_right = any(w['bounding_rect']['x1'] > g_end for w in words_in_line)
                    if has_left and has_right:
                        is_spanning = True
                        break

                if is_spanning:
                    # عند مصادفة سطر ممتد بالكامل (مثل العنوان الرئيسي)، نقوم بتفريغ ورسم الأعمدة المتراكمة أولاً
                    for col_idx in range(num_columns - 1, -1, -1):
                        render_column_words(accumulated_words_by_column[col_idx], can, text_obj, scale_x, scale_y, height_px)
                        accumulated_words_by_column[col_idx] = []
                    
                    # ثم نرسم السطر الممتد كطبقة مستقلة
                    render_word_group(words_in_line, can, text_obj, scale_x, scale_y, height_px)
                else:
                    # توزيع الكلمات الاعتيادية للعمود الذي يتبع له مركز كل كلمة
                    for w in words_in_line:
                        cx = (w['bounding_rect']['x1'] + w['bounding_rect']['x2']) / 2
                        col_idx = 0
                        for split in split_points:
                            if cx > split:
                                col_idx += 1
                            else:
                                break
                        accumulated_words_by_column[col_idx].append(w)

            # رسم وتفريغ بقية الأعمدة المتراكمة في نهاية الصفحة (من اليمين إلى اليسار للغة العربية)
            for col_idx in range(num_columns - 1, -1, -1):
                render_column_words(accumulated_words_by_column[col_idx], can, text_obj, scale_x, scale_y, height_px)

        can.drawText(text_obj)
        can.showPage()

    can.save()
    print(f"[+] Success! Searchable PDF generated and saved to: {output_pdf_path}")

def main():
    parser = argparse.ArgumentParser(
        description="أداة تحويل ملفات الـ PDF الممسوحة ضوئياً إلى ملفات قابلة للبحث باستخدام محرك Microsoft OneOCR المحلي.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument(
        '-i', '--input',
        required=True,
        help="مسار ملف الـ PDF المدخل المراد معالجته بالـ OCR.\nمثال: -i \"scanned_document.pdf\""
    )
    
    parser.add_argument(
        '-o', '--mode',
        choices=['visible', 'invisible'],
        default='visible',
        help=(
            "نوع الملف المخرج المولد:\n"
            "  visible   -> دمج طبقة النصوص الشفافة مباشرة فوق الصور الأصلية المستخرجة (الوضع الافتراضي).\n"
            "  invisible -> توليد طبقة النصوص الشفافة فقط بملف مستقل دون أي صور، لدمجها لاحقاً مع البي دي إف الأصلي.\n"
            "مثال: -o invisible"
        )
    )
    
    parser.add_argument(
        '-out', '--output',
        help="مسار حفظ الملف الناتج (اختياري). إذا لم يحدد، سيتم الحفظ تلقائياً في نفس المجلد مع لاحقة '_searchable' أو '_text_layer'."
    )

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[-] [ERROR] Input file '{args.input}' does not exist.")
        sys.exit(1)

    if not args.output:
        base, ext = os.path.splitext(args.input)
        suffix = "_searchable" if args.mode == 'visible' else "_text_layer"
        args.output = f"{base}{suffix}{ext}"

    try:
        pdf_to_searchable_pdf(args.input, args.output, mode=args.mode)
    except Exception as e:
        print(f"\n[-] [CRITICAL ERROR] Execution failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()