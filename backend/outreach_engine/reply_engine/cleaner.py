"""
TEXT CLEANER
============

Extract clean human text from email replies.

Removes:
- HTML tags
- Quoted previous emails (> lines, blockquotes)
- "On {date}, {name} wrote:" blocks
- Signatures (after --, Best, Thanks, etc.)
- Tracking footers / unsubscribe links
- Multiple blank lines

Enterprise Rules:
- Preserve short replies ("Yes.", "No thanks")
- If cleaned text < 3 chars → fallback to first sentence from raw
- Max output: 2000 chars for AI input
- Never return empty string
"""

import re
import logging
from typing import Optional, Tuple
from html import unescape
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

# Max length for AI input
MAX_CLEANED_LENGTH = 2000

# Minimum meaningful reply length
MIN_REPLY_LENGTH = 3


class HTMLTextExtractor(HTMLParser):
    """Extract text from HTML, preserving structure."""
    
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.in_blockquote = False
        self.blockquote_depth = 0
        self.in_style = False
        self.in_script = False
    
    def handle_starttag(self, tag, attrs):
        if tag == "blockquote":
            self.in_blockquote = True
            self.blockquote_depth += 1
        elif tag == "style":
            self.in_style = True
        elif tag == "script":
            self.in_script = True
        elif tag in ("br", "p", "div", "tr", "li"):
            self.text_parts.append("\n")
    
    def handle_endtag(self, tag):
        if tag == "blockquote":
            self.blockquote_depth -= 1
            if self.blockquote_depth <= 0:
                self.in_blockquote = False
                self.blockquote_depth = 0
        elif tag == "style":
            self.in_style = False
        elif tag == "script":
            self.in_script = False
        elif tag in ("p", "div", "tr"):
            self.text_parts.append("\n")
    
    def handle_data(self, data):
        if self.in_style or self.in_script:
            return
        if self.in_blockquote:
            return  # Skip quoted content
        self.text_parts.append(data)
    
    def get_text(self) -> str:
        return "".join(self.text_parts)


