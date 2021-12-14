from .tplbuild import TplBuild


def main():
    """
    Main tplbuild entrypoint.
    """
    bld = TplBuild.from_path(".")
    print(bld.render())


main()
