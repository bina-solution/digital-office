import logging
import os

from src.ocr_core.ocr_processor import OcrProcessor
from src.ocr_core.ocr_json_query import OcrJsonQuery, ocr_json_query_factory
from src.utils.storage import failed_drive_files_path, ocr_test_files_path, pdf_test_files_path

logger = logging.getLogger("ocr_query")
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())

TEST_FILES_PATH = ocr_test_files_path()
PDF_TEST_FILES_PATH = pdf_test_files_path()
FAILED_DRIVE_FILES_PATH = failed_drive_files_path()

TEST_FILES = [
    os.path.join(ocr_test_files_path(), x) for x in os.listdir(TEST_FILES_PATH)
]
PDF_TEST_FILES = [
    os.path.join(pdf_test_files_path(), x) for x in os.listdir(PDF_TEST_FILES_PATH)
]
FAILED_DRIVE_FILES_PATH = [
    os.path.join(failed_drive_files_path(), x) for x in os.listdir(FAILED_DRIVE_FILES_PATH)
]

ALL_TEST_FILES = TEST_FILES 
# ALL_TEST_FILES = FAILED_DRIVE_FILES_PATH  # + PDF_TEST_FILES


# ALL_TEST_FILES = [os.path.join(TEST_FILES_PATH, "en-test.png")]

INVOICE_ID_KW = [
    (
        "after",
        [
            "חשבונית מס זיכוי מס':",
            "חשבונית מס מספר:",
            "חשבונית מס מספר",
            "חשבונית מס מס':",
            "'חשבונית מס מס",
            'חשבונית מס"',
            "חשבונית מס -",
            "חשבונית מס :",
            "חשבונית זיכוי",
            "חשבונית מס'",
            "חשבונית מס",
            "invoice id",
        ],
    ),
    ("under", ["חשבונית מס"]),
]

SHIPMENT_ID_KW = [
    (
        "after",
        [
            "תעודת משלוח מספר",
            "תעודת משלוח מס':",
            "תעודת משלוח מס'",
            "תעודת משלוח מס",
            "תעודת משלוח",
            "משלוח מס'",
            # "משלוח",
            # "מספר:",
            # "מס':",
        ],
    ),
    ("before", ["- S01"]),
]


def get_invoice_id(ocr_query: OcrJsonQuery):
    for kw in INVOICE_ID_KW:
        print(f"KW: {kw}")

        query = {
            "action": f"find {kw[0]}",
            "action_value": kw[1],
            "value_validations": [
                {"validation_type": "has_number"},
                {"validation_type": "length_greater_than", "validation_value": 3},
                {"validation_type": "length_less_than", "validation_value": 20},
            ],
            "is_rtl": True,
        }
        print(f"Query: {query}")

        result = ocr_query.json_query(query)
        if result.get("result") is not None:
            return {
                "value": result.get("result"),
                "text_match": (result.get("process_context") or {}).get("text_match"),
            }


def get_shipment_id(ocr_query: OcrJsonQuery):
    for kw in SHIPMENT_ID_KW:
        print(f"KW: {kw}")

        query = {
            "action": f"find {kw[0]}",
            "action_value": kw[1],
            "value_validations": [
                {"validation_type": "has_number"},
                {"validation_type": "length_greater_than", "validation_value": 3},
            ],
            "is_rtl": True,
        }
        print(f"Query: {query}")

        result = ocr_query.json_query(query)
        if result.get("result") is not None:
            return {
                "value": result.get("result"),
                "text_match": (result.get("process_context") or {}).get("text_match"),
            }


def process_all_files():
    files_res = []
    ocr_processor = OcrProcessor()
    pause_between_files = True
    draw_queries = True
    for filepath in ALL_TEST_FILES:
        ocr_query = ocr_json_query_factory(filepath, draw=True)

        invoice_id_res = get_invoice_id(ocr_query)
        invoice_id = invoice_id_res.get("value") if invoice_id_res else None
        invoice_id_text_match = (
            invoice_id_res.get("text_match") if invoice_id_res else None
        )

        shipment_id_res = get_shipment_id(ocr_query)
        shipment_id = shipment_id_res.get("value") if shipment_id_res else None
        shipment_id_text_match = (
            shipment_id_res.get("text_match") if shipment_id_res else None
        )
        
        print(f"File: {filepath}, Invoice ID: {invoice_id}, Shipment ID: {shipment_id}")
        files_res.append(
            {
                "file": filepath,
                "invoice_id": invoice_id,
                "invoice_id_text_match": invoice_id_text_match,
                "shipment_id": shipment_id,
                "shipment_id_text_match": shipment_id_text_match,
            }
        )
        
        if draw_queries:
            ocr_query.ocr_query.ocr_drawer.show()
        if pause_between_files:
            input("Press Enter to continue...")

    for filepath in files_res:
        print(filepath)

    input("Press Enter to continue...")

    for filepath in files_res:
        if not filepath.get("invoice_id") and not filepath.get("shipment_id"):
            print(f"File: {filepath.get('file')} has missing data")

    input("Press Enter to continue...")
    for filepath in files_res:
        if filepath.get("invoice_id") and filepath.get("shipment_id"):
            print(f"File: {filepath.get('file')} has both data")

    input("Press Enter to continue...")
    for filepath in files_res:
        print(
            f"File: {filepath.get('file')}",
            f"ID: {filepath.get('invoice_id') or filepath.get('shipment_id')}",
        )

    input("Press Enter to continue...")
    # print sucsess len out of all files
    success_count = len(
        [x for x in files_res if x.get("invoice_id") or x.get("shipment_id")]
    )
    print(f"Success count: {success_count} out of {len(files_res)}")


if __name__ == "__main__":
    process_all_files()
