"""Generate sample fee PDFs for tuition & PG businesses."""
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm


def make_pdf(path: str, title: str, lines: list[str]):
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 20)
    c.drawString(20 * mm, h - 30 * mm, title)
    c.setFont("Helvetica", 12)
    y = h - 50 * mm
    for line in lines:
        c.drawString(20 * mm, y, line)
        y -= 7 * mm
    c.save()
    print(f"Created {path}")


if __name__ == "__main__":
    assets = Path("/home/z/my-project/assets")
    assets.mkdir(parents=True, exist_ok=True)

    make_pdf(
        str(assets / "tuition_fees.pdf"),
        "Vidhya Tuition Centre — Fee Structure",
        [
            "Classes 6-10 (all subjects): Rs.1500/month",
            "Classes 11-12 (PCM/PCB): Rs.2500/month",
            "NEET / JEE Foundation: Rs.3500/month",
            "Weekend Crash Course: Rs.5000 (3 months)",
            "",
            "Batch Timings:",
            "  Weekday: 5 PM - 7 PM",
            "  Weekend: 10 AM - 12 PM",
            "",
            "Trial Class: FREE (1 session)",
            "Address: No.42, Gandhipuram, Coimbatore 641012",
            "Phone: +91 422 5555 555",
        ],
    )

    make_pdf(
        str(assets / "pg_fees.pdf"),
        "Shanthi Gents PG — Rent Structure",
        [
            "Sharing Room (2 sharing): Rs.6500/month",
            "Single Room: Rs.9500/month",
            "Deposit: 2 months (refundable)",
            "",
            "Amenities (all inclusive):",
            "  - 24/7 WiFi (100 Mbps)",
            "  - Air Conditioning",
            "  - 3 meals daily (veg + non-veg)",
            "  - Hot water 24/7",
            "  - Laundry service (weekly)",
            "  - 24/7 security",
            "",
            "Address: 3rd Floor, Crosscut Road, Gandhipuram, Coimbatore 641012",
            "Phone: +91 422 5555 556",
        ],
    )
    print("\nSample PDFs generated successfully.")
