0.0.2
=====

- Moved profile variables to appear under the `vars` variable instead of
  existing globally when rendering Jinja templates.
- Added support for --set and --set-json for build commands.
- Fix manifest creation to not include empty fields that may not be supported by
  some registries.
