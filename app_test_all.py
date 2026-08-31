"""AppTest headless run for all 9 Streamlit pages (app + pages/*)."""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = [os.path.join(ROOT, p) for p in
         ["app.py", "pages/1_Migration.py", "pages/2_Sales_Revenue.py",
          "pages/3_NPS_CS.py", "pages/4_Price_Changes.py",
          "pages/5_Retention_V2V_V2C.py", "pages/6_New_to_Category.py",
          "pages/7_Definitions.py", "pages/8_Insights.py"]]

fails = 0
for p in PAGES:
    at = AppTest.from_file(p, default_timeout=300)
    at.run()
    if at.exception:
        fails += 1
        print(f"✗ {p}: EXCEPTION")
        for e in at.exception:
            print("   ", e.value)
    elif at.error:
        fails += 1
        print(f"✗ {p}: ERROR {at.error[0].value}")
    else:
        print(f"✓ {p}: no exception/error")
print("FAIL" if fails else "ALL PAGES PASS")
sys.exit(1 if fails else 0)
