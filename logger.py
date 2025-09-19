import sys
from loguru import logger

def get_logger():
    logger.configure(handlers=[{
            "sink": sys.stderr,
            "format": "{time:HH:mm:ss} | {function} | <level>{message}</level>"
        },
        {
            "sink": "logger.log",
            "format": "{time:YYYY-MM-DD HH:mm:ss} | {level} | {function} | {message}",
            "rotation": "10 MB",
            "retention": "7 days"
        }]
    )
    return logger