import sys, os
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")
from app.search.extractor import extract_products_from_url

products = extract_products_from_url(
    "https://www.amazon.in/deep-learning-laptop/s?k=deep+learning+laptop",
    category="laptop"
)
print(f"Got {len(products)} products")
for p in products[:8]:
    print(f"  {p.name[:70]}")
    print(f"  Price: ₹{p.price:,.0f}" if p.price else "  Price: N/A")
    print(f"  URL: {p.source_url[:70]}")
    print()
