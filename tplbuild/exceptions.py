class TplBuildException(Exception):
    """
    Base class of all exceptions raised by tplbuild.
    """

    def __init__(self, message, *, more_message="") -> None:
        super().__init__(message)
        self.more_message = more_message


class TplBuildTemplateException(TplBuildException):
    """
    Exception due to a failure to render a template.
    """


class TplBuildContextException(TplBuildException):
    """
    Exception during processing of build context data.
    """


class TplBuildNoSourceImageException(TplBuildException):
    """
    Exception raised when a source image lookup fails with check_only=True.
    """
