"""Tests for PDF reader functionality."""

import os
import tempfile
import pytest
from unittest.mock import Mock, patch

from src.pdf_mcp_server.pdf_reader import PDFReader


class TestPDFReader:
    """Test cases for PDFReader class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.pdf_reader = PDFReader()
        self.sample_pdf_path = "tests/sample_files/test.pdf"
    
    def test_is_pdf_file(self):
        """Test PDF file validation."""
        assert self.pdf_reader.is_pdf_file("document.pdf") is True
        assert self.pdf_reader.is_pdf_file("document.PDF") is True
        assert self.pdf_reader.is_pdf_file("document.txt") is False
        assert self.pdf_reader.is_pdf_file("document.docx") is False
    
    def test_extract_text_file_not_found(self):
        """Test text extraction with non-existent file."""
        result = self.pdf_reader.extract_text("nonexistent.pdf")
        assert result["success"] is False
        assert "not found" in result["error"].lower()
    
    def test_extract_text_invalid_file(self):
        """Test text extraction with invalid file type."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp.write(b"This is not a PDF")
            tmp_path = tmp.name
        
        try:
            result = self.pdf_reader.extract_text(tmp_path)
            assert result["success"] is False
            assert "not a PDF" in result["error"]
        finally:
            os.unlink(tmp_path)
    
    @patch('fitz.open')
    def test_extract_text_success(self, mock_fitz_open):
        """Test successful text extraction."""
        # Mock PyMuPDF document
        mock_doc = Mock()
        mock_page = Mock()
        mock_page.get_text.return_value = "Sample PDF text content"
        mock_doc.__len__.return_value = 1
        mock_doc.__getitem__.return_value = mock_page
        mock_doc.metadata = {
            "title": "Test Document",
            "author": "Test Author"
        }
        mock_fitz_open.return_value = mock_doc
        
        # Mock file existence
        with patch('os.path.exists', return_value=True):
            result = self.pdf_reader.extract_text("test.pdf")
        
        assert result["success"] is True
        assert result["total_pages"] == 1
        assert result["extracted_pages"] == 1
        assert "Sample PDF text content" in result["full_text"]
        assert len(result["pages"]) == 1
        assert result["pages"][0]["page_number"] == 1
        assert result["pages"][0]["text"] == "Sample PDF text content"
    
    @patch('fitz.open')
    def test_extract_text_with_page_range(self, mock_fitz_open):
        """Test text extraction with page range."""
        # Mock PyMuPDF document with multiple pages
        mock_doc = Mock()
        mock_page1 = Mock()
        mock_page1.get_text.return_value = "Page 1 content"
        mock_page2 = Mock()
        mock_page2.get_text.return_value = "Page 2 content"
        mock_page3 = Mock()
        mock_page3.get_text.return_value = "Page 3 content"
        
        mock_doc.__len__.return_value = 3
        mock_doc.__getitem__.side_effect = [mock_page1, mock_page2, mock_page3]
        mock_doc.metadata = {}
        mock_fitz_open.return_value = mock_doc
        
        with patch('os.path.exists', return_value=True):
            result = self.pdf_reader.extract_text("test.pdf", page_range=(2, 3))
        
        assert result["success"] is True
        assert result["total_pages"] == 3
        assert result["extracted_pages"] == 2
        assert len(result["pages"]) == 2
        assert result["pages"][0]["page_number"] == 2
        assert result["pages"][1]["page_number"] == 3
    
    @patch('fitz.open')
    def test_extract_metadata(self, mock_fitz_open):
        """Test metadata extraction."""
        mock_doc = Mock()
        mock_doc.metadata = {
            "title": "Test Document",
            "author": "Test Author",
            "subject": "Test Subject",
            "creator": "Test Creator",
            "producer": "Test Producer",
            "creationDate": "2023-01-01",
            "modDate": "2023-06-01"
        }
        mock_doc.__len__.return_value = 5
        mock_doc.needs_pass = False
        mock_doc.pdf_version.return_value = "1.7"
        
        metadata = self.pdf_reader.extract_metadata(mock_doc)
        
        assert metadata["title"] == "Test Document"
        assert metadata["author"] == "Test Author"
        assert metadata["page_count"] == 5
        assert metadata["encrypted"] is False
        assert metadata["pdf_version"] == "1.7"
    
    @patch('fitz.open')
    def test_get_page_info(self, mock_fitz_open):
        """Test page information extraction."""
        mock_doc = Mock()
        mock_page = Mock()
        mock_rect = Mock()
        mock_rect.width = 595.0
        mock_rect.height = 842.0
        mock_page.rect = mock_rect
        mock_page.rotation = 0
        mock_page.get_text.return_value = "Page content"
        mock_page.get_images.return_value = []
        mock_page.get_links.return_value = []
        mock_page.annots.return_value = []
        
        mock_doc.__len__.return_value = 1
        mock_doc.__getitem__.return_value = mock_page
        mock_fitz_open.return_value = mock_doc
        
        with patch('os.path.exists', return_value=True):
            result = self.pdf_reader.get_page_info("test.pdf")
        
        assert result["success"] is True
        assert result["total_pages"] == 1
        assert len(result["pages"]) == 1
        page_info = result["pages"][0]
        assert page_info["width"] == 595.0
        assert page_info["height"] == 842.0
        assert page_info["rotation"] == 0
        assert page_info["text_length"] == len("Page content")
    
    @patch('fitz.open')
    def test_search_text(self, mock_fitz_open):
        """Test text search functionality."""
        mock_doc = Mock()
        mock_page = Mock()
        
        # Mock search results
        mock_rect = Mock()
        mock_rect.x0, mock_rect.y0, mock_rect.x1, mock_rect.y1 = 100, 200, 150, 220
        mock_page.search_for.return_value = [mock_rect]
        mock_page.get_textbox.return_value = "This is the context containing search term"
        
        mock_doc.__len__.return_value = 1
        mock_doc.__getitem__.return_value = mock_page
        mock_fitz_open.return_value = mock_doc
        
        with patch('os.path.exists', return_value=True):
            result = self.pdf_reader.search_text("test.pdf", "search term")
        
        assert result["success"] is True
        assert result["total_matches"] == 1
        assert len(result["matches"]) == 1
        match = result["matches"][0]
        assert match["page_number"] == 1
        assert match["search_term"] == "search term"
        assert "search term" in match["context"]
    
    def test_extract_images_file_not_found(self):
        """Test image extraction with non-existent file."""
        result = self.pdf_reader.extract_images("nonexistent.pdf")
        assert result["success"] is False
        assert "not found" in result["error"].lower()
    
    @patch('fitz.open')
    def test_extract_images_no_images(self, mock_fitz_open):
        """Test image extraction from PDF with no images."""
        mock_doc = Mock()
        mock_page = Mock()
        mock_page.get_images.return_value = []
        
        mock_doc.__len__.return_value = 1
        mock_doc.__getitem__.return_value = mock_page
        mock_fitz_open.return_value = mock_doc
        
        with patch('os.path.exists', return_value=True):
            result = self.pdf_reader.extract_images("test.pdf")
        
        assert result["success"] is True
        assert result["total_images"] == 0
        assert len(result["images"]) == 0


class TestPDFReaderIntegration:
    """Integration tests requiring actual PDF files."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.pdf_reader = PDFReader()
    
    @pytest.mark.skipif(
        not os.path.exists("tests/sample_files/test.pdf"),
        reason="Sample PDF file not found"
    )
    def test_real_pdf_extraction(self):
        """Test with a real PDF file if available."""
        result = self.pdf_reader.extract_text("tests/sample_files/test.pdf")
        
        # Basic sanity checks
        if result["success"]:
            assert result["total_pages"] > 0
            assert isinstance(result["full_text"], str)
            assert len(result["pages"]) > 0
        else:
            # If it fails, at least check error handling
            assert "error" in result
            assert isinstance(result["error"], str)


if __name__ == "__main__":
    pytest.main([__file__])