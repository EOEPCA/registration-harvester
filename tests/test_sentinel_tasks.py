import os
import sys
import pytest
import tempfile
import zipfile
import flowable
from unittest.mock import MagicMock, patch

# Add the src directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from worker.common.types import ExternalJob, JobResultBuilder, JobResult
from worker.sentinel.tasks import SentinelUnzipHandler

class TestSentinelUnzipHandler:
    @pytest.fixture
    def handler(self):
        handlers_config = {
            "SentinelUnzipHandler": {
                "subscription_config": {
                    "lock_duration": "PT1M",
                    "number_of_retries": 5,
                    "wait_period_seconds": 1,
                    "number_of_tasks": 1
                },
                "handler_config": {}
            }
        }
        return SentinelUnzipHandler(handlers_config)

    @pytest.fixture
    def job_result_builder(self, mock_job):
        return JobResultBuilder(mock_job)

    @pytest.fixture
    def mock_job(self):
        job = MagicMock(spec=ExternalJob)
        job.id = "test-job-id"
        job.element_name = "test-task"
        return job

    @pytest.fixture
    def test_zip_file(self):
        # Create a temporary zip file for testing
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            with zipfile.ZipFile(temp_zip.name, 'w') as zf:
                zf.writestr('test_file.txt', 'Test content')
            return temp_zip.name

    def test_successful_unzip(self, handler, mock_job, job_result_builder, test_zip_file):
        # Setup
        mock_job.get_variable.return_value = test_zip_file

        # Execute
        result = handler.execute(mock_job, job_result_builder, {})

        # Assert
        scene_folder = next((var.value for var in result._variables if var.name == "scene_folder"), None)

        assert isinstance(result, flowable.external_worker_client.worker_result.WorkerResultSuccess)
        assert os.path.exists(scene_folder)
        assert os.path.isfile(os.path.join(scene_folder, "test_file.txt"))

        # Cleanup
        os.unlink(test_zip_file)
        os.unlink(os.path.join(scene_folder, "test_file.txt"))
        os.rmdir(scene_folder)

    def test_nonexistent_zip_file(self, handler, mock_job, job_result_builder):
        # Setup
        mock_job.get_variable.return_value = "/nonexistent/path/file.zip"

        # Execute
        result = handler.execute(mock_job, job_result_builder, {})

        # Assert
        assert isinstance(result, flowable.external_worker_client.worker_result.WorkerResultFailure)


    def test_invalid_zip_file(self, handler, mock_job, job_result_builder):
        # Setup
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_file:
            temp_file.write(b'Not a zip file')
            temp_file.flush()
            mock_job.get_variable.return_value = temp_file.name

        # Execute
        result = handler.execute(mock_job, job_result_builder, {})

        # Assert
        assert isinstance(result, flowable.external_worker_client.worker_result.WorkerResultFailure)

        # Cleanup
        os.unlink(temp_file.name)

    def test_extraction_error(self, handler, mock_job, job_result_builder, test_zip_file):
        # Setup
        mock_job.get_variable.return_value = test_zip_file
        
        # Simulate permission error during extraction
        with patch('zipfile.ZipFile.extractall', side_effect=PermissionError("Permission denied")):
            # Execute
            result = handler.execute(mock_job, job_result_builder, {})

            # Assert
            assert isinstance(result, flowable.external_worker_client.worker_result.WorkerResultFailure)

        # Cleanup
        os.unlink(test_zip_file)
