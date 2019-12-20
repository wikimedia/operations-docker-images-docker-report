import argparse
import logging


# Helper functions below taken from
# https://vincent.bernat.ch/en/blog/2019-sustainable-python-script
class CustomFormatter(argparse.RawDescriptionHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass


def setup_logging(logger: logging.Logger, options: argparse.Namespace):
    """Configure logging."""
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    logger.setLevel(options.debug and logging.DEBUG or logging.INFO)
    if not options.silent:
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(levelname)s[%(name)s] %(message)s"))
        logger.addHandler(ch)
