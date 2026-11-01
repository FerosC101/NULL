"""The exported report: a finished document with vector exhibits, drawn only from the frozen snapshot."""

import io
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.models import Report
from app.services.lifecycle import SEVERITY
from app.services.reports import SECTION_TITLES, normalize_snapshot

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
for name, file in (
    ("Geist-Light", "Geist-Light.ttf"),
    ("Geist", "Geist-Regular.ttf"),
    ("Geist-Medium", "Geist-Medium.ttf"),
    ("GeistMono", "GeistMono-Regular.ttf"),
    ("GeistMono-Medium", "GeistMono-Medium.ttf"),
):
    pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
pdfmetrics.registerFontFamily("Geist", normal="Geist", bold="Geist-Medium", italic="Geist", boldItalic="Geist-Medium")

INK = colors.HexColor("#111111")
BODY = colors.HexColor("#2B2B2B")
GRAY = colors.HexColor("#6B6B6B")
RULE = colors.HexColor("#DCDCDC")
WASH = colors.HexColor("#F4F4F4")
FILL = colors.HexColor("#3D3D3D")
OK = colors.HexColor("#2F8F62")
WARN = colors.HexColor("#A87A26")
BAD = colors.HexColor("#B84A4A")
ON_BLACK = {
    "SUPPORTED": colors.HexColor("#55B987"),
    "CONTRADICTED": colors.HexColor("#D46B6B"),
    "PARTIALLY IDENTIFIED": colors.HexColor("#D6A85B"),
    "UNDERDETERMINED": colors.HexColor("#D6A85B"),
    "UNVERIFIED": colors.HexColor("#A3A3A3"),
}
ON_PAPER = {
    "SUPPORTED": OK,
    "CONTRADICTED": BAD,
    "PARTIALLY IDENTIFIED": WARN,
    "UNDERDETERMINED": WARN,
    "UNVERIFIED": GRAY,
}

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm
WIDTH = PAGE_W - 2 * MARGIN


def _style(name: str, **kw) -> ParagraphStyle:
    return ParagraphStyle(name, **{"fontName": "Geist", "textColor": BODY, "fontSize": 9.5, "leading": 14.5, **kw})


STYLES = {
    "h1": _style("h1", fontName="Geist-Light", fontSize=21, leading=26, textColor=INK, spaceAfter=3),
    "h2": _style("h2", fontName="Geist-Medium", fontSize=11, leading=15, textColor=INK, spaceBefore=11, spaceAfter=3),
    "h3": _style("h3", fontName="Geist-Medium", fontSize=9.5, leading=13.5, textColor=INK, spaceBefore=6, spaceAfter=1),
    "body": _style("body", spaceAfter=4),
    "lede": _style("lede", fontName="Geist-Light", fontSize=12.5, leading=18, spaceAfter=7),
    "meta": _style("meta", fontSize=8, leading=11.5, textColor=GRAY),
    "kind": _style("kind", fontName="GeistMono", fontSize=6.8, leading=10, textColor=GRAY, spaceAfter=7),
    "label": _style("label", fontName="GeistMono", fontSize=6.6, leading=9.5, textColor=GRAY),
    "cell": _style("cell", fontSize=8, leading=11.2),
    "strong": _style("strong", fontName="Geist-Medium", fontSize=8, leading=11.2, textColor=INK),
    "mono": _style("mono", fontName="GeistMono", fontSize=7, leading=10.2),
    "verdict": _style("verdict", fontName="GeistMono-Medium", fontSize=17, leading=22, spaceAfter=3),
    "claim": _style("claim", fontName="Geist-Light", fontSize=14, leading=19.5, textColor=INK, spaceAfter=5),
}


def _p(text: Any, style: str = "body", **kw) -> Paragraph:
    base = STYLES[style]
    return Paragraph(escape(str(text)), ParagraphStyle(f"{style}+", parent=base, **kw) if kw else base)


def _when(value: str | None) -> str:
    if not value:
        return "Not recorded"
    return datetime.fromisoformat(value).astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _hour(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(UTC).strftime("%H:%M")


def _words(value: str) -> str:
    return value.replace("_", " ")


def _table(header: list[str], rows: list[list[Any]], widths: list[float], styles: list[str] | None = None) -> Table:
    """Widths are fractions of the text width. Long tables repeat their header across pages."""
    styles = styles or ["cell"] * len(header)
    body = [[c if isinstance(c, Flowable) else _p(c, styles[i]) for i, c in enumerate(row)] for row in rows]
    table = Table(
        [[_p(h.upper(), "label") for h in header], *body], colWidths=[w * WIDTH for w in widths], repeatRows=1
    )
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.7, INK),
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
            ]
        )
    )
    return table


class Heading(Paragraph):
    """A numbered section heading. The document records its page for the contents and bookmarks."""

    def __init__(self, number: int, title: str):
        text = f'<font name="GeistMono" size="9" color="#6B6B6B">{number:02d}</font>&nbsp;&nbsp;{escape(title)}'
        super().__init__(text, STYLES["h1"])
        self.section = (number, title)


class Lifecycle(Flowable):
    MARKS = {"completed": INK, "in_progress": GRAY, "needs_attention": WARN, "blocked": BAD, "not_started": RULE}
    WORDS = {
        "completed": "Completed",
        "in_progress": "In progress",
        "needs_attention": "Needs attention",
        "blocked": "Blocked",
        "not_started": "Not started",
    }

    def __init__(self, stages: list[dict]):
        super().__init__()
        self.stages = stages
        self.width, self.height = WIDTH, 44

    def draw(self) -> None:
        c = self.canv
        step = self.width / len(self.stages)
        for index, stage in enumerate(self.stages):
            x = index * step
            c.setFillColor(self.MARKS[stage["status"]])
            c.rect(x, self.height - 3, step - 3, 3, stroke=0, fill=1)
            c.setFillColor(INK)
            c.setFont("Geist-Medium", 7.6)
            c.drawString(x, self.height - 15, stage["label"])
            c.setFillColor(GRAY)
            c.setFont("Geist", 6.5)
            c.drawString(x, self.height - 25, self.WORDS[stage["status"]])
            for row, line in enumerate(simpleSplit(stage["summary"] or "", "Geist", 6.1, step - 6)[:2]):
                c.drawString(x, self.height - 33.5 - row * 7.2, line)


