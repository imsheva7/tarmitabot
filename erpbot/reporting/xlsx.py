"""Render report data to an in-memory XLSX file. Text is never interpreted as a formula."""
from io import BytesIO
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font


def build_workbook(report):
    workbook=Workbook(write_only=True)
    try:
        for sheet in report.sheets:
            ws=workbook.create_sheet(sheet.title)
            ws.sheet_view.rightToLeft=True
            ws.freeze_panes='A2'
            headers=[]
            for value in sheet.headers:
                cell=WriteOnlyCell(ws,value=value)
                cell.font=Font(bold=True)
                cell.data_type='s'
                headers.append(cell)
            ws.append(headers)
            for row in sheet.rows:
                cells=[]
                for value in row:
                    if isinstance(value,str):
                        value=ILLEGAL_CHARACTERS_RE.sub('',value)
                    cell=WriteOnlyCell(ws,value=value)
                    if isinstance(value,str): cell.data_type='s'
                    cells.append(cell)
                ws.append(cells)
        stream=BytesIO()
        workbook.save(stream)
        return stream.getvalue()
    finally:
        workbook.close()
