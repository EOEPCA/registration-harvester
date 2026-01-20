from unittest.mock import Mock

import pytest

from worker.common.resources.stac import validate_configured_prefix_rewrite, asset_hrefs_rewrite


@pytest.mark.parametrize(
    "rewrite_config, in_url, out_url",
    [({"prefix_from": "/abc/", "prefix_to": "/def/"}, "/abc/def/ghi.test", "/def/def/ghi.test"),
     ({"prefix_from": "/abc/", "prefix_to": "/def/"}, "/xyz/def/ghi.test", "/xyz/def/ghi.test"),
     ({"prefix_from": "/abc/", "prefix_to": "/def/"}, "/def/def/ghi.test", "/def/def/ghi.test"),
     ({"prefix_from": "/abc/", "prefix_to": "/def/"}, "", ""),

     ({"prefix_from": "/abc/", "prefix_to": "/abc/"}, "/abc/def/ghi.test", "/abc/def/ghi.test"),
     ({"prefix_from": "/abc/", "prefix_to": "/abc/"}, "/def/def/ghi.test", "/def/def/ghi.test"),

     ({}, "/abc/def/ghi.test", "file:///abc/def/ghi.test"),
     (None, "/abc/def/ghi.test", "file:///abc/def/ghi.test"),
     ({"prefix_from": "", "prefix_to": ""}, "/abc/def/ghi.test", "/abc/def/ghi.test")]
)
def test_url_rewrite_applies_configured_change_correctly(rewrite_config, in_url, out_url):
    stac_item = Mock()
    stac_item.assets = {"a1": Mock()}
    stac_item.assets["a1"].href = in_url

    config = validate_configured_prefix_rewrite(rewrite_config)
    asset_hrefs_rewrite(stac_item, config["prefix_from"], config["prefix_to"])

    assert stac_item.assets["a1"].href == out_url
