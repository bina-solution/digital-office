#!/usr/bin/env python3
"""
Generate test images for table column alignment validation.
Tests all combinations of header and value alignments (left, center, right).
"""

from PIL import Image, ImageDraw, ImageFont
import os

# Configuration
OUTPUT_DIR = "fixtures"
IMAGE_WIDTH = 800
IMAGE_HEIGHT = 400
BACKGROUND_COLOR = "white"
TEXT_COLOR = "black"
FONT_SIZE = 32

# Table configuration
TABLE_TOP = 100
TABLE_LEFT = 200
TABLE_WIDTH = 400  # Single column
COLUMN_WIDTH = 400
ROW_HEIGHT = 60
HEADER_ROW_Y = TABLE_TOP
VALUE_ROW_START_Y = TABLE_TOP + ROW_HEIGHT

# Test data
HEADER_TEXT = "Amount"
VALUE_TEXTS = ["1,234.56", "987.65", "5,432.10"]

def get_alignment_x(text, font, column_left, column_width, alignment):
    """Calculate x position for text based on alignment."""
    bbox = font.getbbox(text)
    text_width = bbox[2] - bbox[0]
    
    if alignment == "left":
        return column_left + 10  # 10px padding from left
    elif alignment == "center":
        return column_left + (column_width - text_width) // 2
    elif alignment == "right":
        return column_left + column_width - text_width - 10  # 10px padding from right
    else:
        raise ValueError(f"Unknown alignment: {alignment}")

def create_alignment_test_image(header_align, value_align, output_filename):
    """
    Create a test image with specified header and value alignments.
    Single column with one header and three values below it.
    
    Args:
        header_align: Alignment for header text ("left", "center", "right")
        value_align: Alignment for value text ("left", "center", "right")
        output_filename: Name of the output file
    """
    # Create image
    img = Image.new('RGB', (IMAGE_WIDTH, IMAGE_HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)
    
    # Try to use a default font, fall back to PIL default if not available
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", FONT_SIZE)
    except:
        font = ImageFont.load_default()
    
    # Draw table grid lines - single column
    # Left and right column borders
    draw.line([(TABLE_LEFT, TABLE_TOP), (TABLE_LEFT, VALUE_ROW_START_Y + ROW_HEIGHT * len(VALUE_TEXTS))], 
              fill="gray", width=2)
    draw.line([(TABLE_LEFT + TABLE_WIDTH, TABLE_TOP), (TABLE_LEFT + TABLE_WIDTH, VALUE_ROW_START_Y + ROW_HEIGHT * len(VALUE_TEXTS))], 
              fill="gray", width=2)
    
    # Row separator lines (header + 3 value rows = 4 horizontal lines)
    draw.line([(TABLE_LEFT, HEADER_ROW_Y), (TABLE_LEFT + TABLE_WIDTH, HEADER_ROW_Y)], 
              fill="gray", width=2)
    
    for i in range(len(VALUE_TEXTS) + 1):  # +1 for bottom border
        y = VALUE_ROW_START_Y + i * ROW_HEIGHT
        draw.line([(TABLE_LEFT, y), (TABLE_LEFT + TABLE_WIDTH, y)], 
                  fill="gray", width=2)
    
    # Draw header in the single column
    header_x = get_alignment_x(HEADER_TEXT, font, TABLE_LEFT, COLUMN_WIDTH, header_align)
    header_y = HEADER_ROW_Y + 15  # Vertical padding
    draw.text((header_x, header_y), HEADER_TEXT, fill=TEXT_COLOR, font=font)
    
    # Draw values in rows below the header
    for i, value_text in enumerate(VALUE_TEXTS):
        value_x = get_alignment_x(value_text, font, TABLE_LEFT, COLUMN_WIDTH, value_align)
        value_y = VALUE_ROW_START_Y + i * ROW_HEIGHT + 15  # Vertical padding
        draw.text((value_x, value_y), value_text, fill=TEXT_COLOR, font=font)
    
    # Add title at the top
    title = f"Header: {header_align} | Value: {value_align}"
    title_bbox = font.getbbox(title)
    title_width = title_bbox[2] - title_bbox[0]
    title_x = (IMAGE_WIDTH - title_width) // 2
    draw.text((title_x, 30), title, fill="darkblue", font=font)
    
    # Save image
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    img.save(output_path)
    print(f"Created: {output_path}")
    return output_path

def main():
    """Generate all alignment combination test images."""
    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    alignments = ["left", "center", "right"]
    
    print("Generating table column alignment test images...")
    print("=" * 60)
    
    for header_align in alignments:
        for value_align in alignments:
            filename = f"below-table-align-h{header_align[0]}-v{value_align[0]}.png"
            create_alignment_test_image(header_align, value_align, filename)
    
    print("=" * 60)
    print(f"Generated {len(alignments) * len(alignments)} test images")
    print("\nAlignment combinations created:")
    for header_align in alignments:
        for value_align in alignments:
            print(f"  - Header: {header_align:6s} | Value: {value_align:6s}")

if __name__ == "__main__":
    main()
