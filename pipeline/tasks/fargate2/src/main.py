from logging import INFO, getLogger

logger = getLogger(__name__)
logger.setLevel(INFO)

if __name__ == "__main__":
    logger.info("This is a Fargate task")
