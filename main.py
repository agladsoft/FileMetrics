import os
import uvicorn
import asyncio
from pydantic import BaseModel
from fastapi import HTTPException
from prometheus_client.core import REGISTRY
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import PlainTextResponse
from datetime import datetime, timezone, timedelta
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

active_files: dict = {}  # Хранит временные метки последней активности


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


@app.post("/file-processed/")
async def track_file(metrics_name: FileMetrics):
    """
    Updates Prometheus metrics related to file processed.

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
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/file-processing/")
async def track_file(metrics_name: FileMetrics):
    """
    Updates the processing status of a file with the given metrics.

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
        raise HTTPException(status_code=500, detail=str(e)) from e


async def reset_status(script_name: str, timeout: int = 60) -> None:
    """
    Resets the real-time processing status of a file to 0 after a specified timeout.

    This function waits for the specified timeout, then checks if the file is still
    in the active_files dictionary. If it is, it resets the corresponding gauge
    in the PROCESSING_STATUS metric to 0 and removes the file from the dictionary.

    :param script_name: The name of the script that processed the file.
    :param timeout: The number of seconds to wait before resetting the metric.
    """
    await asyncio.sleep(timeout)

    if script_name in active_files:
        last_update: datetime = active_files[script_name][1]
        if datetime.now(timezone.utc) - last_update >= timedelta(seconds=timeout):
            active_files.pop(script_name, None)


@app.post("/real-time-stats/")
async def track_file(metrics_name: FileMetrics, background_tasks: BackgroundTasks):
    try:
        current_rows: int = active_files.get(metrics_name.script_name, (0, None))[0]
        current_rows += 1

        # Обновляем счетчик строк и время последней активности
        active_files[metrics_name.script_name] = (current_rows, datetime.now(timezone.utc))

        # Устанавливаем увеличенное значение метрики
        PROCESSING_STATUS.labels(
            script_name=metrics_name.script_name,
            file_name=metrics_name.file_name
        ).set(current_rows)

        # Запускаем фоновую задачу для сброса через 60 секунд
        background_tasks.add_task(reset_status, metrics_name.script_name)

        return {"message": f"Metrics updated: {current_rows} rows"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv('APP_PORT')))
