from typing import Iterable, List
from unittest.mock import Mock, call

import pytest

from .exceptions import TplBuildException
from .images import (
    CommandImage,
    CopyCommandImage,
    ImageDefinition,
    SourceImage,
)
from .utils import (
    line_reader,
    visit_graph,
)


class TestImageNode(ImageDefinition):
    """Test node with variable number of dependencies"""

    def __init__(self, depth: int, deps: List[ImageDefinition]) -> None:
        super().__init__()
        self.depth = depth
        self.deps = deps

    def calculate_hash(self, symbolic: bool) -> str:
        raise NotImplementedError()

    def get_dependencies(self) -> List[ImageDefinition]:
        return list(self.deps)

    def set_dependencies(self, deps: Iterable[ImageDefinition]) -> None:
        self.deps = list(deps)


@pytest.mark.unit
def test_visit_graph_cycle():
    """Test that cycle detection works correct for visit_graph"""
    img = CommandImage(
        parent=None,
        command="RUN",
        args="stuff",
    )
    img.parent = img

    visit_mock = Mock(side_effect=lambda img: img)
    with pytest.raises(TplBuildException, match="Cycle detected in graph"):
        visit_graph([img], visit_mock)
    visit_mock.assert_called_once_with(img)

    img_list = [SourceImage(repo="hi", tag="bye")]
    for _ in range(9):
        img_list.append(
            CopyCommandImage(
                parent=img_list[-1],
                context=img_list[-1],
                command="hello",
            )
        )

    # Ensure that we don't detect a cycle for overlapping DAG and that
    # we only visit each unique image once.
    visit_mock.reset_mock()
    assert visit_graph(img_list, visit_mock) == img_list
    assert visit_mock.call_count == 10

    # Make sure we detect a deep cycle
    img_list[2].context = img_list[6]
    visit_mock.reset_mock()
    with pytest.raises(TplBuildException, match="Cycle detected in graph"):
        visit_graph(img_list, visit_mock)


@pytest.mark.unit
def test_visit_graph_generate():
    """Test visit graph behavior toward genearting new nodes"""

    def visit_replace(image: ImageDefinition) -> ImageDefinition:
        assert isinstance(image, TestImageNode)

        if image.depth < 10:
            return TestImageNode(
                image.depth,
                [TestImageNode(image.depth + 1, []) for _ in range(2)],
            )

        return image

    root = TestImageNode(0, [])
    result = visit_graph([root], visit_replace)
    assert len(result) == 1
    assert len(result) == 1 and result[0] is not root

    visit_mock = Mock(side_effect=lambda img: img)
    visit_graph(result, visit_mock)
    assert visit_mock.call_count == 2 ** 11 - 1

    def visit_update(image: ImageDefinition) -> ImageDefinition:
        assert isinstance(image, TestImageNode)

        if image.depth < 10:
            image.set_dependencies(
                [TestImageNode(image.depth + 1, []) for _ in range(2)]
            )

        return image

    root = TestImageNode(0, [])
    result = visit_graph([root], visit_update)
    assert len(result) == 1 and result[0] is root

    visit_mock.reset_mock()
    visit_graph(result, visit_mock)
    assert visit_mock.call_count == 2 ** 11 - 1


@pytest.mark.unit
def test_visit_graph():
    """Test visit graph behavior"""
    nodes = []
    for _ in range(10):
        nodes.append(TestImageNode(-1, list(nodes)))

    visit_mock = Mock(side_effect=lambda img: img)
    assert visit_graph(nodes, visit_mock) == nodes
    assert visit_mock.call_count == 10

    new_node = TestImageNode(-1, [])

    def visit_replace(image: ImageDefinition) -> ImageDefinition:
        if image is nodes[3]:
            return new_node
        return image

    new_nodes = visit_graph(nodes, visit_replace)
    new_nodes_exp = list(nodes)
    new_nodes_exp[3] = new_node
    assert new_nodes == new_nodes_exp

    for image in nodes[4:]:
        assert nodes[3] not in image.deps
        assert new_node in image.deps


@pytest.mark.unit
def test_visit_graph_order():
    """Test visit graph order traversal"""
    nodes = [TestImageNode(-1, []) for _ in range(5)]
    nodes[2].deps = [nodes[3]]
    nodes[1].deps = [nodes[4], nodes[2]]
    nodes[0].deps = [nodes[4], nodes[1]]

    visit_mock_pre = Mock(side_effect=lambda img: img)
    visit_mock_post = Mock()
    assert (
        visit_graph(nodes[:1], visit_mock_pre, visit_func_post=visit_mock_post)
        == nodes[:1]
    )

    visit_mock_pre.assert_has_calls(
        [
            call(nodes[0]),
            call(nodes[4]),
            call(nodes[1]),
            call(nodes[2]),
            call(nodes[3]),
        ]
    )
    visit_mock_post.assert_has_calls(
        [
            call(nodes[4]),
            call(nodes[3]),
            call(nodes[2]),
            call(nodes[1]),
            call(nodes[0]),
        ]
    )


@pytest.mark.unit
def test_line_reader():
    """Test line reader behavior"""

    assert list(line_reader("hi\n\nthere")) == [(0, "hi"), (2, "there")]
    assert list(line_reader("hi\n\nthere\n")) == [(0, "hi"), (2, "there")]
    assert list(line_reader("hi\n\nthe\\\nre\n")) == [(0, "hi"), (3, "there")]
    assert list(line_reader("hi\n\nthere\\\n")) == [(0, "hi"), (2, "there")]
    assert list(line_reader("hi\n# comment\nthere\\\n")) == [(0, "hi"), (2, "there")]
    assert list(line_reader("hi\n# comment\\\nthere\\\n")) == [(0, "hi"), (2, "there")]
    assert list(line_reader("hi\nthere\\\n# comment")) == [
        (0, "hi"),
        (2, "there# comment"),
    ]
    assert not list(line_reader(""))
    assert not list(line_reader(" #comment\n# comment\n  #  comment 2\n\n"))
    assert list(line_reader("\n\nhi\n\nthere")) == [(2, "hi"), (4, "there")]
    assert list(line_reader("  \\\n\nhi\n\nthere")) == [(2, "hi"), (4, "there")]
    assert list(line_reader("\\\nhi\n\nthere")) == [(1, "hi"), (3, "there")]