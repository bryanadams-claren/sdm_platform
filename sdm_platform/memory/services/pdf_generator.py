"""PDF generation service for conversation summaries."""

import logging
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph
from reportlab.platypus import SimpleDocTemplate
from reportlab.platypus import Spacer

from sdm_platform.memory.schemas import ConversationSummaryData

logger = logging.getLogger(__name__)


class ConversationSummaryPDFGenerator:
    """Generates PDF summary documents using ReportLab."""

    def __init__(self, summary_data: ConversationSummaryData):
        """
        Initialize the PDF generator.

        Args:
            summary_data: Complete summary data for PDF generation
        """
        self.data = summary_data
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Set up custom paragraph styles."""
        # Header style
        self.styles.add(
            ParagraphStyle(
                name="CustomTitle",
                parent=self.styles["Heading1"],
                fontSize=24,
                textColor=colors.HexColor("#1e3a8a"),
                spaceAfter=6,
                spaceBefore=12,
            )
        )

        # Subheader style
        self.styles.add(
            ParagraphStyle(
                name="SectionHeader",
                parent=self.styles["Heading2"],
                fontSize=14,
                textColor=colors.HexColor("#1e3a8a"),
                spaceAfter=6,
                spaceBefore=12,
                borderWidth=0,
                borderColor=colors.HexColor("#1e3a8a"),
                borderPadding=0,
            )
        )

        # Body style
        self.styles.add(
            ParagraphStyle(
                name="CustomBody",
                parent=self.styles["Normal"],
                fontSize=11,
                leading=14,
                spaceAfter=8,
            )
        )

        # Quote style
        self.styles.add(
            ParagraphStyle(
                name="Quote",
                parent=self.styles["Normal"],
                fontSize=10,
                italic=True,
                leftIndent=20,
                rightIndent=20,
                textColor=colors.HexColor("#4b5563"),
                spaceAfter=6,
            )
        )

        # Bullet point style
        self.styles.add(
            ParagraphStyle(
                name="BulletPoint",
                parent=self.styles["Normal"],
                fontSize=10,
                leftIndent=20,
                spaceAfter=4,
                bulletIndent=10,
            )
        )

    def generate(self) -> BytesIO:
        """
        Generate PDF and return as BytesIO buffer.

        Returns:
            BytesIO buffer containing the generated PDF
        """
        buffer = BytesIO()

        # Create PDF document
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72,
        )

        # Build content
        story = []

        # Header section
        story.extend(self._build_header())
        story.append(Spacer(1, 0.3 * inch))

        # Narrative summary section
        story.extend(self._build_narrative_section())
        story.append(Spacer(1, 0.3 * inch))

        # Key discussion points section
        story.extend(self._build_discussion_points_section())

        # Selected option section (if applicable)
        if self.data.selected_option:
            story.append(Spacer(1, 0.3 * inch))
            story.extend(self._build_selected_option_section())

        # Build PDF
        doc.build(story)

        buffer.seek(0)
        logger.info(
            "Generated PDF for conversation %s (%d bytes)",
            self.data.conversation_id,
            len(buffer.getvalue()),
        )
        return buffer

    def _build_header(self) -> list:
        """Build the header section of the PDF."""
        content = []

        # Logo placeholder / Brand
        content.append(
            Paragraph(
                "CLAREN HEALTH",
                ParagraphStyle(
                    name="Brand",
                    fontSize=16,
                    textColor=colors.HexColor("#1e3a8a"),
                    spaceAfter=12,
                    fontName="Helvetica-Bold",
                ),
            )
        )

        # Title
        content.append(
            Paragraph(
                f"{self.data.journey_title} - Conversation Summary",
                self.styles["CustomTitle"],
            )
        )

        # Patient info
        content.append(
            Paragraph(
                f"<b>Prepared for:</b> {self.data.user_name}",
                self.styles["CustomBody"],
            )
        )

        # Date
        content.append(
            Paragraph(
                f"<b>Date:</b> {self.data.generated_at.strftime('%B %d, %Y')}",
                self.styles["CustomBody"],
            )
        )

        return content

    def _build_narrative_section(self) -> list:
        """Build the narrative summary section."""
        content = []

        content.append(
            Paragraph("YOUR CONVERSATION SUMMARY", self.styles["SectionHeader"])
        )

        # Split narrative into paragraphs
        if self.data.narrative_summary:
            paragraphs = self.data.narrative_summary.split("\n\n")
            content.extend(
                Paragraph(para.strip(), self.styles["CustomBody"])
                for para in paragraphs
                if para.strip()
            )
        else:
            content.append(
                Paragraph(
                    "No narrative summary available.",
                    self.styles["CustomBody"],
                )
            )

        return content

    def _build_discussion_points_section(self) -> list:
        """Build a concise key discussion points section."""
        content = []

        content.append(Paragraph("KEY DISCUSSION POINTS", self.styles["SectionHeader"]))

        # Limit to top 2 extracted points and 1 quote per topic for brevity
        max_points = 2
        max_quotes = 1

        for point_summary in self.data.point_summaries:
            # Only include points that were addressed
            if not point_summary.extracted_points and not point_summary.relevant_quotes:
                continue

            # Point title
            content.append(
                Paragraph(
                    f"<b>{point_summary.title}</b>",
                    ParagraphStyle(
                        name="PointTitle",
                        parent=self.styles["Normal"],
                        fontSize=12,
                        textColor=colors.HexColor("#1e3a8a"),
                        spaceAfter=4,
                        spaceBefore=8,
                        fontName="Helvetica-Bold",
                    ),
                )
            )

            # Extracted points (limited)
            if point_summary.extracted_points:
                content.extend(
                    Paragraph(f"• {point}", self.styles["BulletPoint"])
                    for point in point_summary.extracted_points[:max_points]
                )

            # Single representative quote (if available)
            if point_summary.relevant_quotes:
                content.extend(
                    Paragraph(f'"{quote}"', self.styles["Quote"])
                    for quote in point_summary.relevant_quotes[:max_quotes]
                )

        return content

    def _build_selected_option_section(self) -> list:
        """Build the selected treatment option section."""
        content = []

        if not self.data.selected_option:
            return content

        opt = self.data.selected_option

        # Limit benefits/drawbacks for brevity
        max_items = 3

        content.append(
            Paragraph("PREFERRED TREATMENT APPROACH", self.styles["SectionHeader"])
        )

        content.append(Paragraph(f"<b>{opt.title}</b>", self.styles["CustomBody"]))

        if opt.description:
            content.append(Paragraph(opt.description, self.styles["CustomBody"]))

        if opt.typical_timeline:
            content.append(
                Paragraph(
                    f"<b>Expected Timeline:</b> {opt.typical_timeline}",
                    self.styles["CustomBody"],
                )
            )

        if opt.benefits:
            content.append(
                Paragraph("<b>Potential Benefits:</b>", self.styles["CustomBody"])
            )
            content.extend(
                Paragraph(f"• {benefit}", self.styles["BulletPoint"])
                for benefit in opt.benefits[:max_items]
            )

        if opt.drawbacks:
            content.append(Spacer(1, 0.1 * inch))
            content.append(
                Paragraph("<b>Considerations:</b>", self.styles["CustomBody"])
            )
            content.extend(
                Paragraph(f"• {drawback}", self.styles["BulletPoint"])
                for drawback in opt.drawbacks[:max_items]
            )

        return content
