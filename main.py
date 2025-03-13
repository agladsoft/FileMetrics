import os
import uvicorn
from fastapi import FastAPI
from datetime import datetime
from pydantic import BaseModel
from fastapi import HTTPException
from prometheus_client.core import REGISTRY
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Gauge, Summary, generate_latest


app: FastAPI = FastAPI()
counter: int = 0

# Метрики
FILES_PROCESSED: Counter = Counter(
    'files_processed_total',
    'Total number of processed files',
    ['script_name', 'file_name']
)
ROWS_PROCESSED: Counter = Counter(
    'rows_in_json_total',
    'Total number of rows written to JSON',
    ['script_name', 'file_name']
)
PROCESSING_TIME: Summary = Summary(
    'file_processing_time_seconds',
    'Time spent processing files',
    ['script_name', 'file_name']
)
FILE_UPLOAD_TIME: Gauge = Gauge(
    'file_upload_time',
    'Timestamp of file upload (seconds since epoch)',
    ['script_name', 'file_name']
)
PROCESSING_STATUS: Gauge = Gauge(
    'active_file_processing',
    'Number of files currently being processed',
    ['script_name', 'file_name']
)


class FileMetrics(BaseModel):
    script_name: str
    file_name: str
    rows: int
    processing_time: float


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """
    Returns all available metrics in OpenMetrics text format.

    This endpoint is meant to be scraped by Prometheus and should not be used
    directly by humans unless you know what you are doing.
    :return: A string containing all available metrics in OpenMetrics text format.
    """
    return generate_latest(REGISTRY)


@app.post("/track-file/")
async def track_file(metrics_name: FileMetrics):
    """
    Updates Prometheus metrics related to file processing.

    This endpoint increments the count of processed files and rows, observes
    the processing time, and sets the file upload timestamp for the specified
    file and script.

    :param metrics_name: An object containing the script name, file name, number of rows processed, and processing time.
    :return: A message indicating that the metrics have been updated.
    :raises: HTTPException: If an error occurs while updating the metrics.
    """
    try:
        FILES_PROCESSED.labels(
            script_name=metrics_name.script_name,
            file_name=metrics_name.file_name
        ).inc()

        ROWS_PROCESSED.labels(
            script_name=metrics_name.script_name,
            file_name=metrics_name.file_name
        ).inc(metrics_name.rows)

        PROCESSING_TIME.labels(
            script_name=metrics_name.script_name,
            file_name=metrics_name.file_name
        ).observe(metrics_name.processing_time)

        FILE_UPLOAD_TIME.labels(
            script_name=metrics_name.script_name,
            file_name=metrics_name.file_name
        ).set(datetime.now().timestamp())

        return {"message": "Metrics updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/real-time-stats/")
async def track_file(metrics_name: FileMetrics):
    """
    Updates the real-time processing status of a file with the given metrics.

    This endpoint receives a `FileMetrics` object containing the script name,
    file name, and number of rows. It sets the processing status gauge for
    the specified file to the number of rows provided.

    :param metrics_name: An object containing the script name, file name, and number of rows.
    :return: A message indicating that the metrics have been updated.
    :raises: If an error occurs while updating the metrics, an HTTP 500 error is raised with the exception details.
    """
    try:
        PROCESSING_STATUS.labels(
            script_name=metrics_name.script_name,
            file_name=metrics_name.file_name
        ).set(metrics_name.rows)

        return {"message": "Metrics updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv('APP_PORT')))
