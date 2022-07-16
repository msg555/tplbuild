
Jinja Render Environment
------------------------

Filters
=======

Anywhere a Jinja template is rendered within `tplbuild` will have access to the
following filters.

:code:`shell_escape`
~~~~~~~~~~~~~~~~~~~~

This will escape the passed string to be passed as a single argument
to a command-line shell. Example usage:

.. code-block:: jinja

  RUN echo {{ vars.welcome_message | shell_escape }}


:code:`ignore_escape`
~~~~~~~~~~~~~~~~~~~~~

This will escape the passed string appropriately to be passed as a literal
path when templating a dockerignore file. This is useful if your paths may
contain characters with special semantics like '!', '?' or '\'.

.. code-block:: jinja

  !{{ vars.base_path | ignore_escape }}/src
