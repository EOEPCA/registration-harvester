import os
import datetime
import time
import requests
import netrc
import zipfile
from pathlib import Path
from dateutil.parser import parse
from worker.common.log_utils import configure_logging, log_with_context, format_duration, format_file_metrics
from worker.common.types import ExternalJob, JobResultBuilder, JobResult
from worker.common.client import flowableClient
from registration_library.providers import esa_cdse as cdse
from registration_library.datasets import sentinel
from registration_library.resources import stac
from worker.common.task_handler import TaskHandler

configure_logging()


class SentinelDiscoverHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult :
        """
        Searches for new data since last workflow execution

        Variables needed:
            start_time
            end_time
            order_id

        Variables set:
            scenes: List of scenes found
        """

        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        log_with_context("Discovering new sentinel data ...", log_context)

        # Workflow variables
        start_time = job.get_variable("start_time")
        end_time = job.get_variable("end_time")
        order_id = job.get_variable("order_id")
        if order_id is None:
            order_id = job.process_instance_id

        if start_time is None and end_time is None:
            history = flowableClient.get_process_instance_history(job.process_instance_id)
            if "startTime" in history:
                current_time = parse(history["startTime"])  # 2024-03-17T01:02:22.487+0000
                log_with_context("use startTime from workflow: %s" % current_time, log_context)
            else:
                current_time = datetime.datetime.now()
                log_with_context("use datetime.now() as startTime: %s" % current_time, log_context)
            end_time = datetime.datetime(current_time.year, current_time.month, current_time.day, current_time.hour)
            start_time = end_time - datetime.timedelta(hours=1)
            start_time = start_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            end_time = end_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        log_with_context(f"Search interval: {start_time} - {end_time}", log_context)

        # Discovering scenes
        try:
            scenes = cdse.search_scenes_ingestion(date_from=start_time, date_to=end_time, filters=None)
        except Exception as e:
            log_with_context(f"Error searching scenes: {e}", log_context)
            return result.error(f"Error searching scenes: {e}")
        
        log_with_context(f"Found {len(scenes)} scenes", log_context)

        return result.success().variable_json(name="scenes", value=scenes)


class SentinelDownloadHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult :
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        time_start = time.perf_counter()

        scene = job.get_variable("scene")
        log_with_context(f"Input variables: {scene=}", context=log_context, log_level="debug")
        if 'cdse_id' not in scene and 'uid' in scene:
                scene['cdse_id'] = scene['uid']

        # TODO: Calculate scene path according to https://gitlab.dlr.de/terrabyte/data-management/ingestion/terrabyte-ingestion-lib/-/blob/main/terrabyte/ingestion/providers/esa_cdse.py#L241-251
        scene_path = Path(self._get_scene_path(self.handler_config['base_dir'], scene))

        # CDSE download url
        if scene['scene_id'].startswith('S1'):
            url = f"https://download.dataspace.copernicus.eu/odata/v1/Products({scene['uid']})/$value" #$zip
        else:
            url = f"https://download.dataspace.copernicus.eu/odata/v1/Products({scene['uid']}))/$value" 
        access_key = self._get_access_token()
        headers = {"Authorization": f"Bearer {access_key}"}

        try:
            session = requests.Session()
            session.headers.update(headers)
            response = session.get(url, stream=True)
            response.raise_for_status()
            
            if scene_path.suffix in ['.SAFE', '.SEN3']: 
                scene_path = scene_path.parent / f"{scene['scene_id']}.zip"
            scene_path.parent.mkdir(parents=True, exist_ok=True)
            log_with_context(f"Start downloading {scene['scene_id']} (Size: {scene['ContentLength']}, Destination: {scene_path}) ", log_context)
            with scene_path.open(mode="wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        file.write(chunk)
            if scene_path.suffix == '.zip':
                if not zipfile.is_zipfile(scene_path):
                    scene_path.unlink(missing_ok=True)
                    raise Exception("File downloaded is not a valid zip file, remove file")
            elif scene_path.suffix == '.nc':
                pass
        except requests.RequestException as e:
            error_messages = {
                404: "Download not found",
                403: "Download failed - Access denied",
                504: "Download timeout",
            }
            status_code = getattr(e.response, 'status_code', None)
            error_msg = error_messages.get(status_code, "Download failed")
            log_with_context(f"{error_msg} for {url}: {str(e)}", log_context)
            return result.failure()
        except Exception as e:
            log_with_context(f"Download failed for {url}: {str(e)}", log_context)
            return result.failure()

        time_end = time.perf_counter()
        log_with_context(f"Downloaded {scene_path} ({format_file_metrics(scene_path.stat().st_size, time_end - time_start)})", log_context)

        collection = sentinel.get_collection_name(scene['scene_id'])
        log_with_context(f"{collection=}")

        return (
            result.success()
                .variable_string(name="zip_file", value=str(scene_path))
                .variable_string(name="collection", value=str(collection))
        )

    def _get_scene_path(self, base_dir, scene):
        s3path = Path(scene['S3Path'].lstrip('/'))
        return str(Path(base_dir) / s3path)

    def _get_access_token(self):
        if 'token_expire_time' in os.environ and time.time() <= (float(os.environ['token_expire_time'])-5):
            return os.environ['s3_access_key']

        auth = netrc.netrc().authenticators('dataspace.copernicus.eu')
        username = auth[0]
        password = auth[2]
        auth_server_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
        data = {
            "client_id": "cdse-public",
            "grant_type": "password",
            "username": username,
            "password": password,
        }

        token_time = time.time()
        response = requests.post(auth_server_url, data=data, verify=True, allow_redirects=False).json()
        os.environ['token_expire_time'] = str(token_time + response.get("expires_in", 0))
        os.environ['s3_access_key'] = response.get("access_token", "")
        return (os.environ['s3_access_key'])

    def _download_data(
        self, 
        url,
        output_dir,
        file_name=None,
        chunk_size=1024 * 1000,
        timeout=300,
        auth=None,
        check_size=True,
        overwrite=False
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
            except Exception as e:
                file_name = os.path.basename(url)
                #raise Exception("Can not automatically identify file_name.")
        
        file_path = os.path.join(output_dir, file_name)
        # TODO: Check for existing files and whether they have the correct file size
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        if os.path.exists(file_path) and not overwrite:
            return file_path
        elif os.path.exists(file_path) and overwrite:
            os.remove(file_path)

        with open(file_path, "wb") as f:
            start = time.perf_counter()
            for chunk in r.iter_content(chunk_size=chunk_size):
                f.write(chunk)
            duration = time.perf_counter() - start
            
        file_size = os.stat(file_path).st_size
        speed = round((file_size / duration) / (1000 * 1000), 2)

        if check_size:
            if expected_file_size != file_size:
                os.remove(file_path)
                raise Exception(f"Failed to download from {url}")

        return file_path


class SentinelUnzipHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult :
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
        log_with_context(f"Input variables: {zip_file=}", log_context)
        if not zip_file or not os.path.exists(zip_file) or not zip_file.endswith('.zip'):
            log_with_context("Invalid input variables", log_context)
            return result.failure()

        try:
            # Create the output directory (same as zip file but without .zip extension)
            output_dir = os.path.dirname(zip_file)

            with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                zip_ref.extractall(output_dir)

            os.remove(zip_file)
            
            time_end = time.perf_counter()
            log_with_context(f"Successfully unzipped {scene['scene_id']} to: {output_dir}, {format_duration(time_end - time_start)}", log_context)
            
            return result.success().variable_string(name="scene_folder", value=os.path.join(output_dir, scene['scene_id']))

        except zipfile.BadZipFile:
            log_with_context(f"Invalid zip file: {zip_file}", log_context)
            return result.failure()
        except Exception as e:
            log_with_context(f"Error unzipping file {zip_file}: {str(e)}", log_context)
            return result.failure()


class SentinelCheckIntegrityHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult :
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}

        # get job variables
        scene = job.get_variable("scene")
        scene_folder = job.get_variable("scene_folder")
        log_with_context(f"Input variables: {scene_folder=}", log_context)

        if not scene_folder or not os.path.exists(scene_folder):
            log_with_context("Invalid input variables", log_context)
            return result.failure()

        try:
            validity = sentinel.validate_integrity(scene_folder, scene['scene_id'])
        except Exception as e:
            log_with_context(f"Error checking integrity: {str(e)}", log_context)
            return result.failure()

        log_with_context(f"Successfully checked integrity for {scene['scene_id']}", log_context)

        return (
            result.success()
                .variable_boolean(name="validity", value=validity)
        )


class SentinelExtractMetadataHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult :
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}

        # get job variables
        scene = job.get_variable("scene")
        scene_id = scene['scene_id']
        scene_folder = job.get_variable("scene_folder")
        log_with_context(f"Input variables: {scene_folder=}, {scene_id=}", log_context)
        if not scene_folder or not os.path.exists(scene_folder) or not scene_id or not scene:
            log_with_context("Invalid input variables", log_context)
            return result.failure()

        try:
            stac_item = sentinel.sentinel_metadata(scene_folder, scene_id)
        except Exception as e:
            log_with_context(f"Error extracting metadata: {str(e)}", log_context)
            return result.failure()

        log_with_context(f"Successfully extracted metadata for {scene['scene_id']}", log_context)

        return result.success().variable_string(name="stac_item", value=str(stac_item))


class SentinelRegisterMetadataHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult :
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}

        # get job variables
        scene = job.get_variable("scene")
        collection = job.get_variable("collection")
        stac_item = job.get_variable("stac_item")
        log_with_context(f"Input variables: {scene=}, {collection=}", log_context)
        if not scene or not collection or not stac_item:
            log_with_context("Invalid input variables", log_context)
            return result.failure()

        try:
            stac.register_metadata(
                stac_file=stac_item,
                scene_id=scene['scene_id'],
                inventory_id='unused',
                inventory_collection='unused',
                collection=collection,
                api_user=self.handler_config['api_user'],
                api_url=self.handler_config['api_url'],
                api_pw=self.handler_config['api_pw'],
                inventory_dsn='unused',
                file_deletion=False
            )

            return result.success()
        except Exception as e:
            log_with_context(f"Error registering metadata: {str(e)}", log_context)
            return result.failure()
