"""O ponto de entrada do aplicativo empacotado (o PyInstaller precisa de um script): o mesmo ``sh-analyzer-gui`` do
``pyproject.toml``."""

from sh_analyzer_gui.app import main

raise SystemExit(main())
