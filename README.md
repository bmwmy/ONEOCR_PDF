# ONEOCR_PDF
MS ONEOCR OCR Model with PDF capabilities based on Python
____________________________________________________________________
To use you need to place 3 files from recent Windows 11 versions of Snipping Tool. The easiest way to get them is through https://store.rg-adguard.net, insert "https://apps.microsoft.com/detail/9mz95kl8mr0l" in the search box and download the most recent "Microsoft.ScreenSketch" "msixbundle" file. Then rename it to .zip and extract it. Extract the "SnippingToolApp" "msix" file for your architecture (x64 or ARM64) again after also renaming it to .zip, and the files should be in the "SnippingTool" folder.

oneocr.dll
oneocr.onemodel
onnxruntime.dll
These files should be placed in the C:/Users/your_user_folder/.config/oneocr folder.
____________________________________________________________________

Pre-requisites:
pip install pymupdf oneocr reportlab Pillow
____________________________________________________________________

for usage type:
python scr.py --help
____________________________________________________________________

يدعم اللغة العربية وبدقة تفوق أغلب محركات التعرف الضوئي الموجودة الآن...
