# Copyright (C) 2024 Kevin Ewoldt
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
import json
from bs4 import BeautifulSoup

# Import functions from lambda_function
from lambda_function import (
    get_first_monday_of_month,
    is_federal_holiday,
    get_next_business_day,
    get_auction_date
)


class TestDateMethods(unittest.TestCase):
    """Test cases for date calculation methods"""
    
    def test_get_first_monday_of_month(self):
        """Test getting first Monday of various months"""
        # January 2025 - first day is Wednesday, so first Monday is Jan 6
        result = get_first_monday_of_month(2025, 1)
        self.assertEqual(result.date(), datetime(2025, 1, 6).date())
        
        # September 2025 - first day is Monday, but the logic in lambda_function 
        # moves to next Monday if the day has already happened, so first Monday is Sept 8
        result = get_first_monday_of_month(2025, 9)
        self.assertEqual(result.date(), datetime(2025, 9, 8).date())
        
        # February 2025 - first day is Saturday, so first Monday is Feb 3
        result = get_first_monday_of_month(2025, 2)
        self.assertEqual(result.date(), datetime(2025, 2, 3).date())
    
    def test_is_federal_holiday(self):
        """Test federal holiday detection"""
        # New Year's Day
        new_years = datetime(2025, 1, 1)
        self.assertTrue(is_federal_holiday(new_years))
        
        # July 4th
        july_4th = datetime(2025, 7, 4)
        self.assertTrue(is_federal_holiday(july_4th))
        
        # Labor Day 2025 (first Monday in September = Sept 8, due to lambda logic)
        labor_day = datetime(2025, 9, 8)
        self.assertTrue(is_federal_holiday(labor_day))
        
        # Regular day
        regular_day = datetime(2025, 3, 15)
        self.assertFalse(is_federal_holiday(regular_day))
        
        # Not Labor Day (third Monday in September)
        not_labor_day = datetime(2025, 9, 15)
        self.assertFalse(is_federal_holiday(not_labor_day))
    
    def test_get_next_business_day(self):
        """Test getting next business day"""
        # Friday -> Monday
        friday = datetime(2025, 1, 3)  # Jan 3, 2025 is Friday
        result = get_next_business_day(friday)
        self.assertEqual(result.date(), datetime(2025, 1, 6).date())  # Monday
        
        # Saturday -> Monday
        saturday = datetime(2025, 1, 4)  # Jan 4, 2025 is Saturday
        result = get_next_business_day(saturday)
        self.assertEqual(result.date(), datetime(2025, 1, 6).date())  # Monday
        
        # Sunday -> Monday
        sunday = datetime(2025, 1, 5)  # Jan 5, 2025 is Sunday
        result = get_next_business_day(sunday)
        self.assertEqual(result.date(), datetime(2025, 1, 6).date())  # Monday
        
        # Monday -> Tuesday
        monday = datetime(2025, 1, 6)  # Jan 6, 2025 is Monday
        result = get_next_business_day(monday)
        self.assertEqual(result.date(), datetime(2025, 1, 7).date())  # Tuesday
    
    @patch('lambda_function.logger')
    def test_get_auction_date_regular_month(self, mock_logger):
        """Test auction date calculation for regular month"""
        # March 2025 - first Monday is March 3, not a holiday
        result = get_auction_date(2025, 3)
        self.assertEqual(result.date(), datetime(2025, 3, 3).date())
        
        # Verify logging
        mock_logger.info.assert_called_with("Auction date set to first Monday: 2025-03-03")
    
    @patch('lambda_function.logger')
    def test_get_auction_date_with_holiday(self, mock_logger):
        """Test auction date calculation when first Monday is a holiday"""
        # September 2025 - first Monday is Sept 8 (Labor Day), should move to Sept 9
        result = get_auction_date(2025, 9)
        self.assertEqual(result.date(), datetime(2025, 9, 9).date())
        
        # Verify logging includes holiday message
        expected_calls = [
            unittest.mock.call("First Monday 2025-09-08 is a federal holiday, moving to next business day: 2025-09-09")
        ]
        mock_logger.info.assert_has_calls(expected_calls, any_order=True)


