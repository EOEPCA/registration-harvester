from pystac import Catalog, Collection, Item

from worker.common.task_handler import TaskHandler
from worker.common.types import ExternalJob, JobResult, JobResultBuilder
from worker.common.log_utils import configure_logging, log_with_context
from eodm.load import load_stac_api_collections, load_stac_api_items

configure_logging()


class StacCatalogHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        """
        Load STAC catalog and extract collection paths

        Variables needed:
            stac_catalog_path: Path to the STAC catalog file

        Variables set:
            collection_paths: List of collection paths
        """
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        stac_catalog_path = job.get_variable("stac_catalog_path")
        catalog = Catalog.from_file(stac_catalog_path)

        collection_paths = [collection.get_self_href() for collection in catalog.get_all_collections()]
        log_with_context(
            f"StacCatalogHandler finished. Starting {len(collection_paths)} StacCollectionHandler tasks.", log_context
        )
        return result.success().variable_json(name="collection_paths", value=collection_paths)


class StacCollectionHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        """
        Publish STAC collection to STAC API

        Variables needed:
            collection_paths: List of collection paths

        Variables set:
            item_paths: List of item paths
        """
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        collection_path = job.get_variable("collection_paths")
        collection = Collection.from_file(collection_path)

        try:
            log_with_context(f"Publishing collection {collection.id}", log_context)
            load_stac_api_collections(
                url=self.get_config("stac_api", ""),
                collections=[collection],
                verify=False,
                update=True,
                auth=(self.get_config("stac_api_user", None), self.get_config("stac_api_pw", None)),
            )
        except Exception as e:
            log_with_context(f"Error publishing collection: {str(e)}", log_context)
            return result.failure(f"Error publishing collection: {str(e)}")

        item_paths = [item.get_self_href() for item in collection.get_all_items()]
        log_with_context(
            f"StacCollectionHandler finished publishing collection {collection.id}. Starting {len(item_paths)} StacItemHandler tasks.",
            log_context,
        )
        return result.success().variable_json(name="item_paths", value=item_paths)


class StacItemHandler(TaskHandler):
    def execute(self, job: ExternalJob, result: JobResultBuilder, config: dict) -> JobResult:
        """
        Publish STAC item to STAC API

        Variables needed:
            item_paths: List of item paths

        Variables set:
            None
        """
        log_context = {"JOB": job.id, "BPMN_TASK": job.element_name}
        item_paths = job.get_variable("item_paths")
        item = Item.from_file(item_paths)

        try:
            log_with_context(f"Publishing item {item.id}", log_context)
            load_stac_api_items(
                url=self.get_config("stac_api", ""),
                items=[item],
                verify=False,
                update=True,
                auth=(self.get_config("stac_api_user", None), self.get_config("stac_api_pw", None)),
            )
        except Exception as e:
            log_with_context(f"Error publishing item: {str(e)}", log_context)
            return result.failure(f"Error publishing item: {str(e)}")

        log_with_context(f"Finished publishing item {item.id}", log_context)
        return result.success()