class CoverageGrid(Flowable):
    LABEL = 112
    TOTAL = 42
    ROW = 11
    CLOSED = {"disconnected": "Disconnected", "not_selected": "Not selected", "restricted": "Restricted, not read"}

    def __init__(self, matrix: dict):
        super().__init__()
        self.matrix = matrix
        self.width = WIDTH
        self.height = 16 + len(matrix["rows"]) * self.ROW + 18

    def draw(self) -> None:
        c = self.canv
        hours = self.matrix["hours"]
        cell = (self.width - self.LABEL - self.TOTAL) / max(len(hours), 1)
        top = self.height - 14
        c.setFont("GeistMono", 5.8)
        c.setFillColor(GRAY)
        for index, value in enumerate(hours):
            if index % 6 == 0:
                c.drawString(self.LABEL + index * cell, top + 3, _hour(value))
        c.drawRightString(self.width, top + 3, "RECORDS")
        for position, row in enumerate(self.matrix["rows"]):
            y = top - (position + 1) * self.ROW
            c.setFillColor(BODY)
            c.setFont("Geist", 7.2)
            c.drawString(0, y + 2.6, row["label"])
            if row["state"] != "readable":
                c.setFillColor(WASH)
                c.rect(self.LABEL, y + 0.8, cell * len(hours) - 1, self.ROW - 1.6, stroke=0, fill=1)
                c.setFillColor(GRAY)
                c.setFont("Geist", 6.4)
                c.drawString(self.LABEL + 4, y + 2.8, self.CLOSED.get(row["state"], row["state"]))
                continue
            offset = 0
            for item in row["cells"]:
                span = item["hours"]
                color = {"records": FILL, "gap": BAD}.get(item["state"], RULE)
                c.setFillColor(color)
                c.rect(self.LABEL + offset * cell, y + 0.8, span * cell - 1, self.ROW - 1.6, stroke=0, fill=1)
                offset += span
            c.setFillColor(GRAY)
            c.setFont("GeistMono", 6.4)
            c.drawRightString(self.width, y + 2.8, f"{row['records']:,}")
        y = 2
        x = self.LABEL
        c.setFont("Geist", 6.5)
        for color, text in (
            (FILL, "Records"),
            (RULE, "No records in this period"),
            (BAD, "Collection gap"),
            (WASH, "Not read"),
        ):
            c.setFillColor(color)
            c.rect(x, y, 7, 6, stroke=0, fill=1)
            c.setFillColor(GRAY)
            c.drawString(x + 10, y + 0.8, text)
            x += 16 + pdfmetrics.stringWidth(text, "Geist", 6.5) + 10


class ComparisonGrid(Flowable):
    """Each reality's prediction against what was observed. Rows that separate realities come first."""

    ROW = 16
    OBSERVED = 64

    def __init__(self, realities: list[dict], evidence: dict[str, dict]):
        super().__init__()
        self.realities = realities
        self.evidence = evidence
        keys = list(dict.fromkeys(p["observable"] for r in realities for p in r["predictions"]))
        self.rows = sorted(
            [
                (key, [next((p for p in r["predictions"] if p["observable"] == key), None) for r in realities])
                for key in keys
            ],
            key=lambda row: not self._separates(row[1]),
        )
        self.width = WIDTH
        self.height = 16 + len(self.rows) * self.ROW + 17

    @staticmethod
    def _separates(cells: list[dict | None]) -> bool:
        stances = {c["expects"] if c else "any" for c in cells}
        return len(stances) > 1

    def _glyph(self, cell: dict | None, x: float, y: float) -> None:
        c = self.canv
        if not cell or cell["expects"] == "any":
            c.setStrokeColor(RULE)
            c.setLineWidth(0.8)
            c.line(x - 3, y, x + 3, y)
            return
        color = {"matched": INK, "violated": BAD, "inconclusive": WARN}.get(cell["outcome"], GRAY)
        c.setStrokeColor(color)
        c.setLineWidth(0.8)
        if cell["outcome"] in ("untested", "indifferent"):
            c.setDash(1.4, 1.4)
        c.circle(x, y, 4, stroke=1, fill=0)
        c.setDash()
        if cell["expects"] == "positive":
            c.setFillColor(color)
            c.circle(x, y, 1.7, stroke=0, fill=1)
        if cell["outcome"] == "violated":
            c.line(x - 3, y - 3, x + 3, y + 3)

    def draw(self) -> None:
        c = self.canv
        count = max(len(self.realities), 1)
        column = 32
        names = self.width - self.OBSERVED - count * column
        top = self.height - 12
        c.setFont("GeistMono", 6.2)
        c.setFillColor(GRAY)
        c.drawString(0, top + 2, "OBSERVABLE")
        c.drawString(names, top + 2, "OBSERVED")
        for index, reality in enumerate(self.realities):
            c.drawCentredString(names + self.OBSERVED + (index + 0.5) * column, top + 2, reality["label"])
        c.setStrokeColor(INK)
        c.setLineWidth(0.7)
        c.line(0, top, self.width, top)
        for position, (key, cells) in enumerate(self.rows):
            y = top - (position + 1) * self.ROW
            label = next(p["label"] for p in cells if p)
            c.setFillColor(BODY if self._separates(cells) else GRAY)
            c.setFont("Geist", 7.6)
            c.drawString(0, y + 5, label)
            item = self.evidence.get(key)
            c.setFillColor(GRAY)
            c.setFont("GeistMono", 6.6)
            c.drawString(names, y + 5, self._observed(item))
            for index, cell in enumerate(cells):
                self._glyph(cell, names + self.OBSERVED + (index + 0.5) * column, y + 7)
            c.setStrokeColor(RULE)
            c.setLineWidth(0.25)
            c.line(0, y, self.width, y)
        x = 0
        c.setFont("Geist", 6.5)
        for sample, text in (
            ({"expects": "positive", "outcome": "matched"}, "Predicts a positive result, seen"),
            ({"expects": "zero", "outcome": "matched"}, "Predicts nothing found, seen"),
            ({"expects": "zero", "outcome": "untested"}, "Not yet observed"),
            ({"expects": "zero", "outcome": "violated"}, "Conflicts with observation"),
        ):
            self._glyph(sample, x + 4, 4.5)
            c.setFillColor(GRAY)
            c.setFont("Geist", 6.5)
            c.drawString(x + 11, 2.5, text)
            x += 11 + pdfmetrics.stringWidth(text, "Geist", 6.5) + 12

    @staticmethod
    def _observed(item: dict | None) -> str:
        if not item:
            return "Not observed"
        state = item.get("state")
        if state == "unavailable":
            return "Unavailable"
        if state == "partial":
            return "Partial"
        if state == "zero":
            return "None"
        value = item.get("value")
        return f"Yes: {value:g}" if value is not None else "Yes"


