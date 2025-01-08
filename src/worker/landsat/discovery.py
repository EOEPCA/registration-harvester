from typing import Any

from eodm.extract import extract_stac_api_items
from pystac import Item

from worker.common.providers import usgs


def handle_item(item: Item) -> dict[str, Any]:
    item_dict = item.to_dict()
    scene = {}
    scene["id"] = item_dict["id"].replace("_SR", "")
    scene["collection"] = usgs.get_collection_name(item_dict["id"])
    scene["properties"] = {}
    scene["properties"]["landsat:scene_id"] = item_dict["properties"]["landsat:scene_id"]
    return scene


def search(api_url: str, collections: list[str], bbox: list[str], interval: str, limit: int, query: dict) -> list:
    return list(
        map(
            handle_item,
            extract_stac_api_items(
                url=api_url,
                collections=collections,
                bbox=bbox,
                datetime_interval=interval,
                limit=limit,
                query=query,
                filter=None,
            ),
        )
    )
