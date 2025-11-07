#!/usr/bin/env python3
"""
Standalone test to verify CSV conversion fix without requiring Frappe framework.
This demonstrates that the csv.writer approach correctly handles special characters.
"""

from csv import reader as csv_reader
from csv import writer as csv_writer
from io import StringIO


def test_csv_conversion_with_special_characters():
    """Test that CSV conversion properly handles commas, quotes, and newlines"""
    print("Testing CSV conversion with special characters...")

    # Test data with special characters that need proper CSV escaping
    test_data = [
        ["ID", "Name", "Description"],
        ["1", "John Doe", "A person with, comma"],
        ["2", 'Jane "Quote" Smith', "Normal text"],
        ["3", "Bob\nNewline", "Text with\nnewline"],
        ["4", 'Complex, "quoted", text', 'Multiple "issues" here'],
    ]

    # Convert using the proper csv module method (like the fix)
    buffer = StringIO()
    csv_writer(buffer).writerows(test_data)
    csv_string = buffer.getvalue()

    # Parse the CSV output back to verify it's valid
    parsed_data = list(csv_reader(StringIO(csv_string)))

    print(f"  Generated {len(parsed_data)} CSV rows")

    # Verify data integrity
    assert len(parsed_data) == len(test_data), "Row count mismatch"
    assert parsed_data[0] == test_data[0], "Header mismatch"
    assert parsed_data[1][2] == "A person with, comma", "Comma not preserved"
    assert parsed_data[2][1] == 'Jane "Quote" Smith', "Quotes not preserved"
    assert parsed_data[3][1] == "Bob\nNewline", "Newline not preserved"
    assert parsed_data[4][1] == 'Complex, "quoted", text', "Complex case failed"

    print("  ✓ All special characters handled correctly")
    return True


def test_manual_join_vs_csv_writer():
    """Demonstrate why manual join is problematic"""
    print("\nComparing manual join vs csv.writer...")

    test_data = [
        ["ID", "Name", "Value"],
        ["1", "Item, with comma", "100"],
        ["2", 'Item "with quotes"', "200"],
    ]

    # Manual join (the old hack method) - INCORRECT
    manual_join = [",".join(row) for row in test_data]

    # CSV writer method (the fix) - CORRECT
    buffer = StringIO()
    csv_writer(buffer).writerows(test_data)
    proper_csv = buffer.getvalue().splitlines()

    print(f"\n  Row with comma:")
    print(f"    Manual join:  {manual_join[1]}")
    print(f"    csv.writer:   {proper_csv[1]}")

    # Parse the proper CSV
    parsed_proper = next(csv_reader(StringIO(proper_csv[1])))
    print(f"    Parsed (csv.writer): {parsed_proper} - {len(parsed_proper)} fields ✓")

    # Parse the manual join - will fail
    parsed_manual = list(csv_reader(StringIO(manual_join[1])))[0]
    print(f"    Parsed (manual join): {parsed_manual} - {len(parsed_manual)} fields ✗")

    assert len(parsed_proper) == 3, "csv.writer should produce 3 fields"
    assert len(parsed_manual) != 3, "Manual join produces wrong field count"
    assert parsed_proper[1] == "Item, with comma", "csv.writer should preserve comma"

    print("\n  ✓ csv.writer correctly handles special characters")
    print("  ✓ Manual join creates invalid CSV")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("CSV Conversion Fix Validation")
    print("=" * 60)

    try:
        test_csv_conversion_with_special_characters()
        test_manual_join_vs_csv_writer()
        print("\n" + "=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        exit(1)