def _nice_ceiling(value: float) -> float:
    if value <= 0:
        return 1
    power = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * power:
            return step * power
    return 10 * power


class HourlyChart(Flowable):
    """One measure, one axis. The measure is drawn as a line or bars, with its expected level dashed."""

    PLOT_LEFT = 34

    def __init__(
        self,
        labels: list[str],
        values: list[float | None],
        expected: list[float | None],
        unit: str,
        bars=False,
        flagged: list[bool] | None = None,
        marks: list[tuple[int, str]] | None = None,
        scale: float = 1,
    ):
        super().__init__()
        self.labels, self.values, self.expected = labels, values, expected
        self.unit, self.bars, self.flagged, self.marks, self.scale = unit, bars, flagged, marks or [], scale
        self.width, self.height = WIDTH, 118

    def draw(self) -> None:
        c = self.canv
        known = [v / self.scale for v in [*self.values, *self.expected] if v is not None]
        ceiling = _nice_ceiling(max(known, default=1))
        left, bottom = self.PLOT_LEFT, 22
        plot_w, plot_h = self.width - left, self.height - bottom - 14
        y_of = lambda v: bottom + plot_h * (v / self.scale) / ceiling  # noqa: E731
        count = max(len(self.labels), 1)
        x_of = lambda i: left + (i + 0.5) * plot_w / count  # noqa: E731
        c.setFont("GeistMono", 6)
        for step in range(5):
            value = ceiling * step / 4
            y = bottom + plot_h * step / 4
            c.setStrokeColor(RULE if step else INK)
            c.setLineWidth(0.25 if step else 0.7)
            c.line(left, y, self.width, y)
            c.setFillColor(GRAY)
            c.drawRightString(left - 4, y - 2, f"{value:g}")
        c.setFont("Geist", 6.4)
        c.drawString(0, self.height - 6, self.unit)
        c.setFont("GeistMono", 5.8)
        for index, label in enumerate(self.labels):
            if index % 3 == 0:
                c.drawCentredString(x_of(index), bottom - 9, label)
        if self.bars:
            width = plot_w / count - 2
            for index, value in enumerate(self.values):
                if value:
                    hit = self.flagged and self.flagged[index]
                    c.setFillColor(BAD if hit else FILL)
                    c.rect(x_of(index) - width / 2, bottom, width, y_of(value) - bottom, stroke=0, fill=1)
        c.setStrokeColor(GRAY)
        c.setLineWidth(0.8)
        c.setDash(2, 2)
        self._line([(x_of(i), y_of(v)) for i, v in enumerate(self.expected) if v is not None])
        c.setDash()
        if not self.bars:
            c.setStrokeColor(INK)
            c.setLineWidth(1.3)
            self._line([(x_of(i), y_of(v)) for i, v in enumerate(self.values) if v is not None])
        for index, text in self.marks:
            c.setStrokeColor(BAD)
            c.setLineWidth(0.6)
            c.line(x_of(index), bottom, x_of(index), bottom + plot_h)
            c.setFillColor(BAD)
            c.setFont("Geist", 6.4)
            # The label sits on the side away from the data that follows the event.
            if x_of(index) > left + plot_w / 2:
                c.drawRightString(x_of(index) - 3, bottom + plot_h - 7, text)
            else:
                c.drawString(x_of(index) + 3, bottom + plot_h - 7, text)
        x = left
        c.setFont("Geist", 6.5)
        c.setFillColor(GRAY)
        c.drawString(x, 1, f"{'Bars' if self.bars else 'Solid line'}: observed.  Dashed line: expected for that hour.")

    def _line(self, points: list[tuple[float, float]]) -> None:
        c = self.canv
        for (x1, y1), (x2, y2) in zip(points, points[1:], strict=False):
            c.line(x1, y1, x2, y2)


class Pipeline(Flowable):
    STAGES = (
        ("awaiting", "Awaiting approval", INK),
        ("approved", "Approved", INK),
        ("pending", "Pending verification", WARN),
        ("failed", "Failed or recurred", BAD),
        ("verified", "Verified", OK),
        ("rejected", "Rejected", GRAY),
    )

    def __init__(self, counts: dict[str, int]):
        super().__init__()
        self.counts = counts
        self.width, self.height = WIDTH, 40

    def draw(self) -> None:
        c = self.canv
        step = self.width / len(self.STAGES)
        for index, (key, label, color) in enumerate(self.STAGES):
            x = index * step
            value = self.counts.get(key, 0)
            c.setFillColor(color if value else RULE)
            c.rect(x, self.height - 2.5, step - 3, 2.5, stroke=0, fill=1)
            c.setFillColor(INK if value else GRAY)
            c.setFont("GeistMono", 16)
            c.drawString(x, self.height - 22, str(value))
            c.setFillColor(GRAY)
            c.setFont("Geist", 6.8)
            c.drawString(x, self.height - 33, label)


