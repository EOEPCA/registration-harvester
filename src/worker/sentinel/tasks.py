import datetime
import os
import time
import zipfile
from pathlib import Path

import requests
from dateutil.parser import parse

# from registration_library.resources import stac
from worker.common.client import flowable_client

# from registration_library.datasets import sentinel
from worker.common.datasets import sentinel
from worker.common.log_utils import configure_logging, format_duration, format_file_metrics, log_with_context

# from registration_library.providers import esa_cdse as cdse
from worker.common.providers import cdse
from worker.common.resources import stac
from worker.common.secrets import worker_secrets
from worker.common.task_handler import TaskHandler
from worker.common.types import ExternalJob, JobResult, JobResultBuilder

configure_logging()


class SentinelDiscoverHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        """
        Searches for new Sentinel data

        Variables needed:
            start_time
            stop_time
            filter

        Variables set:
            scenes: List of scenes found
        """

        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        log_with_context("Discovering new Sentinel data ...", log_context)

        url = self.get_config("api_url", "https://datahub.creodias.eu/odata/v1")
        limit = self.get_config("limit", 1000)

        filter_param = job.get_variable("filter")
        if filter_param is not None and len(filter_param) > 0:
            filters = [filter_param]
            log_with_context(f"Search parameter: filter='{filters}'", log_context)
            try:
                scenes = cdse.search(
                    api_url=url,
                    max_items=limit,
                    filters=filters,
                )
                log_with_context(f"Number of scenes found: {len(scenes)}", log_context)
                for idx, scene in enumerate(scenes, 1):
                    log_with_context(f"{idx} {scene["scene_id"]}", log_context)
            except Exception as e:
                error_msg = repr(e)
                log_with_context(error_msg, log_context)
                return self.task_failure("Error in discovery", error_msg, result, retries=3, timeout="PT20M")
        else:
            error_message = "Process input variable 'filter' is mandatory and must have a non-empty value"
            log_with_context(error_message, log_context, "error")
            # return result.failure().error_message(error_message).retries(0).retry_timeout("PT10M")
            return result.success().variable_json(name="scenes", value=[])

        # scenes = []
        return result.success().variable_json(name="scenes", value=scenes)


class SentinelContinuousDiscoveryHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        """
        Searches for new Sentinel data continuously

        Variables needed:

        Variables set:
            scenes: List of scenes found
        """

        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}

        if self.get_config("enabled", False):
            log_with_context("Continous discoveriy of new Sentinel data ...", log_context)

            # Handle input variables
            url = self.get_config("api_url", "https://datahub.creodias.eu/odata/v1")
            limit = self.get_config("limit", 1000)
            timewindow_hours = self.get_config("timewindow_hours", 1)
            filter_param = self.get_config("filter", None)
            start_time, end_time = self.determine_search_interal(job, timewindow_hours)

            filter_base = f"(PublicationDate ge {start_time} and PublicationDate lt {end_time}) and Online eq true"
            # filters_param = [
            #    (
            #        "(startswith(Name,'S1') and (contains(Name,'SLC') or contains(Name,'GRD')) "
            #        "and not contains(Name,'_COG') and not contains(Name, 'CARD_BS'))&$expand=Attributes"
            #    ),
            #    "(startswith(Name,'S2') and contains(Name,'L2A')) and not contains(Name,'_N9999')",
            #    # ("(startswith(Name,'S2') and (contains(Name,'L1C') or
            #    # contains(Name,'L2A')) and not contains(Name,'_N9999'))"),
            #    # "(startswith(Name,'S3A') or startswith(Name,'S3B'))",
            #    # "(startswith(Name,'S5P') and not contains(Name,'NRTI_'))"
            # ]
            if filter_param is not None:
                filters = [f"({filter_base}) and ({filter_param})"]
            else:
                filters = [filter_base]
            log_with_context(f"Search parameter: filter='{filters}'", log_context)

            try:
                scenes = cdse.search(api_url=url, max_items=limit, filters=filters)
                log_with_context(f"Number of scenes found: {len(scenes)}", log_context)
                for idx, scene in enumerate(scenes, 1):
                    log_with_context(f"{idx} {scene["scene_id"]}", log_context)
            except Exception as e:
                error_msg = repr(e)
                log_with_context(error_msg, log_context)
                return self.task_failure("Error in continous discovery", error_msg, result, retries=3, timeout="PT20M")
        else:
            log_with_context("Continous discovery is disabled by configuration, skipping ...", log_context)
            scenes = []

        scenes = []
        return result.success().variable_json(name="scenes", value=scenes)

    def determine_search_interal(self, job: ExternalJob, timedelta_hours: float) -> tuple[str, str]:
        history = flowable_client.get_process_instance_history(job.process_instance_id)
        if "startTime" in history:
            current_time = parse(history["startTime"])
        else:
            current_time = datetime.datetime.now()
        end_time = datetime.datetime(current_time.year, current_time.month, current_time.day, current_time.hour)
        start_time = end_time - datetime.timedelta(hours=timedelta_hours)
        start_time = start_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        end_time = end_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return start_time, end_time


class SentinelDownloadHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        time_start = time.perf_counter()

        scene = job.get_variable("scene")
        log_with_context(f"Input variables: {scene=}", context=log_context, log_level="debug")
        if "cdse_id" not in scene and "uid" in scene:
            scene["cdse_id"] = scene["uid"]

        # TODO: Calculate scene path according to
        # https://gitlab.dlr.de/terrabyte/data-management/ingestion/terrabyte-ingestion-lib/-/blob/main/
        # terrabyte/ingestion/providers/esa_cdse.py#L241-251
        scene_path = Path(self._get_scene_path(self.get_config("base_dir", "/tmp"), scene))
        if scene_path.suffix in [".SAFE", ".SEN3"]:
            scene_path = scene_path.parent / f"{scene['scene_id']}.zip"

        if os.path.exists(scene_path):
            log_with_context(f"Skipped download. File {scene_path} already exists", log_context)
        else:
            try:
                url = f"https://download.dataspace.copernicus.eu/odata/v1/Products({scene['uid']})/$value"
                access_key = self._get_access_token()
                headers = {"Authorization": f"Bearer {access_key}"}

                session = requests.Session()
                session.headers.update(headers)
                response = session.get(url, stream=True)
                response.raise_for_status()

                scene_path.parent.mkdir(parents=True, exist_ok=True)
                log_with_context(
                    f"Downloading {scene['scene_id']} (Size: {scene['ContentLength']}, Destination: {scene_path})",
                    log_context,
                )
                with scene_path.open(mode="wb") as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            file.write(chunk)
                if scene_path.suffix == ".zip":
                    if not zipfile.is_zipfile(scene_path):
                        scene_path.unlink(missing_ok=True)
                        raise Exception("File downloaded is not a valid zip file, remove file")
                elif scene_path.suffix == ".nc":
                    pass
            except requests.RequestException as e:
                error_messages = {
                    404: "Download not found",
                    403: "Download failed - Access denied",
                    504: "Download timeout",
                }
                status_code = getattr(e.response, "status_code", None)
                error_msg = error_messages.get(status_code, "Download failed")
                log_with_context(f"{error_msg} for {url}: {str(e)}", log_context)
                return result.failure()
            except Exception as e:
                log_with_context(f"Download failed for {url}: {str(e)}", log_context)
                return result.failure()

            time_end = time.perf_counter()
            log_with_context(
                f"Downloaded {scene_path} ({format_file_metrics(scene_path.stat().st_size, time_end - time_start)})",
                log_context,
            )

        collection = sentinel.get_collection_name(scene["scene_id"])
        log_with_context(f"{collection=}")

        return (
            result.success()
            .variable_string(name="zip_file", value=str(scene_path))
            .variable_string(name="collection", value=str(collection))
        )

    def _get_scene_path(self, base_dir, scene):
        s3path = Path(scene["S3Path"].lstrip("/"))
        return str(Path(base_dir) / s3path)

    def _get_access_token(self):
        if "token_expire_time" in os.environ and time.time() <= (float(os.environ["token_expire_time"]) - 5):
            return os.environ["s3_access_key"]

        cdse_user = worker_secrets.get_secret("cdse_user", "")
        cdse_password = worker_secrets.get_secret("cdse_password", "")
        auth_server_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
        data = {
            "client_id": "cdse-public",
            "grant_type": "password",
            "username": cdse_user,
            "password": cdse_password,
        }

        token_time = time.time()
        response = requests.post(auth_server_url, data=data, verify=True, allow_redirects=False).json()
        os.environ["token_expire_time"] = str(token_time + response.get("expires_in", 0))
        os.environ["s3_access_key"] = response.get("access_token", "")
        return os.environ["s3_access_key"]

    def _download_data(
        self,
        url,
        output_dir,
        file_name=None,
        chunk_size=1024 * 1000,
        timeout=300,
        auth=None,
        check_size=True,
        overwrite=False,
    ):
        """
        Download single file from USGS M2M by download url
        """

        if auth:
            r = requests.get(url, stream=True, allow_redirects=True, timeout=timeout, auth=auth)
        else:
            r = requests.get(url, stream=True, allow_redirects=True, timeout=timeout)
        r.raise_for_status()

        expected_file_size = int(r.headers.get("content-length", -1))
        if file_name is None:
            try:
                file_name = r.headers["Content-Disposition"].split('"')[1]
            except Exception:
                file_name = os.path.basename(url)
                # raise Exception("Can not automatically identify file_name.")

        file_path = os.path.join(output_dir, file_name)
        # TODO: Check for existing files and whether they have the correct file size
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        if os.path.exists(file_path) and not overwrite:
            return file_path
        elif os.path.exists(file_path) and overwrite:
            os.remove(file_path)

        with open(file_path, "wb") as f:
            # start = time.perf_counter()
            for chunk in r.iter_content(chunk_size=chunk_size):
                f.write(chunk)
            # duration = time.perf_counter() - start

        file_size = os.stat(file_path).st_size
        # speed = round((file_size / duration) / (1000 * 1000), 2)

        if check_size:
            if expected_file_size != file_size:
                os.remove(file_path)
                raise Exception(f"Failed to download from {url}")

        return file_path


class SentinelUnzipHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        """
        Unzips the downloaded Sentinel data file.

        Variables needed:
            zip_file: Path to the downloaded zip file

        Variables set:
            scene_folder: Path to the unzipped scene folder
        """
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        time_start = time.perf_counter()

        # get job variables
        zip_file = job.get_variable("zip_file")
        scene = job.get_variable("scene")
        remove_zip = self.get_config("remove_zip", False)
        log_with_context(f"Input variables: {zip_file=}", log_context)

        if not zip_file or not os.path.exists(zip_file) or not zip_file.endswith(".zip"):
            log_with_context("Invalid input variables", log_context)
            return result.failure()

        try:
            # Create the output directory (same as zip file but without .zip extension)
            output_dir = os.path.dirname(zip_file)

            with zipfile.ZipFile(zip_file, "r") as zip_ref:
                zip_ref.extractall(output_dir)

            if remove_zip:
                os.remove(zip_file)

            time_end = time.perf_counter()
            log_with_context(
                f"Successfully unzipped {scene['scene_id']} to: {output_dir}, {format_duration(time_end - time_start)}",
                log_context,
            )

            return result.success().variable_string(
                name="scene_folder", value=os.path.join(output_dir, scene["scene_id"])
            )

        except zipfile.BadZipFile:
            log_with_context(f"Invalid zip file: {zip_file}", log_context)
            return result.failure()
        except Exception as e:
            log_with_context(f"Error unzipping file {zip_file}: {str(e)}", log_context)
            return result.failure()


class SentinelCheckIntegrityHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}

        # get job variables
        scene = job.get_variable("scene")
        scene_folder = job.get_variable("scene_folder")
        log_with_context(f"Input variables: {scene_folder=}", log_context)

        if not scene_folder or not os.path.exists(scene_folder):
            log_with_context("Invalid input variables", log_context)
            return result.failure()

        try:
            validity = sentinel.validate_integrity(scene_folder, scene["scene_id"])
        except Exception as e:
            log_with_context(f"Error checking integrity: {str(e)}", log_context)
            return result.failure()

        log_with_context(f"Successfully checked integrity for {scene['scene_id']}", log_context)

        return result.success().variable_boolean(name="validity", value=validity)


class SentinelExtractMetadataHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}

        # get job variables
        scene = job.get_variable("scene")
        scene_id = scene["scene_id"]
        scene_folder = job.get_variable("scene_folder")
        collections_dir = self.get_config("collections_dir", os.path.dirname(__file__))
        log_with_context(f"Input variables: {scene_folder=}, {scene_id=}", log_context)

        if not scene_folder or not os.path.exists(scene_folder) or not scene_id or not scene:
            log_with_context("Invalid input variables", log_context)
            return result.failure()

        try:
            stac_item = sentinel.create_metadata(
                scene_path=scene_folder, scene_id=scene_id, collections_dir=collections_dir
            )
        except Exception as e:
            log_with_context(f"Error extracting metadata: {str(e)}", log_context)
            return result.failure()

        log_with_context(f"Successfully extracted metadata for {scene['scene_id']}", log_context)

        return result.success().variable_string(name="stac_item", value=str(stac_item))


class SentinelRegisterMetadataHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}

        # get config
        api_url = self.get_config("stac_api_url", "")
        api_user = self.get_config("stac_api_user", None)
        api_pw = self.get_config("stac_api_pw", None)
        api_ca_cert = self.get_config("stac_api_ca_cert", None)
        file_deletion = self.get_config("stac_file_deletion", True)

        # get job variables
        scene = job.get_variable("scene")
        collection = job.get_variable("collection")
        stac_item = job.get_variable("stac_item")
        log_with_context(f"Input variables: {scene=}, {collection=}", log_context)

        if not scene or not collection or not stac_item:
            log_with_context("Invalid input variables", log_context)
            return result.failure()

        # Asset href rewriting
        rewrite_asset_hrefs = self.get_config("rewrite_asset_hrefs", None)

        try:
            stac.register_metadata(
                stac_file=stac_item,
                collection=collection,
                api_url=api_url,
                api_user=api_user,
                api_pw=api_pw,
                api_ca_cert=api_ca_cert,
                file_deletion=file_deletion,
                rewrite_asset_hrefs=rewrite_asset_hrefs,
            )

            return result.success()
        except Exception as e:
            log_with_context(f"Error registering metadata: {str(e)} at URL {str(api_url)}", log_context)
            return result.failure()
