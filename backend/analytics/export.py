"""
Export Analytics - PDF and Excel Report Generation
Professional formatted reports with charts and branding
"""

from typing import Dict, Any, List
from datetime import datetime
from io import BytesIO
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
import logging

logger = logging.getLogger(__name__)


class ReportExporter:
    """Export analytics reports to PDF and Excel formats"""
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
        logger.info("ReportExporter initialized")
    
    def export_pdf(self, report_data: Dict[str, Any]) -> bytes:
        """
        Export report as PDF with charts and formatting
        
        Args:
            report_data: Report data dictionary
        
        Returns:
            PDF bytes
        """
        try:
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=letter,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=18
            )
            
            # Build document elements
            story = []
            
            # Title page
            story.extend(self._create_title_page(report_data))
            story.append(PageBreak())
            
            # Executive summary
            story.extend(self._create_executive_summary(report_data))
            story.append(Spacer(1, 0.3*inch))
            
            # KPI section
            story.extend(self._create_kpi_section(report_data))
            story.append(Spacer(1, 0.3*inch))
            
            # Charts section
            if 'charts' in report_data and report_data['charts']:
                story.extend(self._create_charts_section(report_data['charts']))
                story.append(Spacer(1, 0.3*inch))
            
            # Detailed metrics table
            story.extend(self._create_metrics_table(report_data))
            
            # Footer
            story.append(PageBreak())
            story.extend(self._create_footer(report_data))
            
            # Build PDF
            doc.build(story)
            
            pdf_bytes = buffer.getvalue()
            buffer.close()
            
            logger.info(f"PDF report generated: {len(pdf_bytes)} bytes")
            return pdf_bytes
            
        except Exception as e:
            logger.error(f"Error generating PDF: {str(e)}")
            raise
    
    def export_excel(self, report_data: Dict[str, Any]) -> bytes:
        """
        Export report as Excel with formatted sheets
        
        Args:
            report_data: Report data dictionary
        
        Returns:
            Excel bytes
        """
        try:
            buffer = BytesIO()
            
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                # Get workbook and add formats
                workbook = writer.book
                
                # Define formats
                header_format = workbook.add_format({
                    'bold': True,
                    'bg_color': '#4472C4',
                    'font_color': 'white',
                    'border': 1,
                    'align': 'center',
                    'valign': 'vcenter'
                })
                
                title_format = workbook.add_format({
                    'bold': True,
                    'font_size': 16,
                    'align': 'center'
                })
                
                number_format = workbook.add_format({
                    'num_format': '#,##0',
                    'border': 1
                })
                
                percent_format = workbook.add_format({
                    'num_format': '0.00%',
                    'border': 1
                })
                
                currency_format = workbook.add_format({
                    'num_format': '$#,##0.00',
                    'border': 1
                })
                
                # Summary sheet
                summary_df = self._create_summary_dataframe(report_data)
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
                summary_sheet = writer.sheets['Summary']
                
                # Format summary sheet
                summary_sheet.write(0, 0, report_data.get('title', 'Report'), title_format)
                summary_sheet.write(1, 0, f"Generated: {report_data.get('generated_at', '')}")
                
                for col_num, value in enumerate(summary_df.columns.values):
                    summary_sheet.write(3, col_num, value, header_format)
                
                summary_sheet.set_column('A:A', 25)
                summary_sheet.set_column('B:B', 15)
                
                # KPIs sheet
                if 'kpis' in report_data:
                    kpis_df = pd.DataFrame([report_data['kpis']])
                    kpis_df.to_excel(writer, sheet_name='KPIs', index=False)
                    kpis_sheet = writer.sheets['KPIs']
                    
                    # Format headers
                    for col_num, value in enumerate(kpis_df.columns.values):
                        kpis_sheet.write(0, col_num, value, header_format)
                        kpis_sheet.set_column(col_num, col_num, 15)
                
                # Time series data (if available)
                if 'charts' in report_data and report_data['charts']:
                    chart_data = report_data['charts']
                    if 'labels' in chart_data and 'datasets' in chart_data:
                        time_df = pd.DataFrame({
                            'Period': chart_data['labels'],
                            'Value': chart_data['datasets'][0]['data']
                        })
                        time_df.to_excel(writer, sheet_name='Time Series', index=False)
                        time_sheet = writer.sheets['Time Series']
                        
                        # Format
                        for col_num, value in enumerate(time_df.columns.values):
                            time_sheet.write(0, col_num, value, header_format)
                        
                        time_sheet.set_column('A:A', 15)
                        time_sheet.set_column('B:B', 12)
                        
                        # Add chart
                        chart = workbook.add_chart({'type': 'line'})
                        chart.add_series({
                            'categories': ['Time Series', 1, 0, len(time_df), 0],
                            'values': ['Time Series', 1, 1, len(time_df), 1],
                            'name': 'Trend'
                        })
                        chart.set_title({'name': 'Performance Over Time'})
                        chart.set_x_axis({'name': 'Period'})
                        chart.set_y_axis({'name': 'Value'})
                        time_sheet.insert_chart('D2', chart)
                
                # Filters sheet (metadata)
                if 'filters' in report_data:
                    filters_df = pd.DataFrame([
                        {'Filter': k, 'Value': str(v)}
                        for k, v in report_data['filters'].items()
                    ])
                    filters_df.to_excel(writer, sheet_name='Filters', index=False)
                    filters_sheet = writer.sheets['Filters']
                    
                    for col_num, value in enumerate(filters_df.columns.values):
                        filters_sheet.write(0, col_num, value, header_format)
                    
                    filters_sheet.set_column('A:A', 20)
                    filters_sheet.set_column('B:B', 30)
            
            excel_bytes = buffer.getvalue()
            buffer.close()
            
            logger.info(f"Excel report generated: {len(excel_bytes)} bytes")
            return excel_bytes
            
        except Exception as e:
            logger.error(f"Error generating Excel: {str(e)}")
            raise
    
    # Private PDF helper methods
    
    def _setup_custom_styles(self):
        """Setup custom paragraph styles"""
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#2C3E50'),
            spaceAfter=30,
            alignment=TA_CENTER
        ))
        
        self.styles.add(ParagraphStyle(
            name='SectionHeading',
            parent=self.styles['Heading2'],
            fontSize=16,
            textColor=colors.HexColor('#34495E'),
            spaceAfter=12,
            spaceBefore=12
        ))
        
        self.styles.add(ParagraphStyle(
            name='KPIValue',
            parent=self.styles['Normal'],
            fontSize=28,
            textColor=colors.HexColor('#27AE60'),
            alignment=TA_CENTER,
            spaceAfter=6
        ))
        
        self.styles.add(ParagraphStyle(
            name='KPILabel',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#7F8C8D'),
            alignment=TA_CENTER
        ))
    
    def _create_title_page(self, report_data: Dict) -> List:
        """Create PDF title page"""
        elements = []
        
        # Add logo space (you can add actual logo here)
        elements.append(Spacer(1, 1*inch))
        
        # Title
        title = Paragraph(
            report_data.get('title', 'Analytics Report'),
            self.styles['CustomTitle']
        )
        elements.append(title)
        elements.append(Spacer(1, 0.3*inch))
        
        # Period
        if 'period' in report_data:
            period = report_data['period']
            period_text = f"Period: {period.get('start', 'N/A')} to {period.get('end', 'N/A')}"
            elements.append(Paragraph(period_text, self.styles['Normal']))
            elements.append(Spacer(1, 0.2*inch))
        
        # Generated date
        generated_text = f"Generated: {report_data.get('generated_at', datetime.utcnow().isoformat())}"
        elements.append(Paragraph(generated_text, self.styles['Normal']))
        
        return elements
    
    def _create_executive_summary(self, report_data: Dict) -> List:
        """Create executive summary section"""
        elements = []
        
        elements.append(Paragraph("Executive Summary", self.styles['SectionHeading']))
        
        if 'summary' in report_data:
            summary = Paragraph(report_data['summary'], self.styles['Normal'])
            elements.append(summary)
        
        return elements
    
    def _create_kpi_section(self, report_data: Dict) -> List:
        """Create KPI cards section"""
        elements = []
        
        elements.append(Paragraph("Key Performance Indicators", self.styles['SectionHeading']))
        
        if 'kpis' not in report_data:
            return elements
        
        kpis = report_data['kpis']
        
        # Create KPI table (3 columns)
        kpi_data = []
        kpi_items = list(kpis.items())
        
        for i in range(0, len(kpi_items), 3):
            row = []
            for j in range(3):
                if i + j < len(kpi_items):
                    key, value = kpi_items[i + j]
                    # Format value
                    if isinstance(value, float):
                        if 'rate' in key.lower() or 'percent' in key.lower():
                            formatted_value = f"{value:.2f}%"
                        elif 'revenue' in key.lower() or 'cost' in key.lower() or 'value' in key.lower():
                            formatted_value = f"${value:,.2f}"
                        else:
                            formatted_value = f"{value:,.2f}"
                    else:
                        formatted_value = f"{value:,}"
                    
                    cell = [
                        Paragraph(formatted_value, self.styles['KPIValue']),
                        Paragraph(key.replace('_', ' ').title(), self.styles['KPILabel'])
                    ]
                    row.append(cell)
                else:
                    row.append(['', ''])
            
            kpi_data.append(row)
        
        # Flatten for table
        table_data = []
        for row in kpi_data:
            table_data.append([cell[0] for cell in row])
            table_data.append([cell[1] for cell in row])
        
        kpi_table = Table(table_data, colWidths=[2.2*inch, 2.2*inch, 2.2*inch])
        kpi_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 1, colors.lightgrey),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8F9FA'))
        ]))
        
        elements.append(kpi_table)
        
        return elements
    
    def _create_charts_section(self, chart_data: Dict) -> List:
        """Create charts section (simplified)"""
        elements = []
        
        elements.append(Paragraph("Performance Trends", self.styles['SectionHeading']))
        
        # In a production system, you'd generate actual charts here
        # For now, we'll add a placeholder
        chart_text = Paragraph(
            "Chart visualization data included in Excel export",
            self.styles['Normal']
        )
        elements.append(chart_text)
        
        return elements
    
    def _create_metrics_table(self, report_data: Dict) -> List:
        """Create detailed metrics table"""
        elements = []
        
        elements.append(Paragraph("Detailed Metrics", self.styles['SectionHeading']))
        
        if 'kpis' not in report_data:
            return elements
        
        # Create table data
        table_data = [['Metric', 'Value']]
        
        for key, value in report_data['kpis'].items():
            metric_name = key.replace('_', ' ').title()
            
            # Format value
            if isinstance(value, float):
                if 'rate' in key.lower():
                    formatted_value = f"{value:.2f}%"
                elif 'revenue' in key.lower() or 'cost' in key.lower():
                    formatted_value = f"${value:,.2f}"
                else:
                    formatted_value = f"{value:,.2f}"
            else:
                formatted_value = f"{value:,}"
            
            table_data.append([metric_name, formatted_value])
        
        metrics_table = Table(table_data, colWidths=[4*inch, 2*inch])
        metrics_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4472C4')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(metrics_table)
        
        return elements
    
    def _create_footer(self, report_data: Dict) -> List:
        """Create report footer"""
        elements = []
        
        footer_text = Paragraph(
            f"<i>This report was automatically generated by Campaign Platform Analytics</i>",
            self.styles['Normal']
        )
        elements.append(footer_text)
        
        if 'filters' in report_data and report_data['filters']:
            elements.append(Spacer(1, 0.2*inch))
            filters_text = "Filters applied: " + ", ".join(
                f"{k}: {v}" for k, v in report_data['filters'].items()
            )
            elements.append(Paragraph(filters_text, self.styles['Normal']))
        
        return elements
    
    # Private Excel helper methods
    
    def _create_summary_dataframe(self, report_data: Dict) -> pd.DataFrame:
        """Create summary DataFrame for Excel"""
        summary_data = []
        
        if 'period' in report_data:
            period = report_data['period']
            summary_data.append({
                'Section': 'Period',
                'Value': f"{period.get('start', 'N/A')} to {period.get('end', 'N/A')}"
            })
            summary_data.append({
                'Section': 'Days',
                'Value': period.get('days', 'N/A')
            })
        
        if 'kpis' in report_data:
            for key, value in report_data['kpis'].items():
                summary_data.append({
                    'Section': key.replace('_', ' ').title(),
                    'Value': value
                })
        
        return pd.DataFrame(summary_data)


# Global instance
report_exporter = ReportExporter()


# Convenience functions
def export_pdf(report_data: Dict[str, Any]) -> bytes:
    """Export report as PDF"""
    return report_exporter.export_pdf(report_data)


def export_excel(report_data: Dict[str, Any]) -> bytes:
    """Export report as Excel"""
    return report_exporter.export_excel(report_data)