def _pipeline_counts(mitigations: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for m in mitigations:
        if m["approval"] == "rejected":
            key = "rejected"
        elif m["verification"] == "verified":
            key = "verified"
        elif m["verification"] in ("failed", "recurred"):
            key = "failed"
        elif m["execution"] == "executed":
            key = "pending"
        elif m["approval"] == "approved":
            key = "approved"
        else:
            key = "awaiting"
        counts[key] = counts.get(key, 0) + 1
    return counts


class Document(BaseDocTemplate):
    def __init__(self, buffer: io.BytesIO, report: Report, snapshot: dict, pages: dict[int, int], total: int):
        super().__init__(
            buffer,
            pagesize=A4,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=22 * mm,
            bottomMargin=19 * mm,
            title=f"{report.ref} {snapshot['investigation']['name']}",
            author="NULL",
            subject=f"Investigation report, version {report.version}",
        )
        self.report, self.snapshot, self.pages_known, self.total = report, snapshot, pages, total
        self.section_pages: dict[int, int] = {}
        frame = Frame(
            MARGIN, 19 * mm, WIDTH, PAGE_H - 41 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0
        )
        self.addPageTemplates(
            [
                PageTemplate(id="cover", frames=[frame], onPage=self._cover),
                PageTemplate(id="body", frames=[frame], onPage=self._furniture),
            ]
        )

    def afterFlowable(self, flowable: Flowable) -> None:
        if isinstance(flowable, Heading):
            number, title = flowable.section
            self.section_pages[number] = self.page
            key = f"section-{number}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(f"{number:02d} {title}", key, level=0)

    def _furniture(self, canvas: Canvas, doc) -> None:
        canvas.saveState()
        s = self.snapshot
        canvas.setFillColor(colors.black)
        canvas.circle(MARGIN + 4.5, PAGE_H - 12 * mm, 4.5, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.circle(MARGIN + 4.5, PAGE_H - 12 * mm, 1, stroke=0, fill=1)
        canvas.setFillColor(GRAY)
        canvas.setFont("GeistMono", 6.8)
        canvas.drawString(MARGIN + 13, PAGE_H - 12 * mm - 2.2, f"{self.report.ref}  VERSION {self.report.version}")
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 12 * mm - 2.2, s["investigation"]["ref"])
        canvas.setFont("Geist", 6.8)
        canvas.drawString(MARGIN, 11 * mm, "Synthetic demonstration data. No real organization was examined.")
        canvas.setFont("GeistMono", 6.8)
        canvas.drawRightString(PAGE_W - MARGIN, 11 * mm, f"PAGE {doc.page} OF {self.total or doc.page}")
        canvas.restoreState()

    def _cover(self, canvas: Canvas, doc) -> None:
        s, report = self.snapshot, self.report
        canvas.saveState()
        canvas.setFillColor(colors.black)
        canvas.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
        canvas.setStrokeColor(colors.HexColor("#2C2C2C"))
        canvas.setLineWidth(0.4)
        for radius in (95, 150, 205):
            canvas.circle(PAGE_W - 28 * mm, PAGE_H - 20 * mm, radius * mm * 0.62, stroke=1, fill=0)
        canvas.setFillColor(colors.black)
        canvas.setStrokeColor(colors.HexColor("#3A3A3A"))
        canvas.circle(MARGIN + 11, PAGE_H - MARGIN - 11, 11, stroke=1, fill=1)
        canvas.setFillColor(colors.white)
        canvas.circle(MARGIN + 11, PAGE_H - MARGIN - 11, 2.4, stroke=0, fill=1)
        canvas.setFont("Geist-Light", 14)
        canvas.drawString(MARGIN + 31, PAGE_H - MARGIN - 16, "N U L L")

        y = PAGE_H - 88 * mm
        canvas.setFont("GeistMono", 7.5)
        canvas.setFillColor(colors.HexColor("#A3A3A3"))
        canvas.drawString(MARGIN, y, "INVESTIGATION REPORT")
        y -= 12 * mm
        canvas.setFillColor(colors.white)
        canvas.setFont("Geist-Light", 30)
        for line in simpleSplit(s["investigation"]["name"], "Geist-Light", 30, WIDTH)[:3]:
            canvas.drawString(MARGIN, y, line)
            y -= 36
        y -= 2
        canvas.setFillColor(colors.HexColor("#A3A3A3"))
        canvas.setFont("Geist-Light", 12)
        for line in simpleSplit(s["claim"]["text"], "Geist-Light", 12, WIDTH * 0.8)[:4]:
            canvas.drawString(MARGIN, y, line)
            y -= 17
        y -= 11
        assessment = s["executive_summary"]["assessment"]
        canvas.setFillColor(ON_BLACK.get(assessment, colors.white))
        canvas.setFont("GeistMono-Medium", 15)
        canvas.drawString(MARGIN, y, assessment)
        if s["conclusion"]["provisional"]:
            canvas.setFont("GeistMono", 7.5)
            canvas.setFillColor(colors.HexColor("#A3A3A3"))
            canvas.drawString(MARGIN, y - 13, "PROVISIONAL: THE INVESTIGATION WAS STILL OPEN")

        contents_top = 92 * mm
        canvas.setFont("GeistMono", 6.8)
        canvas.setFillColor(colors.HexColor("#8A8A8A"))
        canvas.drawString(MARGIN, contents_top, "CONTENTS")
        y = contents_top - 7 * mm
        for index, title in enumerate(SECTION_TITLES, start=1):
            canvas.setFillColor(colors.HexColor("#8A8A8A"))
            canvas.setFont("GeistMono", 7.2)
            canvas.drawString(MARGIN, y, f"{index:02d}")
            canvas.setFillColor(colors.white)
            canvas.setFont("Geist", 8.6)
            canvas.drawString(MARGIN + 18, y, title)
            canvas.setFillColor(colors.HexColor("#8A8A8A"))
            canvas.setFont("GeistMono", 7.2)
            canvas.drawRightString(MARGIN + WIDTH * 0.55, y, str(self.pages_known.get(index, "")))
            y -= 5.3 * mm

        meta = [
            ("REPORT", f"{report.ref}, version {report.version}"),
            ("GENERATED", report.created_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")),
            ("INVESTIGATION", s["investigation"]["ref"]),
            ("INVESTIGATOR", s["investigation"]["assignee"]),
            ("SHA-256", report.sha256[:24]),
        ]
        x = MARGIN + WIDTH * 0.64
        y = contents_top
        for label, value in meta:
            canvas.setFillColor(colors.HexColor("#8A8A8A"))
            canvas.setFont("GeistMono", 6.4)
            canvas.drawString(x, y, label)
            canvas.setFillColor(colors.white)
            canvas.setFont("Geist", 8.2)
            canvas.drawString(x, y - 10, value)
            y -= 8.2 * mm
        canvas.setFillColor(colors.HexColor("#8A8A8A"))
        canvas.setFont("Geist", 7.2)
        canvas.drawString(MARGIN, 14 * mm, s["demo_notice"])
        canvas.restoreState()


class Story:
    """Builds the nine sections. Exhibits are numbered in the order they appear."""

    def __init__(self, report: Report, s: dict):
        self.report, self.s = report, s
        self.flow: list = []
        self.exhibit_count = 0
        self.primary = s["observations"] or self._observed_by_tests()

    def _observed_by_tests(self) -> dict[str, dict]:
        """Older reports stored observations only under the tests that made them."""
        evidence: dict[str, dict] = {}
        for procedure in self.s["procedures"]:
            for result in procedure["results"]:
                if result["actual"]:
                    evidence[result["observable"]] = result["actual"]
        return evidence

    def add(self, *items) -> None:
        self.flow.extend(items)

    def section(self, number: int, kind: str = "") -> None:
        # The summary stands alone for executives, and the appendix starts clean. Other sections flow.
        if number in (2, len(SECTION_TITLES)):
            self.add(PageBreak())
        elif number > 1:
            self.add(CondPageBreak(90 * mm), Spacer(1, 18))
        self.add(Heading(number, SECTION_TITLES[number - 1]))
        self.add(_p(kind.upper(), "kind") if kind else Spacer(1, 7))

    def exhibit(self, title: str, drawing: Flowable, note: str, period: str = "") -> None:
        self.exhibit_count += 1
        self.add(
            KeepTogether(
                [
                    Spacer(1, 6),
                    _p(f"EXHIBIT {self.exhibit_count}", "label"),
                    _p(title, "h3", spaceBefore=1, spaceAfter=4),
                    drawing,
                    Spacer(1, 4),
                    _p(note, "meta"),
                    *([_p(period, "meta")] if period else []),
                    Spacer(1, 6),
                ]
            )
        )

    def missing(self, text: str = "Not captured in this report version.") -> None:
        self.add(_p(text, "meta"))

    def summary(self) -> None:
        s = self.s
        e = s["executive_summary"]
        self.section(1, "Analytical conclusion")
        self.add(_p(e["assessment"], "verdict", textColor=ON_PAPER.get(e["assessment"], INK)))
        if s["conclusion"]["provisional"]:
            self.add(_p("Provisional. The investigation was still open when this report was generated.", "meta"))
        self.add(_p(e["rationale"], "lede"))
        if s["lifecycle"]:
            self.add(Spacer(1, 2), Lifecycle(s["lifecycle"]), Spacer(1, 8))
        blocks = [("Claim under review", s["claim"]["text"])]
        if e["objective"]:
            blocks.append(("Investigation objective", e["objective"]))
        if e["key_finding"]:
            blocks.append(("Most important discovery", f"{e['key_finding']['title']}. {e['key_finding']['body']}"))
        if e["uncertainty"]:
            blocks.append(("Main unresolved uncertainty", e["uncertainty"]))
        if e["next_action"]:
            blocks.append(("Recommended next action", f"{e['next_action']['label']}. {e['next_action']['detail']}"))
        self.add(
            _table(
                ["Question", "Answer"],
                [[_p(title, "strong"), _p(text, "cell")] for title, text in blocks],
                [0.27, 0.73],
            )
        )
        c = e["counts"]
        self.add(
            Spacer(1, 5),
            _p(
                f"{c['evidence']} evidence items, {c['realities']} competing explanations "
                f"({c['surviving_realities']} still compatible), {c['critical_findings']} critical findings, "
                f"{c['remediations']} corrective actions.",
                "meta",
            ),
        )

    def scope(self) -> None:
        s = self.s
        scope = s["scope"]
        self.section(2)
        self.add(
            _table(
                ["Field", "Value"],
                [
                    ["Time period", f"{_when(scope['window_start'])} to {_when(scope['window_end'])}"],
                    ["Assets", scope["assets"]],
                    ["Objective", scope["objective"] or "Not stated"],
                    ["Dataset", f"{scope['dataset']} (synthetic)"],
                    ["Claim interpretation", s["claim"]["interpretation"] or "Not recorded"],
                    ["Reasoning", s["investigation"]["reasoning_note"] or s["investigation"]["reasoning_mode"]],
                ],
                [0.25, 0.75],
            ),
            _p("Data sources examined", "h2"),
            _table(
                ["Source", "Mode", "Status when generated"],
                [[x["name"], x["mode"], x["status"]] for x in s["sources"]],
                [0.56, 0.2, 0.24],
            ),
        )
        if s["methodology"]:
            self.add(_p("Methodology", "h2"), _p(s["methodology"]))
        self.add(_p("Relevant limitations", "h2"))
        for limit in s["limitations"]:
            self.add(_p(limit))
        if not s["limitations"]:
            self.add(_p("None recorded."))

    def evidence(self) -> None:
        s = self.s
        self.section(3, "Observed facts")
        items = s["evidence_quality"]["items"]
        tally = ", ".join(f"{v} {k}" for k, v in s["evidence_quality"]["by_reliability"].items())
        self.add(_p(f"{len(items)} evidence items were collected. By reliability: {tally}."))
        exhibits = s["exhibits"]
        if exhibits:
            matrix = exhibits["coverage_matrix"]
            self.exhibit(
                "Evidence coverage by source and hour",
                CoverageGrid(matrix),
                matrix["interpretation"],
                f"Period: {_when(matrix['window']['start'])} to {_when(matrix['window']['end'])}. "
                "Each cell counts stored records. Endpoint records arrive in 4-hour batches.",
            )
            hosts = exhibits["host_coverage"]
            if hosts.get("unmonitored"):
                channel = lambda v: "Not read" if v is None else ("Seen" if v else "None")  # noqa: E731
                self.add(
                    _p("Hosts endpoint monitoring cannot see", "h2"),
                    _p(f"{hosts['reporting']} of {hosts['hosts']} in-scope hosts have a reporting agent."),
                    _table(
                        ["Host", "Class", "Agent", "Network", "Independent logs"],
                        [
                            [
                                u["hostname"],
                                u["asset_class"],
                                "Never enrolled" if u["edr"] == "never_enrolled" else "Enrolled, silent",
                                channel(u["network"]),
                                channel(u["independent_logs"]),
                            ]
                            for u in hosts["unmonitored"]
                        ],
                        [0.22, 0.2, 0.22, 0.16, 0.2],
                        ["mono", "cell", "cell", "cell", "cell"],
                    ),
                )
        else:
            self.missing("Coverage exhibits were not captured in this report version.")
        by_source: dict[str, dict[str, int]] = {}
        for item in items:
            row = by_source.setdefault(item["source"], {})
            row[item["reliability"]] = row.get(item["reliability"], 0) + 1
        self.add(
            _p("Evidence source summary", "h2"),
            _table(
                ["Source", "Items", "High", "Moderate", "Low"],
                [
                    [k, sum(v.values()), v.get("high", 0), v.get("moderate", 0), v.get("low", 0)]
                    for k, v in sorted(by_source.items())
                ],
                [0.4, 0.15, 0.15, 0.15, 0.15],
                ["mono", "cell", "cell", "cell", "cell"],
            ),
        )
        unknown = s["ledger"].get("unknown") or []
        self.add(_p("Missing evidence", "h2"))
        self.add(
            _p("Required and never observed: " + ", ".join(unknown) + ".")
            if unknown
            else _p("Nothing required remained unobserved.")
        )
        conflicts = [f for f in s["findings"] if f["kind"] == "measurement_bias"]
        if conflicts:
            self.add(_p("Conflicting observations", "h2"))
            for finding in conflicts:
                self.add(_p(f"{finding['title']}: {finding['body']}"))

    def explanations(self) -> None:
        s = self.s
        self.section(4, "Generated hypotheses. None of these is an observed fact")
        realities = s["realities"]
        if not realities:
            self.add(_p("This claim type has no competing explanations."))
            return
        if any(r["predictions"] for r in realities):
            self.exhibit(
                "What each explanation predicts, against what was observed",
                ComparisonGrid(realities, self.primary),
                "Rows where explanations disagree come first. Only those rows can separate them.",
            )
        for reality in realities:
            verdict = {"incompatible": "Excluded"}.get(reality["compatibility"], reality["compatibility"].capitalize())
            block = [
                _p(f"Explanation {reality['label']}: {reality['title']}", "h2"),
                _p(f"{verdict}. Origin: {reality['origin']}.", "meta"),
                _p(reality["statement"]),
                _table(
                    ["Supporting", "Contradicting", "Unresolved assumptions"],
                    [
                        [
                            ", ".join(reality["supporting"]) or "None",
                            ", ".join(reality["contradicting"]) or "None",
                            " ".join(reality["assumptions"]) or "None",
                        ]
                    ],
                    [0.24, 0.24, 0.52],
                ),
            ]
            self.add(KeepTogether(block))

    def tests(self) -> None:
        s = self.s
        self.section(5, "Observed results, kept apart from proposed tests")
        executed = [p for p in s["procedures"] if p["status"] == "completed"]
        stopped = [p for p in s["procedures"] if p["status"] in ("blocked", "failed", "rejected")]
        proposed = [p for p in s["procedures"] if p["status"] in ("proposed", "approved", "running", "not_needed")]
        self.add(_p("Tests performed", "h2"))
        if not executed:
            self.add(_p("No test beyond the first pass had been executed when this report was generated."))
        for procedure in executed:
            rows = []
            for result in procedure["results"]:
                expected = ", ".join(
                    f"{label}: {'nothing' if v == 'zero' else 'positive' if v == 'positive' else 'no view'}"
                    for label, v in result["expected"].items()
                )
                actual = result["actual"]
                rows.append(
                    [
                        result["label"],
                        expected or "No prediction",
                        actual["observation"] if actual else "No result recorded",
                        actual["ref"] if actual else "",
                    ]
                )
            block = [
                _p(procedure["title"], "h3"),
                _p(f"Purpose: {procedure['rationale'] or procedure['procedure']}", "meta"),
            ]
            if procedure["decided_by"]:
                block.append(_p(f"Approved by {procedure['decided_by']} at {_when(procedure['decided_at'])}.", "meta"))
            if rows:
                block.append(Spacer(1, 3))
                block.append(
                    _table(
                        ["Observable", "Expected", "Actual", "Ref"],
                        rows,
                        [0.24, 0.2, 0.46, 0.1],
                        ["cell", "cell", "cell", "mono"],
                    )
                )
            self.add(KeepTogether(block))
        exhibits = s["exhibits"] or {}
        for series in exhibits.get("egress", []):
            labels = [_hour(p["ts"]) for p in series["points"]]
            marks = []
            for event in series["events"]:
                hour = _hour(datetime.fromisoformat(event["ts"]).astimezone(UTC).replace(minute=0).isoformat())
                if hour in labels:
                    marks.append((labels.index(hour), event["label"]))
            self.exhibit(
                f"Hourly egress for {series['host']}",
                HourlyChart(
                    labels,
                    [p["bytes"] for p in series["points"]],
                    [p["typical"] for p in series["points"]],
                    "Egress per hour (MB)",
                    marks=marks,
                    scale=1e6,
                ),
                f"Highest hour: {series['highest_bytes'] / 1e6:,.0f} MB at {_when(series['highest_ts'])}. Largest "
                f"departure from this host's baseline: {series['anomaly_bytes'] / 1e6:,.0f} MB at "
                f"{_when(series['anomaly_ts'])}, against a typical {series['baseline_median_bytes'] / 1e6:,.0f} MB. "
                + (
                    "This falls inside an approved change."
                    if series["explained_by_change"]
                    else "No approved change covers it."
                ),
                f"Period: {_when(s['scope']['window_start'])} to {_when(s['scope']['window_end'])}. "
                f"Evidence: {exhibits.get('refs', {}).get('egress') or 'not recorded'}.",
            )
        if stopped:
            self.add(
                _p("Tests that did not complete", "h2"),
                _table(
                    ["Test", "Status", "Reason"],
                    [[p["title"], p["status"], p["error"] or "Not recorded"] for p in stopped],
                    [0.5, 0.14, 0.36],
                ),
            )
        if proposed:
            self.add(
                _p("Proposed tests, not executed", "h2"),
                _table(
                    ["Test", "Status", "Value (bits)"],
                    [[p["title"], _words(p["status"]), f"{p['information_gain_bits']:.2f}"] for p in proposed],
                    [0.62, 0.2, 0.18],
                ),
            )
        else:
            self.add(_p("No proposed test remains unexecuted.", "meta"))

    def findings(self) -> None:
        s = self.s
        conclusion = s["conclusion"]
        self.section(6, "Analytical conclusion")
        self.add(_p(conclusion["assessment"], "verdict", textColor=ON_PAPER.get(conclusion["assessment"], INK)))
        self.add(_p(conclusion["rationale"], "lede"))
        if conclusion["provisional"]:
            self.add(_p("This assessment is provisional. The investigation was still open.", "meta"))
        realities = s["realities"]
        claim_reality = [r for r in realities if r["claim_true"]]
        against = sorted({ref for r in claim_reality for ref in r["contradicting"]})
        support = sorted({ref for r in claim_reality for ref in r["supporting"]})
        if claim_reality:
            self.add(
                _table(
                    ["Evidence for the claim", "Evidence against the claim"],
                    [[", ".join(support) or "None", ", ".join(against) or "None"]],
                    [0.5, 0.5],
                    ["mono", "mono"],
                )
            )
        unknown = s["ledger"].get("unknown") or []
        assumed = s["ledger"].get("assumed") or []
        established = s["ledger"].get("inferred") or []
        if established:
            self.add(_p("What the evidence establishes", "h2"))
            for line in established:
                self.add(_p(line))
        self.add(_p("Remaining uncertainty", "h2"))
        lines = [f"Not observed: {u}." for u in unknown] + [f"Assumed, not tested: {a}" for a in assumed]
        for line in lines or ["No required observation or assumption remains open."]:
            self.add(_p(line))
        self.add(_p("Findings", "h2"))
        rows = [
            [f["severity"].capitalize(), f"{f['title']}. {f['body']}", ", ".join(f["evidence"]) or "None"]
            for f in sorted(s["findings"], key=lambda f: SEVERITY.index(f["severity"]))
        ]
        if rows:
            self.add(_table(["Severity", "Finding", "Evidence"], rows, [0.11, 0.73, 0.16], ["cell", "cell", "mono"]))
        else:
            self.add(_p("No weaknesses were identified in the evidence examined."))
        self.add(_p("Limitations", "h2"))
        for limit in s["limitations"] or ["None recorded."]:
            self.add(_p(limit))

    def actions(self) -> None:
        s = self.s
        self.section(7, "Recommendations")
        if not s["mitigations"]:
            self.add(_p("No corrective actions were recommended."))
            return
        roots = list(dict.fromkeys(m["root_cause"] for m in s["mitigations"] if m["root_cause"]))
        if roots:
            self.add(_p("Identified root causes", "h2"))
            for root in roots:
                self.add(_p(root))
        self.add(
            _p("Recommended actions", "h2"),
            _table(
                ["ID", "Action", "Priority", "Owner", "Target", "Status"],
                [
                    [
                        m["ref"],
                        m["action"],
                        m["priority"].capitalize(),
                        m["owner"],
                        m["target_date"] or "Not set",
                        f"{_words(m['approval']).capitalize()}, {_words(m['execution'])}",
                    ]
                    for m in s["mitigations"]
                ],
                [0.1, 0.42, 0.09, 0.13, 0.11, 0.15],
                ["mono", "cell", "cell", "cell", "cell", "cell"],
            ),
        )

    def verification(self) -> None:
        s = self.s
        self.section(8, "Observed results of corrective actions")
        if s["mitigations"]:
            self.exhibit(
                "Where corrective actions stand",
                Pipeline(_pipeline_counts(s["mitigations"])),
                "An action counts as verified only when its verification procedure passes against records.",
            )
        criteria = [m for m in s["mitigations"] if m["approval"] != "rejected"]
        if criteria:
            self.add(
                _p("Verification criteria", "h2"),
                _table(
                    ["ID", "Criteria", "Result"],
                    [[m["ref"], m["criteria"], _words(m["verification"]).capitalize()] for m in criteria],
                    [0.11, 0.69, 0.2],
                    ["mono", "cell", "cell"],
                ),
            )
        self.add(_p("Verification evidence", "h2"))
        if s["verifications"]:
            self.add(
                _table(
                    ["Action", "Time", "Result", "Evidence"],
                    [
                        [
                            v["remediation"],
                            _when(v["at"]),
                            "Passed" if v["passed"] else ("Recurrence" if v["recurrence"] else "Failed"),
                            v["summary"],
                        ]
                        for v in s["verifications"]
                    ],
                    [0.11, 0.21, 0.12, 0.56],
                    ["mono", "cell", "cell", "cell"],
                )
            )
        else:
            self.add(_p("No verification had run when this report was generated."))
        recurred = [v for v in s["verifications"] if v["recurrence"]]
        self.add(_p("Recurrence monitoring", "h2"))
        self.add(
            _p(
                f"Recurrence detected in {len(recurred)} of {len(s['verifications'])} verification runs."
                if recurred
                else "No recurrence observed in the runs recorded here."
            )
        )
        open_items = [m for m in criteria if m["verification"] != "verified"]
        self.add(_p("Remaining risks", "h2"))
        for m in open_items:
            self.add(_p(f"{m['ref']}: {m['risk']}"))
        if not open_items:
            self.add(_p("No corrective action remains open."))

    def appendix(self) -> None:
        s = self.s
        self.section(9, "Technical traceability")
        self.add(
            _p("A. Evidence references", "h2"),
            _table(
                ["ID", "Source", "Observation", "Reliability", "Relevance"],
                [
                    [e["ref"], e["source"], e["observation"], e["reliability"], e["relevance"]]
                    for e in s["evidence_quality"]["items"]
                ],
                [0.11, 0.13, 0.52, 0.12, 0.12],
                ["mono", "mono", "cell", "cell", "cell"],
            ),
        )
        methods = list(dict.fromkeys((p["tool"], p["method"]) for p in s["provenance"]["evidence"]))
        self.add(
            _p("B. Methodology by tool", "h2"),
            _table(["Tool", "Method"], [[tool, method] for tool, method in methods], [0.3, 0.7], ["mono", "cell"]),
            _p("C. Assumptions", "h2"),
            _table(
                ["Status", "Assumption", "Basis"],
                [[_words(a["status"]).capitalize(), a["text"], a["basis"] or "Not tested"] for a in s["assumptions"]],
                [0.13, 0.43, 0.44],
            ),
        )
        exhibits = s["exhibits"] or {}
        self.add(_p("D. Statistical details", "h2"))
        signins = exhibits.get("signins")
        if signins:
            self.exhibit(
                "Failed sign-ins per hour",
                HourlyChart(
                    [_hour(p["ts"]) for p in signins["points"]],
                    [p["failures"] for p in signins["points"]],
                    [p["expected"] for p in signins["points"]],
                    "Failed sign-ins per hour",
                    bars=True,
                    flagged=[p["flagged"] for p in signins["points"]],
                ),
                f"{signins['flagged_hours']} of {len(signins['points'])} hours exceed the baseline. Poisson tail test "
                "against the same hour-of-day baseline, Benjamini-Hochberg corrected at FDR 0.01.",
                f"Evidence: {exhibits.get('refs', {}).get('signins') or 'not recorded'}.",
            )
        egress = exhibits.get("egress") or []
        if egress:
            self.add(
                _table(
                    ["Host", "Max z", "At max z (MB)", "Median (MB)", "Baseline records"],
                    [
                        [
                            e["host"],
                            e["max_z"],
                            f"{e['anomaly_bytes'] / 1e6:,.0f}",
                            f"{e['baseline_median_bytes'] / 1e6:,.0f}",
                            e["baseline_records"],
                        ]
                        for e in egress
                    ],
                    [0.3, 0.14, 0.18, 0.18, 0.2],
                    ["mono", "cell", "cell", "cell", "cell"],
                )
            )
        if not signins and not egress:
            self.missing("Statistical exhibits were not captured in this report version.")
        self.add(
            _p("E. Technical execution log", "h2"),
            _table(
                ["Tool", "Role", "Status", "Records", "Started"],
                [
                    [t["tool"], t["role"], t["status"], f"{t['records_read']:,}", _when(t["started_at"])]
                    for t in s["provenance"]["tool_executions"]
                ],
                [0.34, 0.13, 0.13, 0.13, 0.27],
                ["mono", "cell", "cell", "cell", "cell"],
            ),
            _p("F. Provenance", "h2"),
            _table(
                ["ID", "Tool", "Records", "SHA-256 of cited records"],
                [[p["ref"], p["tool"], p["record_count"], p["sha256"] or ""] for p in s["provenance"]["evidence"]],
                [0.11, 0.3, 0.09, 0.5],
                ["mono", "mono", "cell", "mono"],
            ),
            Spacer(1, 8),
            CondPageBreak(40),
            _p("Report snapshot SHA-256", "h3"),
            _p(self.report.sha256, "mono"),
        )

    def build(self) -> list:
        self.add(NextPageTemplate("body"), PageBreak())
        self.summary()
        self.scope()
        self.evidence()
        self.explanations()
        self.tests()
        self.findings()
        self.actions()
        self.verification()
        self.appendix()
        return self.flow


def render_pdf(report: Report) -> bytes:
    snapshot = normalize_snapshot(report.snapshot)
    pages: dict[int, int] = {}
    total = 0
    output = b""
    # Page numbers are only known after a layout, so the second pass prints them on the cover and footers.
    for _ in range(2):
        buffer = io.BytesIO()
        document = Document(buffer, report, snapshot, pages, total)
        document.build(Story(report, snapshot).build())
        pages, total = document.section_pages, document.page
        output = buffer.getvalue()
    return output
