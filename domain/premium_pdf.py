# -*- coding: utf-8 -*-
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import io

def generate_monthly_pdf_report(insights: dict, month: str) -> bytes:
    """Generates a premium PDF report."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    elements.append(Paragraph(f"Raport Wydatków: {month}", styles['Title']))
    elements.append(Spacer(1, 12))

    # Summary
    data = [
        ["Statystyka", "Wartość"],
        ["Liczba faktur", str(insights['count'])],
        ["Suma Brutto", f"{insights['total']:.2f} PLN"],
        ["Ulubiony Dostawca", insights['top_vendor'][0]],
        ["Największy wydatek", f"{insights['biggest']['amount']:.2f} PLN ({insights['biggest']['company']})"]
    ]
    
    t = Table(data, colWidths=[150, 300])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 24))

    # Categories
    elements.append(Paragraph("Wydatki wg kategorii", styles['Heading2']))
    cat_data = [["Kategoria", "Kwota"]]
    for cat, val in insights['categories']:
        cat_data.append([cat, f"{val:.2f} PLN"])
    
    ct = Table(cat_data, colWidths=[150, 300])
    ct.setStyle(TableStyle([
        ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ('BOX', (0, 0), (-1, -1), 0.25, colors.black),
    ]))
    elements.append(ct)

    doc.build(elements)
    return buf.getvalue()
