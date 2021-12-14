class TplBuildException(Exception):
    """
    Base class of all exceptions raised by tplbuild.
    """


class TplBuildTemplateException(TplBuildException):
    """
    Exception due to a failure to render a template.
    """