class TextCleaner:
    """
    Clean email reply text for classification.
    
    Extracts only the new human-written content,
    removing all quoted/forwarded content and signatures.
    """
    
    # Patterns for "On X wrote:" blocks
    ON_WROTE_PATTERNS = [
        r"on\s+.{5,50}\s+wrote\s*:",  # On Mon, Jan 1, 2026, John wrote:
        r"am\s+\d{1,2}\.\d{1,2}\.\d{2,4}.+schrieb",  # German
        r"le\s+\d{1,2}/\d{1,2}/\d{2,4}.+a écrit",  # French
        r"el\s+\d{1,2}/\d{1,2}/\d{2,4}.+escribió",  # Spanish
        r"\d{4}年\d{1,2}月\d{1,2}日.+写道",  # Chinese
        r"от\s+.+\d{4}.+написал",  # Russian
    ]
    
    # Signature start patterns
    SIGNATURE_PATTERNS = [
        r"^--\s*$",  # Standard sig delimiter
        r"^_{3,}$",  # Underscores
        r"^-{3,}$",  # Dashes
        r"^best\s*(regards|wishes)?\s*,?\s*$",
        r"^kind\s*regards\s*,?\s*$",
        r"^regards\s*,?\s*$",
        r"^thanks\s*(and|&)?\s*(regards)?\s*,?\s*$",
        r"^thank\s*you\s*,?\s*$",
        r"^cheers\s*,?\s*$",
        r"^sincerely\s*,?\s*$",
        r"^sent\s+from\s+(my\s+)?(iphone|android|mobile|samsung)",
        r"^get\s+outlook\s+for",
        r"^sent\s+via",
    ]
    
    # Tracking/footer patterns to remove
    FOOTER_PATTERNS = [
        r"click\s+here\s+to\s+unsubscribe",
        r"unsubscribe\s+from\s+this",
        r"opt\s*-?\s*out",
        r"manage\s+your\s+preferences",
        r"email\s+preferences",
        r"view\s+(this\s+)?(email\s+)?in\s+(your\s+)?browser",
        r"trouble\s+viewing",
        r"add\s+us\s+to\s+your\s+contacts",
        r"\[image:\s*[^\]]+\]",  # [image: ...] placeholders
        r"cid:[a-zA-Z0-9]+",  # cid: image references
    ]
    
    def __init__(self):
        """Initialize cleaner with compiled patterns."""
        self._on_wrote_re = [
            re.compile(p, re.IGNORECASE | re.MULTILINE)
            for p in self.ON_WROTE_PATTERNS
        ]
        self._signature_re = [
            re.compile(p, re.IGNORECASE | re.MULTILINE)
            for p in self.SIGNATURE_PATTERNS
        ]
        self._footer_re = [
            re.compile(p, re.IGNORECASE)
            for p in self.FOOTER_PATTERNS
        ]
    
    def clean(
        self,
        raw_text: str,
        is_html: bool = False
    ) -> Tuple[str, int]:
        """
        Clean email reply text.
        
        Args:
            raw_text: Raw email body
            is_html: Whether input is HTML
            
        Returns:
            Tuple of (cleaned_text, original_length)
        """
        if not raw_text:
            return "", 0
        
        original_length = len(raw_text)
        
        # Step 1: Convert HTML to text
        if is_html or self._looks_like_html(raw_text):
            text = self._html_to_text(raw_text)
        else:
            text = raw_text
        
        # Step 2: Decode HTML entities
        text = unescape(text)
        
        # Step 3: Remove "On X wrote:" blocks and everything after
        text = self._remove_on_wrote_blocks(text)
        
        # Step 4: Remove quoted lines (starting with >)
        text = self._remove_quoted_lines(text)
        
        # Step 5: Remove signatures
        text = self._remove_signature(text)
        
        # Step 6: Remove tracking/footer content
        text = self._remove_footers(text)
        
        # Step 7: Clean up whitespace
        text = self._normalize_whitespace(text)
        
        # Step 8: Handle short replies
        if len(text.strip()) < MIN_REPLY_LENGTH:
            text = self._fallback_extract(raw_text, is_html)
        
        # Step 9: Truncate for AI
        if len(text) > MAX_CLEANED_LENGTH:
            text = text[:MAX_CLEANED_LENGTH].rsplit(" ", 1)[0] + "..."
        
        return text.strip(), original_length
    
    # ============== STEP METHODS ==============
    
    def _looks_like_html(self, text: str) -> bool:
        """Check if text appears to be HTML."""
        html_indicators = ["<html", "<body", "<div", "<p>", "<br", "<table"]
        text_lower = text.lower()
        return any(ind in text_lower for ind in html_indicators)
    
    def _html_to_text(self, html: str) -> str:
        """
        Convert HTML to plain text.
        
        Removes blockquotes (quoted content).
        """
        try:
            extractor = HTMLTextExtractor()
            extractor.feed(html)
            return extractor.get_text()
        except Exception as e:
            logger.warning(f"HTML parsing error: {e}")
            # Fallback: strip tags with regex
            text = re.sub(r"<blockquote[^>]*>.*?</blockquote>", "", html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            return text
    
    def _remove_on_wrote_blocks(self, text: str) -> str:
        """
        Remove "On X wrote:" and everything after.
        
        This is where quoted content typically begins.
        """
        for pattern in self._on_wrote_re:
            match = pattern.search(text)
            if match:
                # Keep only text before the match
                text = text[:match.start()].strip()
                break
        
        return text
    
    def _remove_quoted_lines(self, text: str) -> str:
        """Remove lines starting with > (quoted text)."""
        lines = text.split("\n")
        non_quoted = []
        
        for line in lines:
            stripped = line.strip()
            # Skip quoted lines
            if stripped.startswith(">"):
                continue
            # Skip lines that are just quote markers
            if stripped in (">", ">>", ">>>"):
                continue
            non_quoted.append(line)
        
        return "\n".join(non_quoted)
    
    def _remove_signature(self, text: str) -> str:
        """
        Remove email signature.
        
        Detects signature delimiter and removes everything after.
        """
        lines = text.split("\n")
        
        # Find signature start
        sig_start = len(lines)
        
        for i, line in enumerate(lines):
            stripped = line.strip().lower()
            
            for pattern in self._signature_re:
                if pattern.match(stripped):
                    sig_start = i
                    break
            
            if sig_start < len(lines):
                break
        
        # Keep only lines before signature
        return "\n".join(lines[:sig_start])
    
    def _remove_footers(self, text: str) -> str:
        """Remove tracking footers and email preference links."""
        for pattern in self._footer_re:
            text = pattern.sub("", text)
        return text
    
    def _normalize_whitespace(self, text: str) -> str:
        """
        Normalize whitespace.
        
        - Multiple blank lines → single
        - Multiple spaces → single
        - Strip leading/trailing
        """
        # Multiple blank lines to single
        text = re.sub(r"\n{3,}", "\n\n", text)
        
        # Multiple spaces to single
        text = re.sub(r"[ \t]+", " ", text)
        
        # Strip each line
        lines = [line.strip() for line in text.split("\n")]
        
        return "\n".join(lines).strip()
    
    def _fallback_extract(self, raw_text: str, is_html: bool) -> str:
        """
        Fallback extraction for very short or empty results.
        
        Returns first meaningful sentence from raw text.
        """
        # Convert HTML if needed
        if is_html or self._looks_like_html(raw_text):
            text = re.sub(r"<[^>]+>", " ", raw_text)
            text = unescape(text)
        else:
            text = raw_text
        
        # Clean up whitespace
        text = re.sub(r"\s+", " ", text).strip()
        
        # Find first sentence
        sentences = re.split(r"[.!?]\s+", text)
        
        for sentence in sentences:
            sentence = sentence.strip()
            # Skip if it looks like a header or metadata
            if sentence.lower().startswith("from:"):
                continue
            if sentence.lower().startswith("to:"):
                continue
            if sentence.lower().startswith("subject:"):
                continue
            if sentence.lower().startswith("date:"):
                continue
            # Skip quoted content
            if sentence.startswith(">"):
                continue
            
            if len(sentence) >= MIN_REPLY_LENGTH:
                return sentence
        
        # Last resort: return first N chars
        if len(text) >= MIN_REPLY_LENGTH:
            return text[:100]
        
        return text if text else "[empty reply]"
    
    # ============== UTILITIES ==============
    
    def extract_preview(self, text: str, max_length: int = 100) -> str:
        """
        Extract short preview of cleaned text.
        
        Useful for logging and UI display.
        """
        if not text:
            return ""
        
        # Get first line or sentence
        first_line = text.split("\n")[0].strip()
        
        if len(first_line) <= max_length:
            return first_line
        
        return first_line[:max_length-3] + "..."


# ============== EXAMPLE USAGE ==============

def clean_reply_text(raw_text: str, is_html: bool = False) -> str:
    """
    Convenience function for cleaning reply text.
    
    Args:
        raw_text: Raw email body
        is_html: Whether input is HTML
        
    Returns:
        Cleaned text ready for classification
    """
    cleaner = TextCleaner()
    cleaned, _ = cleaner.clean(raw_text, is_html)
    return cleaned
