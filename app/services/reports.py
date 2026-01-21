from __future__ import annotations

import io
from datetime import datetime, timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .. import models


def build_pet_report_pdf(
    pet: models.Pet,
    feedings: list[models.FeedingEvent],
    weights: list[models.PetWeightEntry],
    inventory: models.PetFoodInventory | None,
    start_dt: datetime,
    end_dt: datetime,
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()
    story: list = []
    end_display = (end_dt - timedelta(days=1)).date()
    date_range = f"{start_dt.date().isoformat()} to {end_display.isoformat()}"
    generated = datetime.utcnow().isoformat(timespec="minutes")

    story.append(Paragraph(f"{pet.name} Report", styles["Title"]))
    story.append(Paragraph(f"Date range: {date_range}", styles["Normal"]))
    story.append(Paragraph(f"Generated: {generated} UTC", styles["Normal"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Inventory", styles["Heading2"]))
    inventory_data = [
        ["Food", "Sachets", "Remaining (g)", "Updated"],
    ]
    if inventory:
        inventory_data.append(
            [
                inventory.food_name,
                str(inventory.sachet_count),
                str(inventory.remaining_grams),
                inventory.updated_at.isoformat(timespec="minutes"),
            ]
        )
    else:
        inventory_data.append(["No inventory set.", "-", "-", "-"])
    inventory_table = _styled_table(inventory_data)
    story.append(inventory_table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("Weight Entries", styles["Heading2"]))
    weight_data = [["Recorded At (UTC)", "Weight (kg)"]]
    if weights:
        for entry in weights:
            weight_data.append(
                [
                    entry.recorded_at.isoformat(timespec="minutes"),
                    f"{entry.weight_kg:.2f}",
                ]
            )
    else:
        weight_data.append(["No weight entries.", "-"])
    weight_table = _styled_table(weight_data, col_widths=[300, 120])
    story.append(weight_table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("Feedings", styles["Heading2"]))
    feeding_data = [["Fed At (UTC)", "Amount (g)", "Diet"]]
    if feedings:
        for entry in feedings:
            feeding_data.append(
                [
                    entry.fed_at.isoformat(timespec="minutes"),
                    str(entry.amount_grams),
                    entry.diet_type or "-",
                ]
            )
    else:
        feeding_data.append(["No feedings.", "-", "-"])
    feeding_table = _styled_table(feeding_data, col_widths=[260, 80, 140])
    story.append(feeding_table)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def _styled_table(data: list[list[str]], col_widths: list[int] | None = None) -> Table:
    table = Table(data, hAlign="LEFT", colWidths=col_widths)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e4d3c3")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1f1b16")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e4d3c3")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#fffaf4")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.HexColor("#fffaf4"), colors.HexColor("#fdf3ea")],
                ),
            ]
        )
    )
    return table
