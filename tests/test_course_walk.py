from __future__ import annotations

from playwright.sync_api import sync_playwright

from hictc_web_scraper.course import walk_course

FIXTURE = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Fixture</title></head>
<body>
  <div class="catalog-tree">
    <div class="tree-node" id="tree_node_1">
      <div class="tree-node-content is-current">
        <p class="text text-weight ellipsis-text-two" title="Chapter A">Chapter A</p>
      </div>
      <div class="tree-node-children">
        <div class="tree-node" id="tree_node_2">
          <div class="tree-node-content">
            <p class="text text-weight ellipsis-text-two" title="A.1 Section">A.1 Section</p>
          </div>
          <div class="tree-node-children"></div>
        </div>
      </div>
    </div>
  </div>
  <div id="innerContent">
    <div class="content-style-html"><p>Initial placeholder</p></div>
  </div>
  <script>
    document.querySelectorAll('.tree-node-content').forEach((element) => {
      element.addEventListener('click', () => {
        const title = element.querySelector('p').getAttribute('title');
        document.querySelector('#innerContent').innerHTML =
          '<div class="content-displayName" title="' + title + '">' + title + '</div>' +
          '<div class="content-style-html"><p>Content of ' + title + '</p>' +
          '<img src="/img/pic.png"></div>';
      });
    });
  </script>
</body>
</html>
"""


def test_walk_course_extracts_blocks() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content(FIXTURE)
        blocks = walk_course(page, delay=0.05, leaf_settle=0.6, parent_settle=0.5)
        browser.close()

    titles = [block.title for block in blocks]
    assert titles == ["Chapter A", "A.1 Section"]
    assert blocks[0].kind == "html"
    assert "Content of A.1 Section" in blocks[1].html
    assert "/img/pic.png" in blocks[1].urls
    assert blocks[1].breadcrumb == ["Chapter A", "A.1 Section"]


RERENDER_FIXTURE = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Rerender</title></head>
<body>
  <div id="catalog"></div>
  <div id="innerContent"></div>
  <script>
    const items = ["Alpha", "Beta", "Gamma"];
    let counter = 0;
    function render() {
      const catalog = document.querySelector('#catalog');
      catalog.innerHTML = '';
      items.forEach((title) => {
        counter += 1;
        const node = document.createElement('div');
        node.className = 'tree-node';
        node.id = 'tree_node_' + counter;
        const content = document.createElement('div');
        content.className = 'tree-node-content';
        const p = document.createElement('p');
        p.className = 'text';
        p.setAttribute('title', title);
        p.textContent = title;
        content.appendChild(p);
        content.addEventListener('click', () => {
          document.querySelector('#innerContent').innerHTML =
            '<div class="content-style-html"><p>Content of ' + title + '</p></div>';
          render();
        });
        node.appendChild(content);
        const children = document.createElement('div');
        children.className = 'tree-node-children';
        node.appendChild(children);
        catalog.appendChild(node);
      });
    }
    render();
  </script>
</body>
</html>
"""


def test_walk_course_terminates_on_rerendering_tree() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content(RERENDER_FIXTURE)
        blocks = walk_course(page, delay=0.02, leaf_settle=0.3, parent_settle=0.3)
        browser.close()

    assert [block.title for block in blocks] == ["Alpha", "Beta", "Gamma"]
    assert all(block.kind == "html" for block in blocks)


def test_walk_course_empty_page() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content("<html><body><div id='innerContent'></div></body></html>")
        blocks = walk_course(page, delay=0.0, leaf_settle=0.1, parent_settle=0.1)
        browser.close()
    assert blocks == []
