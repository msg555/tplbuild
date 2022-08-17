from typing import List

from tplbuild.plan import BuildOperation
from tplbuild.tplbuild import TplBuild


def debug_build_operations(tplbld: TplBuild, build_ops: List[BuildOperation]) -> None:
    """
    Print out rendered build operations for debugging purposes.
    """
    first = True
    rendered_ops = tplbld.executor.render_build_ops(build_ops)
    for rendered_op in rendered_ops:
        if not first:
            print("")
        first = False

        print(f"# Building {rendered_op.build_title}")
        print(rendered_op.dockerfile)

        for tag, push_tag in rendered_op.tags.items():
            if push_tag:
                print(f"# Push {rendered_op.build_title} as {tag}")
            else:
                print(f"# Tag {rendered_op.build_title} as {tag}")
