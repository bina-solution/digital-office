# OCR Core

This module provides a comprehensive framework for Optical Character Recognition (OCR) processing, text extraction, and spatial text analysis. It offers a complete pipeline from image/PDF processing to advanced text queries based on visual positioning.

## Core Components

- **ocr_processor.py**  
  The foundation of the OCR pipeline that interfaces with Google Vision API. It handles HTTP requests for OCR processing, implements an efficient caching mechanism to prevent redundant API calls, converts PDFs to JPGs for processing, and manages file hashing for storage optimization.

- **ocr_data.py**  
  Provides a structured wrapper around raw OCR API results with a developer-friendly interface. It transforms JSON responses into usable Python objects, offers cached properties for performance, facilitates loading data from file paths or IDs, and provides clean access to full text and annotations.

- **ocr_object.py**  
  Acts as a high-level facade that integrates OCR data, queries, and visualizations into a cohesive unit. It manages relationships between components, serves as the main entry point for most operations, and provides convenient factory methods for initialization from various sources.

- **ocr_query.py**  
  Implements sophisticated text finding algorithms based on spatial relationships and visual positioning. Features include relative position text searches (before, after, above, below), fuzzy matching to handle OCR imperfections, alignment detection between text elements, and methods to find text patterns across multiple annotations.

- **ocr_json_query.py**  
  Offers a JSON-based query interface that enables declarative text extraction operations. It supports various actions for positional text finding, implements validation rules for extracted values, handles errors with descriptive messages, and returns structured responses for consistent client interaction.

- **ocr_drawings.py**  
  Provides visualization tools for OCR analysis and debugging. It renders bounding boxes, alignment indicators, and other visual aids directly on source images, manages image manipulation operations with caching support, and offers customizable visual styling for different annotation types.

## Models

- **annotation_object.py**  
  Defines the AnnotationObject class that represents a detected text element with its spatial properties. It provides methods for checking relationships with other annotations (alignment, containment), supports merging multiple annotations, detects text directionality (RTL/LTR), and implements alignment analysis with relative positioning.

- **bounding_box.py**  
  Implements the BoundingBox class for geometric representation and analysis of text regions. It calculates essential properties like dimensions, center point, and orientation angle, implements sophisticated alignment algorithms accounting for rotation and distance, and supports operations like combining boxes and checking containment.

- **relative_position.py**  
  Defines the RelativePosition enum that standardizes directional relationships between text elements (BEFORE, AFTER, ABOVE, BELOW). This provides consistent position referencing throughout the system and enables intuitive positional queries.

- **alingment_position.py**  
  Provides the AlignmentPosition enum that specifies spatial alignment types (LEFT, RIGHT, ABOVE, BELOW). It's used extensively in the alignment detection algorithms and supports precise control over text relationship analysis.

## Exceptions

- **ocr_query_exceptions.py**  
  Defines a hierarchy of custom exceptions for OCR operations. Includes OCRQueryException as the base class, MatchNotFound for text search failures, and AlignmentNotFound for alignment detection issues, enabling precise error handling throughout the OCR pipeline.

## Usage

Use this module to process documents, extract structured text based on spatial relationships, and analyze text layout visually. The system is particularly powerful for forms, invoices, and other documents with consistent spatial text arrangements.







