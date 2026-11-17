"""READMEs link to the published docs site; the lint job checks them against the built one."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_site_links  # noqa: E402

URL = "https://example.org/kit/"


def test_a_link_needs_its_page_and_its_anchor(tmp_path):
    site = tmp_path / "site"
    (site / "deployments").mkdir(parents=True)
    (site / "index.html").write_text("<h1>Kit</h1>")
    (site / "deployments/index.html").write_text('<h2 id="run">Run</h2>')
    readme = tmp_path / "README.md"
    readme.write_text(
        f"[home]({URL}) [page]({URL}deployments/) [anchor]({URL}deployments/#run) "
        f"See {URL}deployments/. [moved]({URL}components/visualizer/) [gone]({URL}deployments/#stop)"
    )
    assert check_site_links.broken_links([readme], site, URL) == [
        f"{readme}: {URL}components/visualizer/ has no page",
        f"{readme}: {URL}deployments/#stop has no #stop",
    ]


def test_the_site_url_comes_from_mkdocs(tmp_path):
    (tmp_path / "mkdocs.yaml").write_text("site_name: Kit\nsite_url: https://example.org/kit\n")
    assert check_site_links.site_url(tmp_path) == URL
