import sys
from pathlib import Path

# Ensure Python can see the project root
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.extraction.excel_reader import load_api_request_data
from src.orchestration.dispatcher import distribute_to_services
from src.loading.writer import save_final_report
from src.utils.logger import get_logger

logger = get_logger(__name__)

def run_pipeline():
    logger.info("=" * 40)
    logger.info("STARTING SERVICE COMPARISON PIPELINE")
    logger.info("=" * 40)

    # 1. Extraction (Bronze Layer)
    raw_data = load_api_request_data()
    if raw_data is None or raw_data.empty:
        logger.error("Pipeline stopped. Check data/01_raw for valid input files.")
        return
    logger.info("Extraction complete. Loaded %d rows.", len(raw_data))

    # 2. Orchestration & Service requests (Silver/Enrichment Layer)
    service_results = distribute_to_services(raw_data)

    if service_results is None or service_results.empty:
        logger.warning("Pipeline finished but no service results were gathered.")
        return
    logger.info("Orchestration complete. Gathered %d service responses.", len(service_results))

    # 3. Loading / Save results (Gold Layer)
    final_report = save_final_report(raw_data, service_results)

    logger.info("Pipeline successfully finished. Total rows in report: %d", len(final_report))
    logger.info("=" * 40)

if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception as e:
        logger.exception("Critical Error in main pipeline: %s", e)
