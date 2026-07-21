import datetime
import zipfile
from unittest.mock import MagicMock, Mock, patch

import pytest
from operaton.external_task.external_task import ExternalTask

from worker.sentinel.tasks import (
    SentinelContinuousDiscoveryHandler,
    SentinelDiscoverHandler,
    SentinelDownloadHandler,
)


@pytest.fixture
def mock_task():
    """
    Creates mocked ExternalTask-object.
    """
    task = MagicMock(spec=ExternalTask)

    task.get_worker_id.return_value = "test-worker-001"
    task.get_task_id.return_value = "test-task-123"
    task.get_topic_name.return_value = "sentinel-topics"

    task.complete.return_value = None
    task.failure.return_value = None

    return task


@pytest.fixture
def mock_log_with_context():
    """
    Mocks logging to prevent from side effects.
    """
    with patch("worker.sentinel.tasks.log_with_context") as mock:
        yield mock


@pytest.fixture
def handler_factory(mock_log_with_context):
    """Handler factory"""

    def _create(handler_class):
        with patch("worker.common.task_handler.TaskHandler.__init__", lambda self: None):
            handler_instance = handler_class()
            handler_instance.get_config = Mock()
            return handler_instance

    return _create


class TestSentinelHandlerApiInteraction:
    """
    Tests the interaction with the API for Sentinel.
    """

    @pytest.mark.parametrize("discovery_class", [SentinelContinuousDiscoveryHandler])
    @patch("worker.common.search_interval.datetime")
    def test_SentinelContinuousDiscoveryHandler_returns_scenes_from_api(
        self, mock_datetime, mocker, mock_task, handler_factory, discovery_class, mock_log_with_context
    ):
        """
        Tests SentinelContinuousDiscoveryHandler
        """
        ### Arrange ###
        discovery_handler = handler_factory(discovery_class)

        discovery_handler.get_config.side_effect = {
            "enabled": True,
            "page_size": 1000,
            "collections": "S2_MSI_L2A,S2_MSI_L1C",
            "bbox": "8,40,18,60",
            "timewindow_hours": 1,
        }.get

        # mock EngineClient & API Response
        from operaton.client.engine_client import EngineClient

        mock_method = mocker.patch.object(EngineClient, "get_process_instance_history")
        mock_method.return_value = {"startTime": "2026-06-29T16:01:00Z"}

        # keep real datetime-class for constructors
        mock_datetime.datetime.side_effect = lambda *args, **kw: datetime.datetime(*args, **kw)
        mock_datetime.timedelta = datetime.timedelta

        ### Act ###
        discovery_handler.execute(mock_task)

        # get global vars from complete
        global_vars: dict = mock_task.complete.call_args[1].get("global_variables", {})

        # check for scenes list
        assert "scenes" in global_vars
        scenes: list = global_vars.get("scenes")

        # check list itself
        assert isinstance(scenes, list)
        assert len(scenes) > 0

        # check first scene
        first_scene = scenes[0]
        assert isinstance(first_scene, dict)
        assert "eodag:download_link" in first_scene
        assert "eodag:provider" in first_scene
        assert "id" in first_scene
        assert "uid" in first_scene

        # check if data for both collections was found
        has_msil2a = any("MSIL2A" in scene.get("id", "") for scene in scenes)
        has_msil1c = any("MSIL1C" in scene.get("id", "") for scene in scenes)

        assert has_msil1c or has_msil2a, "Collection S2_MSI_L2A is missing!"
        assert has_msil1c or has_msil2a, "Collection S2_MSI_L1C is missing!"

    @pytest.mark.parametrize("discovery_class", [SentinelDiscoverHandler])
    def test_SentinelDiscoverHandler_downloads_scenes_from_api(
        self, mock_task, handler_factory, discovery_class, mock_log_with_context, tmp_path
    ):
        """
        Tests SentinelDiscoverHandler for Data Discovery and
        Data Download e2e.
        """
        ####### Discovery Test #######
        ### Arrange ###
        discovery_handler = handler_factory(discovery_class)

        mock_task.get_variable.side_effect = {
            "datetime_interval": "2026-06-29T15:00:00Z/2026-06-29T16:00:00Z",
            "collections": "S2_MSI_L1C,S2_MSI_L2A",
            "bbox": "8,40,18,60",
        }.get

        discovery_handler.get_config.side_effect = {
            "page_size": 1000,
        }.get

        ### Act ###
        discovery_handler.execute(mock_task)

        # get global vars from complete
        global_vars: dict = mock_task.complete.call_args[1].get("global_variables", {})

        # check for scenes list
        assert "scenes" in global_vars
        scenes: list = global_vars.get("scenes")

        # check list itself
        assert isinstance(scenes, list)
        assert len(scenes) > 0

        # check first scene
        first_scene = scenes[0]
        assert isinstance(first_scene, dict)
        assert "eodag:download_link" in first_scene
        assert "eodag:provider" in first_scene
        assert "id" in first_scene
        assert "uid" in first_scene

        # check if data for both collections was found
        has_msil2a = any("MSIL2A" in scene.get("id", "") for scene in scenes)
        has_msil1c = any("MSIL1C" in scene.get("id", "") for scene in scenes)

        assert has_msil1c or has_msil2a, "Collection S2_MSI_L2A is missing!"
        assert has_msil1c or has_msil2a, "Collection S2_MSI_L1C is missing!"

        ####### Download-Test #######
        ### Arrange ###
        download_handler = handler_factory(SentinelDownloadHandler)

        mock_task.get_variable.side_effect = {"scene": first_scene}.get

        download_handler.get_config.side_effect = {
            "download_base_dir": str(tmp_path),
            "download_retry_wait_time_minutes": 1,
            "download_retry_timeout_minutes": 60,
        }.get

        ### Act ###
        download_handler.execute(mock_task)

        ### Assert ###
        assert mock_task.complete.call_count == 2

        # get global vars from complete
        global_vars_download: dict = mock_task.complete.call_args[1].get("global_variables", {})

        # check for collection
        assert "collection" in global_vars_download

        # check if there is any file
        downloaded_files = [f for f in tmp_path.rglob("*") if f.is_file() and f.suffix.lower() == ".zip"]
        assert len(downloaded_files) > 0

        # check if file is empty
        first_file = downloaded_files[0]
        assert first_file.stat().st_size > 0

        # check if zip file is valid and complete
        assert zipfile.is_zipfile(first_file), f"{first_file.name} is no valid zip file!"

        # check zip content
        with zipfile.ZipFile(first_file) as zf:
            bad_file = zf.testzip()
            assert bad_file is None, f"Damaged file in zip archive: {bad_file}"
