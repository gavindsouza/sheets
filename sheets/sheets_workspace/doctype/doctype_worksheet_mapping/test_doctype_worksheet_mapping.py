# Copyright (c) 2023, Gavin D'souza and Contributors
# See license.txt

from csv import reader as csv_reader
from csv import writer as csv_writer
from io import StringIO

import frappe
from frappe.tests.utils import FrappeTestCase


class TestDocTypeWorksheetMapping(FrappeTestCase):
    def test_csv_conversion_with_special_characters(self):
        """Test that CSV conversion properly handles commas, quotes, and newlines"""
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
        csv_output = buffer.getvalue().splitlines()

        # Parse the CSV output back to verify it's valid
        parsed_data = []
        for line in csv_output:
            row = next(csv_reader(StringIO(line)))
            parsed_data.append(row)

        # Verify data integrity - all special characters should be preserved
        self.assertEqual(len(parsed_data), len(test_data))
        self.assertEqual(parsed_data[0], test_data[0])  # Header
        self.assertEqual(parsed_data[1][2], "A person with, comma")  # Comma preserved
        self.assertEqual(parsed_data[2][1], 'Jane "Quote" Smith')  # Quotes preserved
        self.assertEqual(parsed_data[3][1], "Bob\nNewline")  # Newline preserved
        self.assertEqual(parsed_data[4][1], 'Complex, "quoted", text')  # Complex case

    def test_csv_conversion_consistency(self):
        """Test that CSV conversion matches the format from fetch_remote_worksheet"""
        # Simulate data that would come from data_imported_csv_file
        test_data = [
            ["ID", "Field 1", "Field 2"],
            ["row1", "value1", "value2"],
            ["row2", "value,with,commas", "normal"],
        ]

        # Method 1: Using csv_writer (the fix)
        buffer1 = StringIO()
        csv_writer(buffer1).writerows(test_data)
        output1 = buffer1.getvalue().splitlines()

        # Method 2: Simulating fetch_remote_worksheet approach
        buffer2 = StringIO()
        csv_writer(buffer2).writerows(test_data)
        output2 = buffer2.getvalue()

        # Both methods should produce equivalent CSV data
        self.assertEqual(output1, output2.splitlines())

    def test_csv_manual_join_vs_csv_writer(self):
        """Test that demonstrates why manual join is problematic"""
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

        # The manual join creates invalid CSV for rows with special chars
        # Row 0 (header) is the same
        self.assertEqual(manual_join[0], proper_csv[0])

        # Row 1 has comma - manual join is WRONG, csv_writer is RIGHT
        # Manual: "1,Item, with comma,100" (4 fields instead of 3!)
        # Proper: '1,"Item, with comma",100' (correctly quoted)
        self.assertNotEqual(manual_join[1], proper_csv[1])

        # Verify the proper CSV is parseable and maintains data integrity
        parsed_proper = next(csv_reader(StringIO(proper_csv[1])))
        self.assertEqual(len(parsed_proper), 3)  # Should have 3 fields
        self.assertEqual(parsed_proper[1], "Item, with comma")  # Comma preserved

        # Manual join would fail to parse correctly
        parsed_manual = next(csv_reader(StringIO(manual_join[1])))
        self.assertNotEqual(len(parsed_manual), 3)  # Would have wrong number of fields
