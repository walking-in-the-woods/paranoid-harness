# fs_guard

Файловый шлюз: whitelist/blacklist/writable, NFKC-нормализация,
защита от path traversal и symlink escape.

::: harness.fs_guard
    options:
      members:
        - FileSystemGuard
        - _glob_to_regex
      show_root_heading: false