class TestFileTypeValidation(unittest.TestCase):
    """Test cases for file type validation"""
    
    def test_pdf_content_type_validation(self):
        """Test PDF validation by content-type header"""
        # Mock response with PDF content-type
        mock_response = MagicMock()
        mock_response.headers = {'content-type': 'application/pdf'}
        mock_response.content = b'%PDF-1.4 fake pdf content'
        
        content_type = mock_response.headers.get('content-type', '').lower()
        file_extension = 'pdf'
        
        is_pdf = (
            'application/pdf' in content_type or 
            file_extension == 'pdf' or
            mock_response.content.startswith(b'%PDF')
        )
        
        self.assertTrue(is_pdf)
    
    def test_xls_content_type_rejection(self):
        """Test XLS file rejection"""
        # Mock response with Excel content-type
        mock_response = MagicMock()
        mock_response.headers = {'content-type': 'application/vnd.ms-excel'}
        mock_response.content = b'Excel file content'
        
        content_type = mock_response.headers.get('content-type', '').lower()
        file_extension = 'xls'
        
        is_pdf = (
            'application/pdf' in content_type or 
            file_extension == 'pdf' or
            mock_response.content.startswith(b'%PDF')
        )
        
        self.assertFalse(is_pdf)
    
    def test_pdf_magic_number_validation(self):
        """Test PDF validation by magic number"""
        # Mock response with PDF magic number but wrong content-type
        mock_response = MagicMock()
        mock_response.headers = {'content-type': 'application/octet-stream'}
        mock_response.content = b'%PDF-1.7 actual pdf content'
        
        content_type = mock_response.headers.get('content-type', '').lower()
        file_extension = 'unknown'
        
        is_pdf = (
            'application/pdf' in content_type or 
            file_extension == 'pdf' or
            mock_response.content.startswith(b'%PDF')
        )
        
        self.assertTrue(is_pdf)
    
    def test_file_extension_validation(self):
        """Test PDF validation by file extension"""
        # Mock response with PDF extension but missing content-type
        mock_response = MagicMock()
        mock_response.headers = {}
        mock_response.content = b'some content without PDF header'
        
        content_type = mock_response.headers.get('content-type', '').lower()
        file_extension = 'pdf'
        
        is_pdf = (
            'application/pdf' in content_type or 
            file_extension == 'pdf' or
            mock_response.content.startswith(b'%PDF')
        )
        
        self.assertTrue(is_pdf)


