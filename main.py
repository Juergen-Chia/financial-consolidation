import logging
import sys
from pathlib import Path

from src.consolidator import ConsolidationError, Consolidator
from src.fx_translator import FXConfigError
from src.report_writer import ReportWriter


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    logger = logging.getLogger("main")

    base_dir = Path(__file__).parent
    config_dir = base_dir / "config"
    data_dir = base_dir / "data"
    output_path = base_dir / "output" / "consolidated_report.xlsx"

    try:
        consolidator = Consolidator(config_dir=config_dir, data_dir=data_dir)
        result = consolidator.run()

        writer = ReportWriter(output_path)
        writer.write(result)

        logger.info("Consolidation complete. Output: %s", output_path)

        warnings = [m for m in result.validation_messages if m.severity == "WARNING"]
        errors = [m for m in result.validation_messages if m.severity == "ERROR"]

        if warnings:
            logger.warning("%d warning(s) — review Validation tab in report.", len(warnings))
        if errors:
            logger.error("%d error(s) — review Validation tab in report.", len(errors))

    except (ConsolidationError, FXConfigError) as exc:
        logging.getLogger("main").error("Consolidation halted: %s", exc)
        sys.exit(1)
    except Exception as exc:
        logging.getLogger("main").exception("Unexpected error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
