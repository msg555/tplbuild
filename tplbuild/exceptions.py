import sys


def _extract_jinja_frames(exc_tb) -> str:
    """
    Extract all the frames in the traceback that look like jinja frames

    Returns:
        A multiline string with a formatted traceback of all the Jinja
        synthetic frames or an empty string if none were found.
    """
    lines = []
    while exc_tb:
        code = exc_tb.tb_frame.f_code
        if code.co_name in (
            "template",
            "top-level template code",
        ) or code.co_name.startswith("block "):
            lines.append(f"  at {code.co_filename}:{exc_tb.tb_lineno}")
        exc_tb = exc_tb.tb_next
    return "\n".join(lines)


class TplBuildException(Exception):
    """
    Base class of all exceptions raised by tplbuild.
    """

    def __init__(self, message: str, *, more_message: str = "") -> None:
        super().__init__(message)
        self.more_message = more_message

    def update_message(self, message: str) -> None:
        """Change the exception message"""
        self.args = (message,)


class TplBuildTemplateException(TplBuildException):
    """
    Exception due to a failure to render a template. Will automatically attach
    jinja template exception information if present in the currently active
    exception info.
    """

    def __init__(self, message) -> None:
        more_message = ""
        exc_info = sys.exc_info()
        if exc_info:
            more_message = _extract_jinja_frames(exc_info[2])
        super().__init__(message, more_message=more_message)


class TplBuildContextException(TplBuildException):
    """
    Exception during processing of build context data.
    """


class TplBuildNoSourceImageException(TplBuildException):
    """
    Exception raised when a source image lookup fails with check_only=True.
    """