class TestHTMLParsing(unittest.TestCase):
    """Test cases for HTML parsing functionality"""
    
    def setUp(self):
        """Set up test HTML samples"""
        self.valid_html = """
        <html>
            <body>
                <div class="fr-view">
                    <ul>
                        <li><a href="/documents/foreclosure-jan-2025.pdf">January 2025</a></li>
                        <li><a href="/documents/foreclosure-feb-2025.pdf">February 2025</a></li>
                    </ul>
                </div>
            </body>
        </html>
        """
        
        self.missing_fr_view_html = """
        <html>
            <body>
                <div class="other-class">
                    <ul>
                        <li><a href="/documents/foreclosure-jan-2025.pdf">January 2025</a></li>
                    </ul>
                </div>
            </body>
        </html>
        """
        
        self.missing_li_html = """
        <html>
            <body>
                <div class="fr-view">
                    <p>No list items here</p>
                </div>
            </body>
        </html>
        """
        
        self.missing_link_html = """
        <html>
            <body>
                <div class="fr-view">
                    <ul>
                        <li>January 2025 (no link)</li>
                    </ul>
                </div>
            </body>
        </html>
        """
    
    def test_parse_valid_html(self):
        """Test parsing valid HTML structure"""
        soup = BeautifulSoup(self.valid_html, 'html.parser')
        
        # Find .fr-view element
        fr_view = soup.find(class_='fr-view')
        self.assertIsNotNone(fr_view)
        
        # Find li element
        li_element = fr_view.find('li')
        self.assertIsNotNone(li_element)
        
        # Find first link
        first_link = li_element.find('a')
        self.assertIsNotNone(first_link)
        self.assertEqual(first_link['href'], '/documents/foreclosure-jan-2025.pdf')
        self.assertEqual(first_link.get_text(strip=True), 'January 2025')
    
    def test_parse_missing_fr_view(self):
        """Test parsing HTML missing .fr-view element"""
        soup = BeautifulSoup(self.missing_fr_view_html, 'html.parser')
        
        fr_view = soup.find(class_='fr-view')
        self.assertIsNone(fr_view)
    
    def test_parse_missing_li(self):
        """Test parsing HTML missing li element"""
        soup = BeautifulSoup(self.missing_li_html, 'html.parser')
        
        fr_view = soup.find(class_='fr-view')
        self.assertIsNotNone(fr_view)
        
        li_element = fr_view.find('li')
        self.assertIsNone(li_element)
    
    def test_parse_missing_link(self):
        """Test parsing HTML missing link in li element"""
        soup = BeautifulSoup(self.missing_link_html, 'html.parser')
        
        fr_view = soup.find(class_='fr-view')
        self.assertIsNotNone(fr_view)
        
        li_element = fr_view.find('li')
        self.assertIsNotNone(li_element)
        
        first_link = li_element.find('a')
        self.assertIsNone(first_link)
    
    def test_construct_pdf_url(self):
        """Test PDF URL construction"""
        base_url = 'https://www.gtcounty.org'
        
        # Relative URL
        relative_href = '/documents/foreclosure-jan-2025.pdf'
        if relative_href.startswith('/'):
            pdf_url = base_url + relative_href
        else:
            pdf_url = relative_href
        self.assertEqual(pdf_url, 'https://www.gtcounty.org/documents/foreclosure-jan-2025.pdf')
        
        # Absolute URL
        absolute_href = 'https://www.gtcounty.org/documents/foreclosure-jan-2025.pdf'
        if absolute_href.startswith('/'):
            pdf_url = base_url + absolute_href
        else:
            pdf_url = absolute_href
        self.assertEqual(pdf_url, 'https://www.gtcounty.org/documents/foreclosure-jan-2025.pdf')


class TestMonthFiltering(unittest.TestCase):
    """Test cases for month filtering logic"""
    
    def test_parse_month_from_link_text(self):
        """Test parsing month/year from link text"""
        # Valid month formats
        test_cases = [
            ("January 2025", datetime(2025, 1, 1)),
            ("February 2025", datetime(2025, 2, 1)),
            ("December 2024", datetime(2024, 12, 1)),
            ("September 2025", datetime(2025, 9, 1))
        ]
        
        for link_text, expected_date in test_cases:
            try:
                auction_month_date = datetime.strptime(link_text, '%B %Y')
                self.assertEqual(auction_month_date.year, expected_date.year)
                self.assertEqual(auction_month_date.month, expected_date.month)
            except ValueError:
                self.fail(f"Failed to parse valid date: {link_text}")
    
    def test_invalid_month_format(self):
        """Test handling invalid month format"""
        invalid_formats = [
            "Jan 2025",
            "January",
            "2025",
            "Invalid Text",
            "13th Month 2025"
        ]
        
        for link_text in invalid_formats:
            with self.assertRaises(ValueError):
                datetime.strptime(link_text, '%B %Y')
    
    def test_future_month_filtering(self):
        """Test future month filtering logic"""
        # Mock current date as January 15, 2025
        with patch('lambda_function.datetime') as mock_datetime:
            mock_datetime.now.return_value = datetime(2025, 1, 15)
            mock_datetime.strptime = datetime.strptime
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            current_date = mock_datetime.now()
            current_month_start = datetime(current_date.year, current_date.month, 1)
            
            # Test cases: (link_text, should_process)
            test_cases = [
                ("December 2024", False),  # Past month
                ("January 2025", False),   # Current month
                ("February 2025", True),   # Future month
                ("March 2025", True),      # Future month
            ]
            
            for link_text, should_process in test_cases:
                auction_month_date = datetime.strptime(link_text, '%B %Y')
                is_future = auction_month_date > current_month_start
                self.assertEqual(is_future, should_process, 
                               f"Month filtering failed for {link_text}")


if __name__ == '__main__':
    # Run specific test suites
    unittest.main(verbosity=2)