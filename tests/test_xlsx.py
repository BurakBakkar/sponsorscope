from sponsorscope.registers.xlsx import cell_int, cell_str, sheet_rows
from tests.xlsx_fixtures import make_xlsx


def test_sheet_rows_round_trip():
    data = make_xlsx([["Employer Name", "Total"], ["  Acme Ltd ", 3], ["Beta", None]])
    rows = list(sheet_rows(data))
    assert [cell_str(r[0]) for r in rows] == ["Employer Name", "Acme Ltd", "Beta"]
    assert [cell_int(r[1]) for r in rows[1:]] == [3, 0]


def test_cell_helpers():
    assert cell_str(None) == "" and cell_str(1.0) == "1.0" and cell_str("  x\xa0") == "x"
    assert cell_int("") == 0 and cell_int(2.0) == 2 and cell_int("7") == 7 and cell_int("n/a") == 0
