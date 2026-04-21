"""PDF reading functionality using PyMuPDF."""

import os
import io
import base64
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    raise ImportError("PyMuPDF is required. Install with: pip install PyMuPDF")

from PIL import Image


class PDFReader:
    """PDF reading and content extraction class."""
    
    def __init__(self):
        """Initialize PDF reader."""
        self.supported_formats = ['.pdf']
    
    def is_pdf_file(self, file_path: str) -> bool:
        """Check if file is a valid PDF."""
        return Path(file_path).suffix.lower() in self.supported_formats
    
    def extract_text(self, file_path: str, page_range: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
        """
        Extract text content from PDF.
        
        Args:
            file_path: Path to PDF file
            page_range: Optional tuple (start_page, end_page) for partial extraction
            
        Returns:
            Dictionary containing extracted text and metadata
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found: {file_path}")
        
        if not self.is_pdf_file(file_path):
            raise ValueError(f"File is not a PDF: {file_path}")
        
        try:
            doc = fitz.open(file_path)
            
            # Determine page range
            total_pages = len(doc)
            start_page = 0
            end_page = total_pages
            
            if page_range:
                start_page = max(0, page_range[0] - 1)  # Convert to 0-based index
                end_page = min(total_pages, page_range[1])
            
            # Extract text from each page
            pages_text = []
            full_text = ""
            
            for page_num in range(start_page, end_page):
                page = doc[page_num]
                text = page.get_text()
                pages_text.append({
                    "page_number": page_num + 1,
                    "text": text,
                    "char_count": len(text)
                })
                full_text += text + "\n"
            
            # Get document metadata
            metadata = self.extract_metadata(doc)
            
            doc.close()
            
            return {
                "success": True,
                "file_path": file_path,
                "total_pages": total_pages,
                "extracted_pages": len(pages_text),
                "full_text": full_text.strip(),
                "pages": pages_text,
                "metadata": metadata,
                "total_characters": len(full_text)
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "file_path": file_path
            }
    
    def extract_metadata(self, doc: fitz.Document) -> Dict[str, Any]:
        """Extract metadata from PDF document."""
        metadata = doc.metadata
        
        return {
            "title": metadata.get("title", ""),
            "author": metadata.get("author", ""),
            "subject": metadata.get("subject", ""),
            "creator": metadata.get("creator", ""),
            "producer": metadata.get("producer", ""),
            "creation_date": metadata.get("creationDate", ""),
            "modification_date": metadata.get("modDate", ""),
            "page_count": len(doc),
            "encrypted": doc.needs_pass,
            "pdf_version": doc.pdf_version() if hasattr(doc, 'pdf_version') else None
        }
    
    def extract_images(self, file_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Extract images from PDF.
        
        Args:
            file_path: Path to PDF file
            output_dir: Directory to save extracted images (optional)
            
        Returns:
            Dictionary containing image information
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found: {file_path}")
        
        try:
            doc = fitz.open(file_path)
            images_info = []
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                image_list = page.get_images()
                
                for img_index, img in enumerate(image_list):
                    # Get image data
                    xref = img[0]
                    pix = fitz.Pixmap(doc, xref)
                    
                    # Skip if image has alpha channel and convert to RGB
                    if pix.alpha:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    
                    img_data = pix.tobytes("png")
                    img_name = f"page_{page_num + 1}_img_{img_index + 1}.png"
                    
                    # Save image if output directory specified
                    img_path = None
                    if output_dir:
                        os.makedirs(output_dir, exist_ok=True)
                        img_path = os.path.join(output_dir, img_name)
                        with open(img_path, "wb") as f:
                            f.write(img_data)
                    
                    # Convert to base64 for return
                    img_base64 = base64.b64encode(img_data).decode()
                    
                    images_info.append({
                        "page_number": page_num + 1,
                        "image_index": img_index + 1,
                        "image_name": img_name,
                        "width": pix.width,
                        "height": pix.height,
                        "colorspace": pix.colorspace.name if pix.colorspace else "unknown",
                        "file_path": img_path,
                        "base64_data": img_base64[:100] + "..." if len(img_base64) > 100 else img_base64,  # Truncate for display
                        "size_bytes": len(img_data)
                    })
                    
                    pix = None  # Free memory
            
            doc.close()
            
            return {
                "success": True,
                "file_path": file_path,
                "total_images": len(images_info),
                "images": images_info,
                "output_directory": output_dir
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "file_path": file_path
            }
    
    def get_page_info(self, file_path: str) -> Dict[str, Any]:
        """
        Get detailed information about each page.
        
        Args:
            file_path: Path to PDF file
            
        Returns:
            Dictionary containing page information
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found: {file_path}")
        
        try:
            doc = fitz.open(file_path)
            pages_info = []
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                rect = page.rect
                
                page_info = {
                    "page_number": page_num + 1,
                    "width": rect.width,
                    "height": rect.height,
                    "rotation": page.rotation,
                    "text_length": len(page.get_text()),
                    "image_count": len(page.get_images()),
                    "link_count": len(page.get_links()),
                    "annotation_count": len(page.annots()) if hasattr(page, 'annots') else 0
                }
                pages_info.append(page_info)
            
            doc.close()
            
            return {
                "success": True,
                "file_path": file_path,
                "total_pages": len(pages_info),
                "pages": pages_info
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "file_path": file_path
            }
    
    def search_text(self, file_path: str, search_term: str, case_sensitive: bool = False) -> Dict[str, Any]:
        """
        Search for text in PDF.
        
        Args:
            file_path: Path to PDF file
            search_term: Text to search for
            case_sensitive: Whether search should be case sensitive
            
        Returns:
            Dictionary containing search results
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found: {file_path}")
        
        try:
            doc = fitz.open(file_path)
            search_results = []
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Perform text search
                text_instances = page.search_for(search_term, hit_max=100)
                
                for instance in text_instances:
                    # Get surrounding text for context
                    text_dict = page.get_textbox(instance)
                    
                    search_results.append({
                        "page_number": page_num + 1,
                        "search_term": search_term,
                        "bbox": [instance.x0, instance.y0, instance.x1, instance.y1],
                        "context": text_dict[:200] + "..." if len(text_dict) > 200 else text_dict
                    })
            
            doc.close()
            
            return {
                "success": True,
                "file_path": file_path,
                "search_term": search_term,
                "total_matches": len(search_results),
                "matches": search_results
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "file_path": file_path,
                "search_term": search_term
            }